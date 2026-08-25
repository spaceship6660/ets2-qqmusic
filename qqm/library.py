"""歌单/我喜欢/收藏：读接口走经典 fcgi，写接口走 musicu.fcg asset 模块。

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
from .qqmusic_api import _post_musicu

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
        start, end = text.find("("), text.rindex(")")
        text = text[start + 1 : end] if start != -1 else text
    return json.loads(text)


def get_encrypt_uin(uin: str, cookie: str) -> str:
    """拿加密 uin（我喜欢等私有歌单接口需要）。"""
    data = _http_get_json(
        "https://c.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg?"
        + urllib.parse.urlencode({"HostUin": uin, "format": "json", "g_tk": 5381}),
        cookie=cookie,
    )
    d = data.get("data") or {}
    return str(d.get("encrypt_uin") or d.get("encryptUin") or "")


def list_playlists(uin: str, cookie: str, include_fav: bool = True) -> list[Playlist]:
    out: list[Playlist] = []
    created = _http_get_json(
        "https://c.y.qq.com/rsc/fcgi-bin/fcg_user_created_diss?"
        + urllib.parse.urlencode(
            {"hostUin": uin, "size": 100, "page": 1, "g_tk": 5381, "format": "json"}
        ),
        cookie=cookie,
    )
    favs = (
        _http_get_json(
            "https://c.y.qq.com/rsc/fcgi-bin/fcg_get_profile_order_asset.fcg?"
            + urllib.parse.urlencode(
                {"ct": 20, "hostUin": uin, "size": 100, "page": 1,
                 "g_tk": 5381, "format": "json"}
            ),
            cookie=cookie,
        )
        if include_fav
        else {"data": {"disslist": []}}
    )

    def _parse(payload: dict[str, Any], kind: str) -> list[Playlist]:
        items = ((payload.get("data") or {}).get("disslist")) or []
        result = []
        for item in items:
            pid = api._to_int(item.get("dissid"))
            if pid:
                result.append(
                    Playlist(
                        pid=pid,
                        name=str(item.get("dissname") or ""),
                        count=api._to_int(item.get("song_count")),
                        kind=kind,
                    )
                )
        return result

    out.extend(_parse(created, "created"))
    out.extend(_parse(favs, "fav"))
    return out


def _song_from_raw(raw: dict[str, Any]) -> Song:
    return Song(
        mid=str(raw.get("mid") or ""),
        songid=api._to_int(raw.get("id")),
        title=str(raw.get("name") or ""),
        artists=[str(s.get("name") or "") for s in (raw.get("singer") or [])],
        album=str(((raw.get("album") or {}).get("name")) or ""),
        duration=api._to_int(raw.get("interval")),
        raw=raw,
    )


def get_playlist_songs(
    pid: int,
    cookie: str,
    liked: bool = False,
    enc_uin: str = "",
    page_size: int = 100,
    max_pages: int = 5,
) -> list[Song]:
    """拉歌单全部曲目（分页）。liked=True 时忽略 pid，走 dirid=201（我喜欢）。"""
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
        songs = [_song_from_raw(x) for x in (d.get("songlist") or []) if x.get("mid")]
        out.extend(songs)
        if len(songs) < page_size:
            break
        begin += len(songs)
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
    return _write_playlist_songs("AddSonglist", songids, dirid, cookie)


def unlike_songs(songids: list[int], cookie: str, dirid: int = _LIKED_DIRID) -> bool:
    return _write_playlist_songs("DelSonglist", songids, dirid, cookie)
