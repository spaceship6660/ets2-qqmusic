"""live_streams.sii 注册/移除 QQM 电台条目。

条目格式：stream_data[N]: "URL|名称|流派|语言|码率|收藏标记"
我们的流派字段固定为 "QQM" 作为识别与移除标记。
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER = "QQM"
BACKUP_SUFFIX = ".qqm-backup.sii"
_ENTRY_RE = re.compile(r"^\s*stream_data\[(\d+)\]\s*:")


def _tasklist_output() -> bytes:
    return subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq eurotrucks2.exe"],
        capture_output=True,
    ).stdout


def game_running() -> bool:
    return b"eurotrucks2.exe" in _tasklist_output().lower()


def _ensure_skeleton(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = "SiiNUnit\n{\n}\n"
    path.write_text(skeleton, encoding="utf-8")
    return skeleton


def _indices(text: str) -> list[int]:
    out = []
    for line in text.splitlines():
        m = _ENTRY_RE.match(line)
        if m:
            out.append(int(m.group(1)))
    return out


def install(path: Path, stations: list[tuple[str, str]], force: bool = False) -> int:
    """stations: [(显示名, 流URL)]。返回写入条数。游戏运行时拒绝除非 force。"""
    if not force and game_running():
        raise RuntimeError("检测到 ETS2 正在运行，请退出游戏后再执行（或加 --force）。")
    text = _ensure_skeleton(path)
    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")

    kept_lines = [ln for ln in text.splitlines() if f"|{MARKER}|" not in ln]
    had_closing = bool(kept_lines) and kept_lines[-1].strip() == "}"
    body_lines = kept_lines[:-1] if had_closing else kept_lines

    next_idx = max(_indices("\n".join(body_lines)), default=-1) + 1
    new_lines = [
        f'stream_data[{next_idx + i}]: "{url}|{name}|{MARKER}|Chinese|192|0"'
        for i, (name, url) in enumerate(stations)
    ]
    out = "\n".join(body_lines + new_lines) + "\n}\n"
    path.write_text(out, encoding="utf-8")
    logger.info("已写入 %d 个 QQM 电台到 %s", len(new_lines), path)
    return len(new_lines)


def remove(path: Path) -> int:
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if f"|{MARKER}|" not in ln]
    removed = len(lines) - len(kept)
    if removed:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return removed
