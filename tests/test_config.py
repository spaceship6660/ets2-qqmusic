import json

from qqm import config


def test_paths_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_DATA_DIR", str(tmp_path))
    cfg = config.Config.load()
    assert cfg.data_dir == tmp_path
    assert cfg.cookie_path == tmp_path / "qqmusic_cookie.json"
    assert cfg.qr_path == tmp_path / "qqmusic_qr.png"


def test_sii_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_SII_PATH", str(tmp_path / "live_streams.sii"))
    cfg = config.Config.load()
    assert cfg.sii_path == tmp_path / "live_streams.sii"


def test_default_sii_path_points_to_documents(monkeypatch):
    monkeypatch.delenv("QQM_SII_PATH", raising=False)
    cfg = config.Config.load()
    assert cfg.sii_path.name == "live_streams.sii"


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_DATA_DIR", str(tmp_path))
    cfg = config.Config.load()
    assert cfg.stream_port == 23456
    assert cfg.quality == "320"


def test_prefs_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_DATA_DIR", str(tmp_path))
    cfg = config.Config.load()
    cfg.save_prefs({"last_playlist": "123"})
    raw = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert raw["last_playlist"] == "123"
    assert config.Config.load().load_prefs()["last_playlist"] == "123"


def test_documents_dir_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv("QQM_DOCUMENTS_DIR", raising=False)
    d = config.documents_dir()
    assert d  # Windows 上应解析出真实文档目录
