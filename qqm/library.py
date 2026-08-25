"""歌单/我喜欢/收藏：列表与读写均走 musicu.fcg（2026-08-25 起旧 fcg 读端点已下线）。

写操作 param 以 L-1124/QQMusicApi modules/songlist.py 的
_build_songlist_oper_param 为准。
2026-08-25 核对（上游源码）：写参数字段为 dirId（camelCase）+ tid(0) +
bFmtUtf8(True)；歌曲列表键为 v_songInfo，元素为对象
{"songId": .., "songType": ..}（非 song_info/[songid, songtype] 数组）。
成功判定与上游 add_songs/del_songs 同语义：模块 code==0 且内层
data.retCode==0；code 80092（歌曲已在/不在歌单）按 False 返回。
若上游变更以源码为准并更新此处注释。
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from . import qqmusic_api as api
from .models import Playlist, Song
from .qqmusic_api import _post_musicu, _song_from_raw

logger = logging.getLogger(__name__)

_LIKED_DIRID = 201


def _http_get_json(url: str, cookie: str | None = None, timeout: int = 20) -> dict[str, Any]:
    headers = dict(api._BASE_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers, method="GET")
    with api._direct_opener().open(request, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace").strip()
    # 兼容 JSONP 壳
    if text and not text.startswith("{"):
        start, end = text.find("("), text.rfind(")")
        if start != -1 and end > start:
            text = text[start + 1 : end]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"接口响应不是 JSON 对象：{text[:80]}")
    return data


def get_encrypt_uin(uin: str, cookie: str) -> str:
    """拿加密 uin。旧 fcg 端点已下线（2026-08-25 实测非 JSON 响应）；
    实测我喜欢读取(dirid=201)不依赖该值，失败时返回空串即可。"""
    try:
        data = _http_get_json(
            "https://c.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg?"
            + urllib.parse.urlencode({"HostUin": uin, "format": "json", "g_tk": 5381}),
            cookie=cookie,
        )
        d = data.get("data") or {}
        return str(d.get("encrypt_uin") or d.get("encryptUin") or "")
    except Exception as exc:
        logger.warning("获取加密 uin 失败（不影响「我喜欢」读取）：%s", exc)
        return ""


def list_playlists(uin: str, cookie: str, include_fav: bool = True) -> list[Playlist]:
    """列出歌单：走 PlaylistBaseRead/GetPlaylistByUin。

    「我喜欢」(dirId==201) 包含在返回中，kind 标记为 "liked"。
    include_fav 参数保留兼容签名；收藏的外部歌单需要加密 uin，
    当前登录流拿不到（旧端点已下线），故不再返回——如后续登录响应
    带出 encrypt_uin 可在此扩展 PlaylistFavRead/CgiGetPlaylistFavInfo。
    """
    data = _post_musicu(
        {
            "comm": {"g_tk": 5381, "uin": str(uin), "format": "json"},
            "req": {
                "module": "music.musicasset.PlaylistBaseRead",
                "method": "GetPlaylistByUin",
                "param": {"uin": str(uin)},
            },
        },
        cookie=cookie,
    )
    req = data.get("req") or {}
    if api._to_int(req.get("code"), -1) != 0:
        detail = api.mask_credentials(json.dumps(data, ensure_ascii=False))
        raise RuntimeError(f"拉取歌单列表失败（code={req.get('code')}）：{detail[:200]}")
    d = req.get("data") or {}
    out: list[Playlist] = []
    for item in d.get("v_playlist") or []:
        if not isinstance(item, dict):
            continue
        dir_id = api._to_int(item.get("dirId"))
        tid = api._to_int(item.get("tid"))
        if not tid:
            continue
        kind = "liked" if dir_id == 201 else "created"
        out.append(
            Playlist(
                pid=tid,
                name=str(item.get("dirName") or ""),
                count=api._to_int(item.get("songNum")),
                kind=kind,
            )
        )
    return out


def get_playlist_songs(
    pid: int,
    cookie: str,
    liked: bool = False,
    enc_uin: str = "",
    page_size: int = 100,
    max_pages: int = 5,
) -> list[Song]:
    """拉歌单全部曲目（分页）。liked=True 时忽略 pid，走 dirid=201（我喜欢）。
    enc_uin 可为空（2026-08-25 实测自账号不需要）。"""
    out: list[Song] = []
    begin = 0
    for _ in range(max_pages):
        param: dict[str, Any] = {
            "disstid": 0 if liked else int(pid),
            "tag": True,
            "song_begin": begin,
            "song_num": page_size,
            "userinfo": True,
            "orderlist": True,
        }
        if liked:
            param.update({"dirid": _LIKED_DIRID, "enc_host_uin": enc_uin})
        data = _post_musicu(
            {
                "comm": {"g_tk": 5381, "uin": "", "format": "json", "platform": "h5"},
                "req": {
                    "module": "music.srfDissInfo.DissInfo",
                    "method": "CgiGetDiss",
                    "param": param,
                },
            },
            cookie=cookie,
        )
        d = data.get("data") or {}
        raw = d.get("songlist") or []
        out.extend(
            _song_from_raw(x) for x in raw if isinstance(x, dict) and x.get("mid")
        )
        if len(raw) < page_size:
            break
        begin += len(raw)
    else:
        logger.warning(
            "歌单 %s 翻页达上限 %s 页仍未取完（每页 %s），结果可能截断。",
            pid,
            max_pages,
            page_size,
        )
    return out


def _write_playlist_songs(method: str, songids: list[int], dirid: int, cookie: str) -> bool:
    body = {
        "comm": {"g_tk": 5381, "uin": "", "format": "json"},
        "req": {
            "module": "music.musicasset.PlaylistDetailWrite",
            "method": method,
            "param": {
                "dirId": int(dirid),
                "tid": 0,
                "bFmtUtf8": True,
                "v_songInfo": [{"songId": int(s), "songType": 0} for s in songids],
            },
        },
    }
    try:
        data = _post_musicu(body, cookie=cookie)
    except Exception as exc:
        logger.warning("写歌单失败：%s", exc)
        return False
    req_data = data.get("req") or {}
    ok = api._to_int(req_data.get("code"), -1) == 0
    if ok:
        inner = req_data.get("data")
        if isinstance(inner, dict) and "retCode" in inner:
            ok = api._to_int(inner.get("retCode"), -1) == 0
    if not ok:
        detail = api.mask_credentials(json.dumps(data, ensure_ascii=False))
        logger.warning("写歌单返回异常：%s", detail[:200])
    return ok


def like_songs(songids: list[int], cookie: str, dirid: int = _LIKED_DIRID) -> bool:
    if not songids:
        return True
    return _write_playlist_songs("AddSonglist", songids, dirid, cookie)


def unlike_songs(songids: list[int], cookie: str, dirid: int = _LIKED_DIRID) -> bool:
    if not songids:
        return True
    return _write_playlist_songs("DelSonglist", songids, dirid, cookie)
