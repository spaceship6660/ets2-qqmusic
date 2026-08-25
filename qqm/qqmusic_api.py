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


_QR_SHOW_URL = "https://ssl.ptlogin2.qq.com/ptqrshow"
_QR_LOGIN_URL = "https://ssl.ptlogin2.qq.com/ptqrlogin"
_CHECK_SIG_URL = "https://ssl.ptlogin2.graph.qq.com/check_sig"
_AUTHORIZE_URL = "https://graph.qq.com/oauth2.0/authorize"
_LOGIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_APPID = "716027609"
_DAID = "383"
_PT_3RD_AID = "100497308"
_REDIRECT_URI = "https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https://y.qq.com/"
_PTUI_CB_RE = re.compile(r"ptuiCB\((.*)\)")
_PTUI_ARGS_RE = re.compile(r"'([^']*)'")
_SIGX_RE = re.compile(r"ptsigx=([^&]+)")
_UIN_RE = re.compile(r"uin=(\d+)")
_CODE_RE = re.compile(r"(?:code=)(.+?)(?:&|$)")


def qr_login(
    qr_path: str | Path | None = None,
    timeout_seconds: float = 180.0,
    poll_interval: float = 1.5,
) -> dict[str, str]:
    """QQ 扫码登录：出二维码 -> 轮询 -> check_sig -> OAuth -> 换凭证 -> 持久化。"""
    import http.cookiejar
    import time
    import uuid
    import random

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.ProxyHandler({}),
    )
    qr_file = Path(qr_path or login_qr_path())
    qr_file.parent.mkdir(parents=True, exist_ok=True)

    # 1) 出二维码（Set-Cookie: qrsig）
    show_params = urllib.parse.urlencode(
        {
            "appid": _APPID, "e": "2", "l": "M", "s": "3", "d": "72", "v": "4",
            "t": str(random.random()), "daid": _DAID, "pt_3rd_aid": _PT_3RD_AID,
        }
    )
    req = urllib.request.Request(
        f"{_QR_SHOW_URL}?{show_params}",
        headers={"User-Agent": _LOGIN_UA, "Referer": "https://xui.ptlogin2.qq.com/"},
    )
    with opener.open(req, timeout=30) as resp:
        qr_file.write_bytes(resp.read())
    qrsig = next((c.value for c in jar if c.name == "qrsig"), None)
    if not qrsig:
        raise RuntimeError("获取 QQ 登录二维码失败（缺少 qrsig）。")
    logger.info("QQ 登录二维码已保存：%s（请用 QQ/QQ音乐 扫码）", qr_file)

    # 2) 轮询：66 已扫待确认 / 65 失效 / 68 拒绝 / 0 成功 / 其他继续等待
    token = str(hash33(qrsig))
    deadline = time.monotonic() + max(10.0, float(timeout_seconds)) \
        if timeout_seconds >= 10 else time.monotonic() + float(timeout_seconds)
    login_params = urllib.parse.urlencode(
        {
            "u1": "https://graph.qq.com/oauth2.0/login_jump",
            "ptqrtoken": token,
            "ptredirect": "0", "h": "1", "t": "1", "g": "1",
            "from_ui": "1", "ptlang": "2052",
            "action": f"0-0-{time.time() * 1000}",
            "js_ver": "20102616", "js_type": "1", "pt_uistyle": "40",
            "aid": _APPID, "daid": _DAID, "pt_3rd_aid": _PT_3RD_AID,
            "has_onekey": "1",
        }
    )
    args: list[str] = []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("QQ 扫码登录超时。")
        req = urllib.request.Request(
            f"{_QR_LOGIN_URL}?{login_params}",
            headers={
                "User-Agent": _LOGIN_UA,
                "Referer": "https://xui.ptlogin2.qq.com/",
                "Cookie": f"qrsig={qrsig}",
            },
        )
        try:
            with opener.open(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError("无效 qrsig，请重试扫码登录。") from exc
        match = _PTUI_CB_RE.search(text)
        if not match:
            raise RuntimeError("无法解析 QQ 登录状态响应。")
        args = _PTUI_ARGS_RE.findall(match.group(1))
        if not args or not args[0].isdigit():
            raise RuntimeError("无法解析 QQ 登录状态码。")
        code = int(args[0])
        if code == 0:
            break
        if code == 65:
            raise TimeoutError("QQ 登录二维码已失效，请重试。")
        if code == 68:
            raise RuntimeError("用户拒绝了 QQ 扫码登录。")
        if code not in (66, 67):
            raise RuntimeError(f"QQ 扫码登录失败（状态码 {code}）。")
        time.sleep(max(0.05, float(poll_interval)))

    redirect_url = args[2] if len(args) > 2 else ""
    sigx_match = _SIGX_RE.search(redirect_url)
    uin_match = _UIN_RE.search(redirect_url)
    if not sigx_match or not uin_match:
        raise RuntimeError("QQ 登录成功但缺少鉴权参数。")
    uin = uin_match.group(1)
    ptsigx = sigx_match.group(1)

    # 3) check_sig -> p_skey
    check_params = urllib.parse.urlencode(
        {
            "uin": uin, "pttype": "1", "service": "ptqrlogin", "nodirect": "0",
            "ptsigx": ptsigx,
            "s_url": "https://graph.qq.com/oauth2.0/login_jump",
            "ptlang": "2052", "ptredirect": "100",
            "aid": _APPID, "daid": _DAID, "j_later": "0", "low_login_hour": "0",
            "regmaster": "0", "pt_login_type": "3", "pt_aid": "0",
            "pt_aaid": "16", "pt_light": "0", "pt_3rd_aid": _PT_3RD_AID,
        }
    )
    req = urllib.request.Request(
        f"{_CHECK_SIG_URL}?{check_params}",
        headers={"User-Agent": _LOGIN_UA, "Referer": "https://xui.ptlogin2.qq.com/"},
    )
    with opener.open(req, timeout=30) as resp:
        resp.read()
    p_skey = next((c.value for c in jar if c.name == "p_skey"), None)
    if not p_skey:
        raise RuntimeError("QQ 登录获取 p_skey 失败。")

    # 4) OAuth authorize -> code（在 302 的 Location 里）
    auth_data = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": "100497308",
            "redirect_uri": _REDIRECT_URI,
            "scope": "get_user_info,get_app_friends",
            "state": "state", "switch": "", "from_ptlogin": "1", "src": "1",
            "update_auth": "1", "openapi": "1010_1030",
            "g_tk": str(hash33(p_skey, 5381)),
            "auth_time": str(int(time.time() * 1000)),
            "ui": str(uuid.uuid4()),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _AUTHORIZE_URL,
        data=auth_data,
        headers={
            "User-Agent": _LOGIN_UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with opener.open(req, timeout=30) as resp:
            resp.read()
        location = resp.geturl()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
    code_match = _CODE_RE.search(location or "")
    if not code_match:
        raise RuntimeError("QQ 登录换取授权 code 失败。")

    # 5) QQLogin -> musicid/musickey
    data = _post_musicu(
        {
            "comm": {
                "ct": 24, "cv": 4747474, "platform": "yqq.json", "chid": "0",
                "g_tk": 5381, "g_tk_new_20200303": 5381, "format": "json",
                "inCharset": "utf-8", "outCharset": "utf-8", "notice": 0,
                "need_new_code": 1, "tmeLoginType": 2,
            },
            "req": {
                "module": "QQConnectLogin.LoginServer",
                "method": "QQLogin",
                "param": {"code": code_match.group(1)},
            },
        }
    )
    req_data = data.get("req") or {}
    if int(req_data.get("code") or 0) != 0:
        detail = mask_credentials(json.dumps(data, ensure_ascii=False))
        raise RuntimeError(f"QQ 登录换取播放凭证失败（响应：{detail[:300]}）。")
    credential = req_data.get("data") or {}
    musicid = str(credential.get("musicid") or "")
    musickey = str(credential.get("musickey") or "")
    if not musicid or not musickey:
        detail = mask_credentials(json.dumps(data, ensure_ascii=False))
        raise RuntimeError(f"QQ 登录成功但未取到播放凭证（响应：{detail}）。")
    cookie = (
        f"uin=o{musicid}; qqmusic_uin=o{musicid}; "
        f"qm_keyst={musickey}; qqmusic_key={musickey}"
    )
    save_login(f"o{musicid}", cookie)
    logger.info("QQ 音乐登录态已保存：%s", login_cookie_path())
    return {"uin": f"o{musicid}", "cookie": cookie}
