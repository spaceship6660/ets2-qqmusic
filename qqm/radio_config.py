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
_COUNT_RE = re.compile(r"^(\s*)stream_data\s*:\s*\d+\s*$")


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
    """stations: [(显示名, 流URL)]。返回写入条数。游戏运行时拒绝除非 force。

    支持两种文件布局（2026-08-25 实机采样）：
    - 游戏生成格式：内层 `live_stream_def : ... {` 单元块 + ` stream_data: N`
      计数行；新条目必须插到内层块内、并把计数改为 N+len(stations)，
      否则游戏解析失败（列表全空）。
    - 简化格式（仅 SiiNunit + 条目 + }）：直接在收尾括号前追加。
    """
    if not force and game_running():
        raise RuntimeError("检测到 ETS2 正在运行，请退出游戏后再执行（或加 --force）。")
    text = _ensure_skeleton(path)
    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")

    lines = text.splitlines()
    kept = [ln for ln in lines if f"|{MARKER}|" not in ln]

    # 定位收尾括号：外层 = 最后一个非空行；内层 = 外层之前最后一个非空行（若为 '}'）
    nonblank = [i for i, ln in enumerate(kept) if ln.strip()]
    if not nonblank:
        kept = ["SiiNunit", "{", "}"]
        nonblank = [0, 1, 2]
    outer_close = nonblank[-1]
    inner_close = None
    if len(nonblank) >= 2:
        prev = nonblank[-2]
        if kept[prev].strip() == "}":
            inner_close = prev

    # 计数行（游戏格式）：移除旧 QQM 后重算总数并原位改写
    count_idx = next((i for i, ln in enumerate(kept) if _COUNT_RE.match(ln)), None)
    if count_idx is not None:
        indent = kept[count_idx][: len(kept[count_idx]) - len(kept[count_idx].lstrip())]
        total_entries = sum(1 for ln in kept if _ENTRY_RE.match(ln))
        kept[count_idx] = f"{indent}stream_data: {total_entries + len(stations)}"

    # 插入点：内层闭括号之前（游戏格式）；否则外层闭括号之前（简化格式）
    insert_at = inner_close if inner_close is not None else outer_close

    # 延续现有条目缩进与编号
    entry_indent = ""
    for ln in kept:
        m = _ENTRY_RE.match(ln)
        if m:
            entry_indent = ln[: len(ln) - len(ln.lstrip())]
            break
    body = kept[:insert_at]
    next_idx = max((_indices("\n".join(body))), default=-1) + 1
    new_lines = [
        f'{entry_indent}stream_data[{next_idx + i}]: "{url}|{name}|{MARKER}|Chinese|192|0"'
        for i, (name, url) in enumerate(stations)
    ]
    out_lines = body + new_lines + kept[insert_at:]
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    logger.info("已写入 %d 个 QQM 电台到 %s", len(new_lines), path)
    return len(new_lines)


def remove(path: Path) -> int:
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if f"|{MARKER}|" not in ln]
    removed = len(lines) - len(kept)
    if removed:
        # 游戏格式：同步回落计数行
        count_idx = next((i for i, ln in enumerate(kept) if _COUNT_RE.match(ln)), None)
        if count_idx is not None:
            indent = kept[count_idx][: len(kept[count_idx]) - len(kept[count_idx].lstrip())]
            total_entries = sum(1 for ln in kept if _ENTRY_RE.match(ln))
            kept[count_idx] = f"{indent}stream_data: {total_entries}"
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return removed
