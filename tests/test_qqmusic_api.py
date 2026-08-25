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
