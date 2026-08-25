"""全局热键（可选）：需要 pip install keyboard。

Ctrl+Alt+Right 下一首 / Ctrl+Alt+Left 上一首 / Ctrl+Alt+Down 收藏当前曲。
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

_COMBOS = {
    "next": "ctrl+alt+right",
    "prev": "ctrl+alt+left",
    "like": "ctrl+alt+down",
}


def register(backend, actions: dict[str, Callable], combos: dict[str, str] | None = None) -> bool:
    """backend 是 keyboard 模块或兼容对象；传 None 时尝试 import。"""
    if backend is None:
        try:
            import keyboard as backend  # noqa: PLC0415
        except Exception:
            logger.warning("未安装 keyboard 库，热键不可用（pip install keyboard）")
            return False
    use = combos if combos is not None else _COMBOS
    for action, combo in use.items():
        fn = actions.get(action)
        if fn is not None:
            backend.add_hotkey(combo, fn)
    return True
