from __future__ import annotations

import random
from typing import Literal

from .models import Song

Mode = Literal["order", "loop", "random"]


class PlaybackQueue:
    """播放顺序状态机。_order 存 _songs 下标，_pos 指向 _order 当前位。"""

    def __init__(self, mode: Mode = "order"):
        self.mode: Mode = mode
        self._songs: list[Song] = []
        self._order: list[int] = []
        self._pos = -1

    def load(self, songs: list[Song], start: int = 0) -> None:
        self._songs = list(songs)
        self._order = list(range(len(self._songs)))
        start_idx = max(0, min(start, len(self._songs) - 1)) if self._songs else -1
        if self.mode == "random":
            self._shuffle_keeping(start_idx)
            self._pos = 0 if self._order else -1
        else:
            self._pos = start_idx

    def _shuffle_keeping(self, keep: int) -> None:
        rest = [i for i in self._order if i != keep]
        random.shuffle(rest)
        self._order = ([keep] if 0 <= keep < len(self._songs) else []) + rest

    def set_mode(self, mode: Mode) -> None:
        old = self.mode
        self.mode = mode
        if old == mode or not self._order:
            return
        cur_idx = self._order[self._pos]
        if mode == "random":
            self._shuffle_keeping(cur_idx)
            self._pos = 0
        else:
            self._order = sorted(self._order)
            self._pos = self._order.index(cur_idx)

    def current(self) -> Song | None:
        if not self._order or not (0 <= self._pos < len(self._order)):
            return None
        return self._songs[self._order[self._pos]]

    def next(self) -> Song | None:
        if not self._order:
            return None
        if self._pos + 1 < len(self._order):
            self._pos += 1
        elif self.mode == "loop":
            self._pos = 0
        else:
            return None
        return self.current()

    def prev(self) -> Song | None:
        if not self._order:
            return None
        if self._pos > 0:
            self._pos -= 1
        elif self.mode == "loop":
            self._pos = len(self._order) - 1
        else:
            return None
        return self.current()

    def snapshot(self) -> dict:
        cur = self.current()
        return {
            "mode": self.mode,
            "pos": self._pos,
            "current": cur.display_name() if cur else None,
            "songs": [self._songs[i].display_name() for i in self._order],
        }
