from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_CSIDL_PERSONAL = 5  # 文档目录


def documents_dir() -> str:
    """解析真实「文档」目录（兼容 OneDrive 重定向）。"""
    env = os.environ.get("QQM_DOCUMENTS_DIR")
    if env:
        return env
    buf = ctypes.create_unicode_buffer(512)
    hr = ctypes.windll.shell32.SHGetFolderPathW(None, _CSIDL_PERSONAL, None, 0, buf)
    if hr != 0:
        return str(Path.home() / "Documents")
    return buf.value


@dataclass
class Config:
    data_dir: Path
    stream_port: int = 23456
    quality: str = "320"
    sii_path: Path = field(default_factory=lambda: Path())

    @classmethod
    def load(cls) -> "Config":
        data_dir = Path(os.environ.get("QQM_DATA_DIR", str(Path.cwd() / "data")))
        sii_env = os.environ.get("QQM_SII_PATH")
        sii = (
            Path(sii_env)
            if sii_env
            else Path(documents_dir()) / "Euro Truck Simulator 2" / "live_streams.sii"
        )
        return cls(
            data_dir=data_dir,
            stream_port=int(os.environ.get("QQM_STREAM_PORT", "23456")),
            quality=os.environ.get("QQM_QUALITY", "320"),
            sii_path=sii,
        )

    @property
    def cookie_path(self) -> Path:
        return self.data_dir / "qqmusic_cookie.json"

    @property
    def qr_path(self) -> Path:
        return self.data_dir / "qqmusic_qr.png"

    @property
    def prefs_path(self) -> Path:
        return self.data_dir / "prefs.json"

    def save_prefs(self, prefs: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.prefs_path.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_prefs(self) -> dict:
        if not self.prefs_path.exists():
            return {}
        try:
            data = json.loads(self.prefs_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
