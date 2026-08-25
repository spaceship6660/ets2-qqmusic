import pytest

from qqm import library


CREATED_FIXTURE = {
    "code": 0,
    "data": {
        "disslist": [
            {"dissid": 111, "dissname": "自建一", "song_count": 12},
            {"dissid": 222, "dissname": "自建二", "song_count": 3},
        ]
    },
}

FAV_FIXTURE = {
    "code": 0,
    "data": {"disslist": [{"dissid": 333, "dissname": "收藏歌单", "song_count": 50}]},
}

DISS_FIXTURE = {
    "code": 0,
    "data": {
        "total": 2,
        "songlist": [
            {"mid": "MA", "id": 1, "name": "歌A", "interval": 200,
             "singer": [{"name": "甲"}], "album": {"name": "专A"}},
            {"mid": "MB", "id": 2, "name": "歌B", "interval": 180,
             "singer": [{"name": "乙"}, {"name": "丙"}], "album": {"name": "专B"}},
        ],
    },
}


@pytest.fixture
def lib(monkeypatch):
    calls = []

    def fake_http_get(url, cookie=None, timeout=20):
        calls.append(("GET", url))
        if "fcg_user_created_diss" in url:
            return CREATED_FIXTURE
        if "fcg_get_profile_order_asset" in url:
            return FAV_FIXTURE
        if "fcg_get_profile_homepage" in url:
            return {"code": 0, "data": {"encrypt_uin": "ENCUIN"}}
        raise AssertionError(url)

    def fake_post_musicu(body, cookie=None, timeout=20):
        calls.append(("POST", body))
        module = body.get("req", {}).get("module", "")
        method = body.get("req", {}).get("method", "")
        if module.startswith("music.srfDissInfo"):
            return DISS_FIXTURE
        if method in ("AddSonglist", "DelSonglist"):
            return {"req": {"code": 0, "data": {"retCode": 0}}}
        raise AssertionError(body)

    monkeypatch.setattr(library, "_http_get_json", fake_http_get)
    monkeypatch.setattr(library, "_post_musicu", fake_post_musicu)
    return calls


class TestEncryptUin:
    def test_returns_encrypt_uin(self, lib):
        assert library.get_encrypt_uin("10001", "ck") == "ENCUIN"


class TestPlaylists:
    def test_lists_created_and_fav(self, lib):
        pls = library.list_playlists("10001", "ck", include_fav=True)
        assert [(p.pid, p.kind) for p in pls] == [(111, "created"), (222, "created"), (333, "fav")]
        assert pls[0].name == "自建一"
        get_urls = [u for op, u in lib if op == "GET"]
        assert any("fcg_user_created_diss" in u for u in get_urls)

    def test_created_only(self, lib):
        pls = library.list_playlists("10001", "ck", include_fav=False)
        assert all(p.kind == "created" for p in pls)


class TestPlaylistSongs:
    def test_normal_playlist_uses_disstid(self, lib):
        songs = library.get_playlist_songs(111, "ck")
        assert [s.mid for s in songs] == ["MA", "MB"]
        post = [b for op, b in lib if op == "POST"][0]
        assert post["req"]["param"]["disstid"] == 111

    def test_liked_uses_dirid_201_and_enc_uin(self, lib):
        songs = library.get_playlist_songs(0, "ck", liked=True, enc_uin="EU")
        assert len(songs) == 2
        post = [b for op, b in lib if op == "POST"][0]
        assert post["req"]["param"]["dirid"] == 201
        assert post["req"]["param"]["enc_host_uin"] == "EU"


class TestLikeOps:
    def test_like_songs_posts_add(self, lib):
        assert library.like_songs([1, 2], cookie="ck") is True
        posts = [b for op, b in lib if op == "POST"]
        add = [b for b in posts if b["req"]["method"] == "AddSonglist"][0]
        assert add["req"]["param"]["dirId"] == 201
        assert add["req"]["param"]["tid"] == 0
        assert add["req"]["param"]["bFmtUtf8"] is True
        assert add["req"]["param"]["v_songInfo"] == [
            {"songId": 1, "songType": 0},
            {"songId": 2, "songType": 0},
        ]

    def test_unlike_posts_del(self, lib):
        assert library.unlike_songs([5], cookie="ck") is True
        posts = [b for op, b in lib if op == "POST"]
        assert posts[-1]["req"]["method"] == "DelSonglist"
        assert posts[-1]["req"]["param"]["v_songInfo"] == [{"songId": 5, "songType": 0}]

    def test_like_fails_on_nonzero_retcode(self, lib, monkeypatch):
        monkeypatch.setattr(
            library,
            "_post_musicu",
            lambda body, cookie=None, timeout=20: {
                "req": {"code": 0, "data": {"retCode": 21001}}
            },
        )
        assert library.like_songs([9], cookie="ck") is False

    def test_like_fails_on_module_error(self, lib, monkeypatch):
        monkeypatch.setattr(
            library,
            "_post_musicu",
            lambda body, cookie=None, timeout=20: {"req": {"code": 80092}},
        )
        assert library.like_songs([9], cookie="ck") is False

    def test_empty_ids_are_noop(self, lib):
        assert library.like_songs([], cookie="ck") is True
        assert library.unlike_songs([], cookie="ck") is True
        assert lib == []


class TestHttpGetJson:
    @staticmethod
    def _serve(monkeypatch, text):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                return text.encode("utf-8")

        class FakeOpener:
            def open(self, request, timeout=20):
                return FakeResponse()

        monkeypatch.setattr(library.api, "_direct_opener", lambda: FakeOpener())

    def test_pure_json(self, monkeypatch):
        self._serve(monkeypatch, '{"code": 0}')
        assert library._http_get_json("https://x.example") == {"code": 0}

    def test_jsonp_shell_unwrapped(self, monkeypatch):
        self._serve(monkeypatch, 'cb({"code": 0, "data": {"encrypt_uin": "E"}});')
        payload = library._http_get_json("https://x.example", cookie="ck")
        assert payload["data"]["encrypt_uin"] == "E"

    def test_non_object_payload_rejected(self, monkeypatch):
        self._serve(monkeypatch, "null")
        with pytest.raises(ValueError):
            library._http_get_json("https://x.example")


class TestPlaylistSongsPagination:
    @staticmethod
    def _raw_song(i: int) -> dict:
        return {
            "mid": f"M{i}",
            "id": i,
            "name": f"歌{i}",
            "interval": 10,
            "singer": [{"name": "甲"}],
            "album": {"name": "专"},
        }

    def test_full_first_page_with_dirty_item_fetches_next(self, monkeypatch):
        pages = [
            {
                "code": 0,
                "data": {
                    "total": 102,
                    "songlist": [self._raw_song(i) for i in range(99)]
                    + [{"name": "无mid脏数据"}],
                },
            },
            {
                "code": 0,
                "data": {
                    "total": 102,
                    "songlist": [self._raw_song(100), self._raw_song(101)],
                },
            },
        ]
        begins: list[int] = []
        queue = list(pages)

        def fake_post(body, cookie=None, timeout=20):
            begins.append(body["req"]["param"]["song_begin"])
            return queue.pop(0)

        monkeypatch.setattr(library, "_post_musicu", fake_post)
        songs = library.get_playlist_songs(7, "ck")
        assert begins == [0, 100]
        assert len(songs) == 101
        assert songs[-1].mid == "M101"
