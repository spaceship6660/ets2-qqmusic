"""命令行入口。示例：

  python -m qqm.cli login
  python -m qqm.cli playlists
  python -m qqm.cli songs --liked
  python -m qqm.cli serve --liked
  python -m qqm.cli radio install --station "我的歌单:123" --station "我喜欢:liked"
  python -m qqm.cli radio remove
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import threading

from . import qqmusic_api as api
from .config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qqm")


# ---------- 工具 ----------


def _require_cookie(cfg: Config) -> str:
    _, cookie = api.load_login()
    if not cookie:
        print("尚未登录，请先执行: python -m qqm.cli login")
        raise SystemExit(2)
    return cookie


def _plain_uin() -> str:
    uin = api.load_login()[0] or ""
    return uin.lstrip("o")


# ---------- 登录/查询命令 ----------


def cmd_login(args, cfg: Config) -> int:
    print("生成二维码…（将弹出系统看图窗口，用 QQ / QQ音乐 App 扫码确认）")
    try:
        result = api.qr_login(qr_path=str(cfg.qr_path), timeout_seconds=300)
    except TimeoutError as exc:
        print(f"登录失败：{exc}")
        return 1
    print(f"登录成功：{result['uin']}（凭证已存 {cfg.cookie_path}）")
    return 0


def cmd_logout(args, cfg: Config) -> int:
    api.clear_login()
    print("已清除本地登录态。")
    return 0


def cmd_status(args, cfg: Config) -> int:
    uin, _ = api.load_login()
    print(json.dumps({
        "logged_in": bool(uin),
        "uin": uin,
        "sii_path": str(cfg.sii_path),
        "ffmpeg": os.environ.get("QQM_FFMPEG_PATH") or shutil.which("ffmpeg"),
    }, ensure_ascii=False))
    return 0


def cmd_search(args, cfg: Config) -> int:
    for i, s in enumerate(api.search_songs(args.keyword)):
        print(f"{i}: [{s.mid}] {s.display_name()} ({s.duration}s)")
    return 0


def cmd_playlists(args, cfg: Config) -> int:
    from . import library

    cookie = _require_cookie(cfg)
    for p in library.list_playlists(_plain_uin(), cookie):
        print(f"{p.kind:>7}  {p.pid:>12}  {p.count:>4}首  {p.name}")
    return 0


def cmd_songs(args, cfg: Config) -> int:
    from . import library

    cookie = _require_cookie(cfg)
    if args.liked:
        enc = library.get_encrypt_uin(_plain_uin(), cookie)
        songs = library.get_playlist_songs(0, cookie, liked=True, enc_uin=enc)
    elif args.playlist:
        songs = library.get_playlist_songs(int(args.playlist), cookie)
    else:
        print("需要 --playlist ID 或 --liked")
        return 2
    for i, s in enumerate(songs):
        print(f"{i}: [{s.mid}] {s.display_name()} ({s.duration}s)")
    return 0


def cmd_like(args, cfg: Config) -> int:
    from . import library

    cookie = _require_cookie(cfg)
    ok = library.like_songs([int(args.songid)], cookie)
    print("已收藏到「我喜欢」" if ok else "收藏失败")
    return 0 if ok else 1


# ---------- serve ----------


def _build_loader(cookie: str):
    from . import library

    def load(key: str):
        if key == "liked":
            enc = library.get_encrypt_uin(_plain_uin(), cookie)
            songs = library.get_playlist_songs(0, cookie, liked=True, enc_uin=enc)
        else:
            songs = library.get_playlist_songs(int(key), cookie)
        if not songs:
            raise SystemExit(f"歌单 {key} 为空或拉取失败")
        log.info("载入 %d 首：%s", len(songs), key)
        return songs

    return load


def cmd_serve(args, cfg: Config) -> int:
    from .stream_server import RadioApp, TrackStreamer, find_ffmpeg, make_server

    if not find_ffmpeg():
        print("找不到 ffmpeg：请安装或设置环境变量 QQM_FFMPEG_PATH 指向 ffmpeg.exe")
        return 1
    cookie = _require_cookie(cfg)
    ctx_key = "liked" if args.liked else str(args.playlist)

    app = RadioApp(loader=_build_loader(cookie), quality=cfg.quality)
    app.attach_streamer(TrackStreamer(app.ring))

    def do_like():
        with app._lock:
            cur = app.queue.current()
        if cur is None:
            return
        from . import library

        ok = library.like_songs([cur.songid], cookie)
        log.info("收藏 %s：%s", cur.display_name(), "成功" if ok else "失败")

    app.on_like = do_like

    server = make_server("127.0.0.1", args.port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        from . import hotkeys
        hotkeys.register(None, {
            "next": lambda: app.control("next"),
            "prev": lambda: app.control("prev"),
            "like": do_like,
        })
    except Exception as exc:  # 热键失败不阻塞
        log.warning("热键注册失败：%s", exc)

    print(f"流地址: http://127.0.0.1:{args.port}/stream.mp3?ctx={ctx_key}")
    print("状态:   http://127.0.0.1:{0}/status.json".format(args.port))
    print("控制:   POST http://127.0.0.1:{0}/control?cmd=next|prev|reload|like".format(args.port))
    print("热键:   Ctrl+Alt+Right 下一首 / Ctrl+Alt+Left 上一首 / Ctrl+Alt+Down 收藏（需 keyboard 库）")
    print("Ctrl+C 退出。")
    stop = threading.Event()
    try:
        app.load_context(ctx_key)
        while not stop.is_set():
            stop.wait(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
        server.shutdown()
    return 0


# ---------- radio ----------


def _parse_station(spec: str) -> tuple[str, str]:
    """'我的歌单:123' -> ('我的歌单', 'http://.../stream.mp3?ctx=123')"""
    name, _, key = spec.rpartition(":")
    if not name or not key:
        raise SystemExit(f"--station 格式应为 名称:<playlist_id|liked>，收到 {spec!r}")
    # 简化：radio 条目固定默认端口；如改端口需同步此处
    url = f"http://127.0.0.1:23456/stream.mp3?ctx={key}"
    return name, url


def cmd_radio_install(args, cfg: Config) -> int:
    from . import radio_config

    stations = [_parse_station(s) for s in args.station]
    count = radio_config.install(cfg.sii_path, stations, force=args.force)
    print(f"已写入 {count} 个电台条目到 {cfg.sii_path}")
    print("注意：游戏只在启动时读取该文件——若游戏正在运行，退出后重开生效。")
    return 0


def cmd_radio_remove(args, cfg: Config) -> int:
    from . import radio_config

    removed = radio_config.remove(cfg.sii_path)
    print(f"已移除 {removed} 个 QQM 电台条目。")
    return 0


# ---------- argparse 装配 ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qqm", description="ETS2 QQ 音乐伴侣")
    sub = p.add_subparsers(required=True)

    sub.add_parser("login").set_defaults(fn=cmd_login)
    sub.add_parser("logout").set_defaults(fn=cmd_logout)
    sub.add_parser("status").set_defaults(fn=cmd_status)

    sp = sub.add_parser("search")
    sp.add_argument("keyword")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("playlists")
    sp.set_defaults(fn=cmd_playlists)

    sp = sub.add_parser("songs")
    sp.add_argument("--playlist", default=None)
    sp.add_argument("--liked", action="store_true")
    sp.set_defaults(fn=cmd_songs)

    sp = sub.add_parser("like")
    sp.add_argument("songid")
    sp.set_defaults(fn=cmd_like)

    sp = sub.add_parser("serve")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--playlist")
    g.add_argument("--liked", action="store_true")
    sp.add_argument("--port", type=int, default=23456)
    sp.set_defaults(fn=cmd_serve)

    rp = sub.add_parser("radio")
    rsub = rp.add_subparsers(required=True)
    ip = rsub.add_parser("install")
    ip.add_argument("--station", action="append", required=True,
                    help='格式 "名称:<playlist_id|liked>"，可多次')
    ip.add_argument("--force", action="store_true")
    ip.set_defaults(fn=cmd_radio_install)
    rm = rsub.add_parser("remove")
    rm.set_defaults(fn=cmd_radio_remove)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    cfg = Config.load()
    try:
        return ns.fn(ns, cfg)
    except KeyboardInterrupt:
        print("已取消。")
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        log.debug("命令执行异常", exc_info=True)
        print(f"出错：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
