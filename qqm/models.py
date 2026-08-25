from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Song:
    """一首歌。mid 用于取播放链接，songid 用于收藏写操作。"""

    mid: str
    songid: int
    title: str
    artists: list[str] = field(default_factory=list)
    album: str = ""
    duration: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def artist_text(self) -> str:
        return ", ".join(a for a in self.artists if a)

    def display_name(self) -> str:
        return f"{self.title} - {self.artist_text}" if self.artist_text else self.title


@dataclass
class Playlist:
    pid: int
    name: str
    count: int
    kind: str  # "created" | "fav"
