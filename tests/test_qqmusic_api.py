import http.cookiejar
import io
import json
import urllib.error

import pytest

from conftest import FakeResponse

from qqm import qqmusic_api as api


class TestHash33:
    def test_seed_zero_single_char(self):
        assert api.hash33("x") == 120  # ord('x')=120

    def test_empty_with_gtk_seed(self):
        assert api.hash33("", 5381) == 5381

    def test_masked_31bit(self):
        assert 0 <= api.hash33("qrsig-example-value") <= 2147483647


class TestMaskCredentials:
    def test_masks_cookie_style(self):
        out = api.mask_credentials("uin=o123; qqmusic_key=SECRET; other=ok")
        assert "SECRET" not in out
        assert "other=ok" in out

    def test_masks_json_style(self):
        out = api.mask_credentials('{"musickey": "ABC", "n": 1}')
        assert "ABC" not in out
        assert '"n": 1' in out

    def test_masks_qm_keyst(self):
        out = api.mask_credentials("uin=o123; qm_keyst=REALSECRET; qqmusic_key=K2")
        assert "REALSECRET" not in out
        assert "qqmusic_key=***" in out


class TestPersistence:
    def test_save_load_clear_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api, "login_cookie_path", lambda: tmp_path / "c.json")
        api.save_login("o123", "uin=o123; qqmusic_key=k")
        uin, cookie = api.load_login()
        assert uin == "o123"
        assert "qqmusic_key=k" in cookie
        api.clear_login()
        assert api.load_login() == (None, None)

    def test_extract_uin(self):
        assert api._extract_uin("uin=o42; x=1") == "42"
        assert api._extract_uin("uin=42") == "42"
        assert api._extract_uin("") is None

    def test_corrupt_file_is_anonymous(self, tmp_path, monkeypatch):
        p = tmp_path / "c.json"
        p.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(api, "login_cookie_path", lambda: p)
        assert api.load_login() == (None, None)


class TestPostMusicu:
    def test_posts_json_and_parses(self, monkeypatch):
        sent = {}

        class Opener:
            def open(self, request, timeout=None):
                sent["url"] = request.full_url
                sent["body"] = json.loads(request.data.decode("utf-8"))
                sent["headers"] = dict(request.header_items())
                return FakeResponse(json.dumps({"code": 0}).encode())

        monkeypatch.setattr(api, "_direct_opener", lambda: Opener())
        data = api._post_musicu({"req": {"module": "m"}}, cookie="uin=o1")
        assert data == {"code": 0}
        assert sent["url"] == api._MUSICU_ENDPOINT
        assert sent["headers"]["Cookie"] == "uin=o1"
        assert sent["headers"]["Referer"] == "https://y.qq.com/"


def _jar_with(qrsig="QRSIG", pskey="PSKEY"):
    jar = http.cookiejar.CookieJar()

    def _set(name, value, domain):
        c = http.cookiejar.Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=True, domain_initial_dot=False,
            path="/", path_specified=True, secure=False,
            expires=None, discard=False, comment=None, comment_url=None, rest={},
        )
        jar.set_cookie(c)

    _set("qrsig", qrsig, "ssl.ptlogin2.qq.com")
    _set("p_skey", pskey, "graph.qq.com")
    return jar


class TestQrLogin:
    def _scripted_opener(self, jar, tmp_path, recorder):
        redirect = (
            "https://ssl.ptlogin2.graph.qq.com/check_sig?uin=10001"
            "&ptsigx=SIGX&ptredirect=100"
        )
        musicu_reply = json.dumps(
            {
                "req": {
                    "code": 0,
                    "data": {"credential": {"musicid": 10001, "musickey": "MKEY"}},
                }
            }
        )

        class ScriptedOpener:
            def open(self, request, timeout=None):
                url = request.full_url
                if "ptqrshow" in url:
                    recorder.append(("ptqrshow", url))
                    return FakeResponse(b"\xff\xd8\xff\xe0FAKEPNG")
                if "check_sig" in url:
                    # 注意：check_sig 的查询串里含 service=ptqrlogin，必须先于 ptqrlogin 判断
                    recorder.append(("check_sig", url))
                    return FakeResponse(b"ok")
                if "ptqrlogin" in url:
                    recorder.append(("ptqrlogin", url))
                    body = f"ptuiCB('0','0','{redirect}','0','登录成功！','nick')"
                    return FakeResponse(body.encode("utf-8"))
                if "oauth2.0/authorize" in url:
                    recorder.append(("authorize", url))
                    loc = "https://y.qq.com/portal/wx_redirect.html?login_type=1&code=THECODE"
                    err = urllib.error.HTTPError(url, 302, "moved", {}, io.BytesIO(b""))
                    err.headers = {"Location": loc}
                    raise err
                if "musicu.fcg" in url:
                    recorder.append(("musicu", json.loads(request.data.decode())))
                    return FakeResponse(musicu_reply.encode())
                raise AssertionError("未知端点 " + url)

        return ScriptedOpener()

    def test_full_flow(self, tmp_path, monkeypatch):
        jar = _jar_with()
        recorder: list = []
        opener = self._scripted_opener(jar, tmp_path, recorder)
        monkeypatch.setattr(api, "login_cookie_path", lambda: tmp_path / "c.json")
        monkeypatch.setattr(api, "login_qr_path", lambda: tmp_path / "qr.png")
        monkeypatch.setattr(http.cookiejar, "CookieJar", lambda: jar)
        monkeypatch.setattr(api.urllib.request, "build_opener", lambda *a, **k: opener)

        result = api.qr_login(timeout_seconds=5, poll_interval=0.05)

        assert result["uin"] == "o10001"
        assert "qqmusic_key=MKEY" in result["cookie"]
        assert (tmp_path / "qr.png").read_bytes().startswith(b"\xff\xd8\xff\xe0")
        saved = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
        assert saved["uin"] == "o10001"
        kinds = [r[0] for r in recorder]
        assert kinds[:3] == ["ptqrshow", "ptqrlogin", "check_sig"]
        musicu_body = [r for r in recorder if r[0] == "musicu"][0][1]
        assert musicu_body["req"]["param"]["code"] == "THECODE"

    def test_timeout_when_never_scanned(self, tmp_path, monkeypatch):
        jar = _jar_with(pskey="")

        class AlwaysWaiting:
            def open(self, request, timeout=None):
                if "ptqrshow" in request.full_url:
                    return FakeResponse(b"PNG")
                body = "ptuiCB('66','0','','0','二维码未失效。','')"
                return FakeResponse(body.encode("utf-8"))

        monkeypatch.setattr(api, "login_cookie_path", lambda: tmp_path / "c.json")
        monkeypatch.setattr(api, "login_qr_path", lambda: tmp_path / "qr.png")
        monkeypatch.setattr(http.cookiejar, "CookieJar", lambda: jar)
        monkeypatch.setattr(api.urllib.request, "build_opener", lambda *a, **k: AlwaysWaiting())
        with pytest.raises(TimeoutError):
            api.qr_login(timeout_seconds=0.5, poll_interval=0.05)


SEARCH_FIXTURE = {
    "req": {
        "code": 0,
        "data": {
            "body": {
                "song": {
                    "list": [
                        {
                            "mid": "003aAYrm3GE0Ac",
                            "id": 4830342,
                            "name": "稻香",
                            "interval": 223,
                            "singer": [{"name": "周杰伦"}],
                            "album": {"name": "魔杰座"},
                        },
                        {"mid": "", "id": 2, "name": "bad"},
                    ]
                }
            }
        },
    }
}

VKEY_OK = {
    "req_1": {
        "code": 0,
        "data": {
            "sip": ["https://isure.stream.qqmusic.qq.com/"],
            "midurlinfo": [{"purl": "M800xx.mp3?vkey=K"}],
        },
    }
}

VKEY_EMPTY = {"req_1": {"code": 0, "data": {"sip": [], "midurlinfo": [{"purl": ""}]}}}


class TestSearch:
    def test_search_parses_songs(self, monkeypatch):
        captured = {}

        def fake_post(body, cookie=None, timeout=20):
            captured["body"] = body
            return SEARCH_FIXTURE

        monkeypatch.setattr(api, "_post_musicu", fake_post)
        songs = api.search_songs("稻香 周杰伦", limit=10)
        assert len(songs) == 1  # 空 mid 被过滤
        s = songs[0]
        assert (s.mid, s.songid, s.title) == ("003aAYrm3GE0Ac", 4830342, "稻香")
        assert s.artists == ["周杰伦"]
        assert s.duration == 223
        req = captured["body"]["req"]
        assert req["module"] == "music.search.SearchCgiService"
        assert req["param"]["query"] == "稻香 周杰伦"

    def test_search_no_result_raises(self, monkeypatch):
        empty = {"req": {"code": 0, "data": {"body": {"song": {"list": []}}}}}
        monkeypatch.setattr(api, "_post_musicu", lambda *a, **k: empty)
        with pytest.raises(RuntimeError, match="没有搜到"):
            api.search_songs("不存在xyz")

    def test_malformed_body_null_is_no_result(self, monkeypatch):
        monkeypatch.setattr(
            api,
            "_post_musicu",
            lambda *a, **k: {"req": {"code": 0, "data": {"body": None}}},
        )
        with pytest.raises(RuntimeError, match="没有搜到"):
            api.search_songs("不存在xyz")


class TestAudioUrl:
    def test_logged_in_builds_request_and_returns_url(self, monkeypatch):
        captured = {}

        def fake_post(body, cookie=None, timeout=20):
            captured["body"] = body
            captured["cookie"] = cookie
            captured["calls"] = captured.get("calls", 0) + 1
            return VKEY_OK

        monkeypatch.setattr(api, "_post_musicu", fake_post)
        monkeypatch.setattr(api, "load_login", lambda: ("o123", "uin=o123; k=1"))
        url = api.get_audio_url("MIDA", quality="320")
        assert url == "https://isure.stream.qqmusic.qq.com/M800xx.mp3?vkey=K"
        assert captured["calls"] == 1  # 单次请求，禁止重试放大
        param = captured["body"]["req_1"]["param"]
        assert param["filename"] == ["M800MIDAMIDA.mp3"]
        assert param["uin"] == "o123"
        assert captured["cookie"] == "uin=o123; k=1"

    def test_anonymous_vip_raises_login_required(self, monkeypatch):
        monkeypatch.setattr(api, "_post_musicu", lambda *a, **k: VKEY_EMPTY)
        monkeypatch.setattr(api, "load_login", lambda: (None, None))
        with pytest.raises(api.QqmusicLoginRequired):
            api.get_audio_url("MIDA")

    def test_empty_midurlinfo_raises_login_required(self, monkeypatch):
        body = {
            "req_1": {"code": 0, "data": {"sip": ["https://x/"], "midurlinfo": []}}
        }
        monkeypatch.setattr(api, "_post_musicu", lambda *a, **k: body)
        monkeypatch.setattr(api, "load_login", lambda: ("o1", "c"))
        with pytest.raises(api.QqmusicLoginRequired):
            api.get_audio_url("MIDA")

    def test_quality_prefixes(self, monkeypatch):
        seen = []

        def fake_post(body, cookie=None, timeout=20):
            seen.append(body["req_1"]["param"]["filename"][0])
            return VKEY_OK

        monkeypatch.setattr(api, "_post_musicu", fake_post)
        monkeypatch.setattr(api, "load_login", lambda: ("o1", "c"))
        api.get_audio_url("M", quality="128")
        api.get_audio_url("M", quality="m4a")
        api.get_audio_url("M", quality="320")
        assert seen == ["M500MM.mp3", "C400MM.m4a", "M800MM.mp3"]
