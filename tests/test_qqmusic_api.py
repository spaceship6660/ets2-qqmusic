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
