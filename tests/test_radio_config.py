import pytest

from qqm import radio_config as rc


SAMPLE = """SiiNUnit
{
stream_data[0]: "http://a.example/x.mp3|Station A|Pop|English|128|0"
stream_data[1]: "http://b.example/y.mp3|Station B|Rock|German|192|0"
}
"""

# 游戏实际生成的格式（2026-08-25 实机采样）：内层 live_stream_def 单元 + 计数行
GAME_SAMPLE = (
    "SiiNunit\n"
    "{\n"
    "live_stream_def : _nameless.202.f734.fa70 {\n"
    " stream_data: 2\n"
    ' stream_data[0]: "http://a.example/x.mp3|Station A|Pop|English|128|0"\n'
    ' stream_data[1]: "http://b.example/y.mp3|Station B|Rock|German|192|0"\n'
    "}\n"
    "\n"
    "}\n"
)


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


def test_game_format_entry_inside_unit_and_count_bumped(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(GAME_SAMPLE, encoding="utf-8")
    rc.install(p, [("我喜欢", "http://127.0.0.1:23456/stream.mp3?ctx=liked")])
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert " stream_data: 3" in lines  # 计数 2 -> 3，保留缩进
    idx_count = lines.index(" stream_data: 3")
    idx_new = next(i for i, ln in enumerate(lines) if "|QQM|" in ln)
    closes = [i for i, ln in enumerate(lines) if ln == "}"]
    idx_inner_close = closes[-2]
    # 新条目必须在内层单元块内部（计数行之后、内层闭括号之前），且带缩进
    assert idx_count < idx_new < idx_inner_close
    assert lines[idx_new].startswith(' stream_data[2]: "http://127.0.0.1:23456/stream.mp3?ctx=liked|我喜欢|QQM|')
    # 结构完整：内层 } 之后只有空行和外层 }
    assert lines[idx_inner_close + 1 :] == ["", "}"]


def test_game_format_idempotent(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(GAME_SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")])
    rc.install(p, [("S1", "http://x/1"), ("S2", "http://x/2")])
    text = p.read_text(encoding="utf-8")
    assert text.count("|QQM|") == 2
    assert " stream_data: 4" in text  # 2 原生 + 2 QQM
    # 所有 QQM 条目都在内层块内
    lines = text.splitlines()
    inner_close = max(i for i, ln in enumerate(lines) if ln == "}")
    qqm_idx = [i for i, ln in enumerate(lines) if "|QQM|" in ln]
    assert all(i < inner_close for i in qqm_idx)


def test_game_format_remove_recomputes_count(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(GAME_SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")])
    removed = rc.remove(p)
    assert removed == 1
    text = p.read_text(encoding="utf-8")
    assert "|QQM|" not in text
    assert " stream_data: 2" in text  # 计数回落
    assert "Station A" in text
