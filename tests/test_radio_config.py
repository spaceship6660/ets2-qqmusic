import pytest

from qqm import radio_config as rc


SAMPLE = """SiiNUnit
{
stream_data[0]: "http://a.example/x.mp3|Station A|Pop|English|128|0"
stream_data[1]: "http://b.example/y.mp3|Station B|Rock|German|192|0"
}
"""


def test_install_appends_marked_entries(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("QQM 测试歌单", "http://127.0.0.1:23456/stream.mp3?ctx=111")])
    text = p.read_text(encoding="utf-8")
    assert "|QQM|" in text
    assert 'stream_data[2]:' in text
    assert text.rstrip().endswith("}")


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")])
    rc.install(p, [("S1", "http://x/1"), ("S2", "http://x/2")])
    text = p.read_text(encoding="utf-8")
    assert text.count("|QQM|") == 2
    assert "S1" in text and "S2" in text


def test_install_creates_backup_once(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")])
    backup = tmp_path / "live_streams.sii.qqm-backup.sii"
    first = backup.read_bytes()
    assert b"Station A" in first
    rc.install(p, [("S1", "http://x/1")])
    assert backup.read_bytes() == first


def test_install_creates_skeleton_if_missing(tmp_path):
    p = tmp_path / "live_streams.sii"
    rc.install(p, [("S1", "http://x/1")])
    text = p.read_text(encoding="utf-8")
    assert text.startswith("SiiNUnit")
    assert "|QQM|" in text


def test_remove_only_qqm_lines(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(
        SAMPLE
        + 'stream_data[2]: "http://127.0.0.1:9/stream.mp3|QQM 歌单|QQM|Chinese|192|0"\n',
        encoding="utf-8",
    )
    removed = rc.remove(p)
    assert removed == 1
    text = p.read_text(encoding="utf-8")
    assert "Station A" in text and "|QQM|" not in text


def test_game_running_detection(monkeypatch):
    monkeypatch.setattr(rc, "_tasklist_output", lambda: b"eurotrucks2.exe   1234")
    assert rc.game_running() is True
    monkeypatch.setattr(rc, "_tasklist_output", lambda: b"INFO: No tasks are running")
    assert rc.game_running() is False


def test_install_refuses_while_game_running(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "game_running", lambda: True)
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(RuntimeError, match="正在运行"):
        rc.install(p, [("S1", "http://x/1")])


def test_install_force_bypasses_game_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "game_running", lambda: True)
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")], force=True)
    assert "|QQM|" in p.read_text(encoding="utf-8")
