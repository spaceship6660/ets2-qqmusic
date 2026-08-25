r"""QQ 音乐 Web 接口客户端。

移植自 Spica-Chatbot（[已移除本地私有路径]\agent_tools\
function_tools\song\qqmusic.py，2026-08 实机验证可用），上游致谢
copws/qq-music-api 与 L-1124/QQMusicApi。仅供个人学习使用。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MUSICU_ENDPOINT = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
        "Gecko/20100101 Firefox/115.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
    "Referer": "https://y.qq.com/",
}


def _direct_opener() -> urllib.request.OpenerDirector:
    # QQ 音乐是国内服务，绝不能跟随系统代理（Clash 等），显式空代理直连。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class QqmusicLoginRequired(RuntimeError):
    """需要扫码登录（未登录或凭证过期）。"""


def hash33(text: str, seed: int = 0) -> int:
    value = seed
    for ch in text:
        value += (value << 5) + ord(ch)
    return 2147483647 & value


def mask_credentials(text: str) -> str:
    for key in (
        "qqmusic_key", "musickey", "musicid", "access_token",
        "refresh_token", "refresh_key", "openid",
        "qm_keyst", "MUSIC_U", "wxunionid",
    ):
        text = re.compile(rf'"{key}"\s*:\s*"[^"]*"').sub(rf'"{key}": "***"', text)
        text = re.compile(rf"(?i){key}=[^;\"'\s]+").sub(rf"{key}=***", text)
    return text


def login_cookie_path() -> Path:
    from .config import Config

    return Config.load().cookie_path


def login_qr_path() -> Path:
    from .config import Config

    return Config.load().qr_path


def load_login() -> tuple[str | None, str | None]:
    path = login_cookie_path()
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookie = str(data.get("cookie") or "")
        uin = str(data.get("uin") or "")
        if cookie:
            return uin or _extract_uin(cookie), cookie
    except Exception as exc:
        logger.warning("QQ音乐登录态文件损坏，按匿名运行：%s (%s)", path, exc)
    return None, None


def save_login(uin: str, cookie: str) -> Path:
    path = login_cookie_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"uin": uin, "cookie": cookie}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def clear_login() -> None:
    try:
        login_cookie_path().unlink(missing_ok=True)
    except OSError:
        pass


def login_available() -> bool:
    return bool(load_login()[1])


def _extract_uin(cookie: str) -> str | None:
    match = re.search(r"(?:^|;\s*)uin=o?(\d+)", cookie or "")
    return match.group(1) if match else None


def _post_musicu(body: dict[str, Any], cookie: str | None = None, timeout: int = 20) -> dict[str, Any]:
    headers = dict(_BASE_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        _MUSICU_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with _direct_opener().open(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
