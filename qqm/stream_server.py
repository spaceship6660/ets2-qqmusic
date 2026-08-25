"""本地 mp3 流：ffmpeg 子进程转码 -> 环形缓冲 -> ThreadingHTTPServer 分发。

游戏把 http://127.0.0.1:<port>/stream.mp3 当网络电台；切台(ctx)即换播放队列。
电台模式没有暂停语义；切歌 = 换 ffmpeg 输入源。
"""

from __future__ import annotations

import collections
import json
import logging
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .models import Song
from .queue_logic import PlaybackQueue

logger = logging.getLogger(__name__)


class RingBuffer:
    """线程安全字节环：满时丢最旧；读阻塞等待数据；close() 唤醒所有读者。"""

    def __init__(self, capacity: int = 4 * 1024 * 1024):
        self.capacity = capacity
        self._buf: collections.deque[bytes] = collections.deque()
        self._size = 0
        self._cond = threading.Condition()
        self._closed = False

    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._cond:
            self._buf.append(bytes(data))
            self._size += len(data)
            while self._size > self.capacity and len(self._buf) > 1:
                dropped = self._buf.popleft()
                self._size -= len(dropped)
            self._cond.notify_all()

    def read(self, n: int = -1, timeout: float = 1.0) -> bytes:
        """有数据立即返回（最多 n 字节）；无数据等 timeout；closed 且空 -> b''。"""
        import time as _time

        deadline = _time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                if self._buf:
                    chunks: list[bytes] = []
                    remaining: float = n if n > 0 else float("inf")
                    while self._buf and remaining > 0:
                        chunk = self._buf[0]
                        if len(chunk) <= remaining:
                            chunks.append(self._buf.popleft())
                            remaining -= len(chunk)
                        else:
                            take = int(remaining)
                            chunks.append(chunk[:take])
                            self._buf[0] = chunk[take:]
                            remaining = 0
                    taken = b"".join(chunks)
                    self._size -= len(taken)
                    return taken
                if self._closed:
                    return b""
                left = deadline - _time.monotonic()
                if left <= 0:
                    return b""
                self._cond.wait(timeout=min(left, 0.25))

    def is_closed(self) -> bool:
        with self._cond:
            return self._closed

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()


def find_ffmpeg() -> str | None:
    return os.environ.get("QQM_FFMPEG_PATH") or shutil.which("ffmpeg")


def build_ffmpeg_command(spec: str, ffmpeg: str = "ffmpeg") -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        spec,
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-f",
        "mp3",
        "pipe:1",
    ]


class TrackStreamer:
    """维护一个 ffmpeg 子进程；play(spec) 切源（kill 旧的、起新的）。"""

    def __init__(self, sink: RingBuffer, spawn: Callable[[list[str]], Any] | None = None):
        self.sink = sink
        self._spawn = spawn or (
            lambda cmd: subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        )
        self._proc: Any = None
        self._lock = threading.Lock()

    def play(self, spec: str) -> None:
        with self._lock:
            self._stop_locked()
            proc = self._spawn(build_ffmpeg_command(spec))
            self._proc = proc
            threading.Thread(target=self._pump, args=(proc,), daemon=True).start()

    def _pump(self, proc: Any) -> None:
        stream = getattr(proc, "stdout", None)
        try:
            while True:
                chunk = stream.read(64 * 1024) if stream else b""
                if not chunk:
                    break
                self.sink.write(chunk)
        except Exception as exc:  # 进程被 kill 时 read 可能抛异常，属正常退出路径
            logger.debug("stream pump exit: %s", exc)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None


class RadioApp:
    """队列 + 流粘合层：ctx 切换重建队列；URL 开播瞬间才解析。

    非 inherent 线程安全：公共方法用 _lock(RLock) 串行化（HTTP handler 与 Timer 并发调用）。
    """

    def __init__(
        self,
        loader: Callable[[str], list[Song]],
        quality: str = "320",
        url_resolver: Callable[[str], str] | None = None,
    ):
        from . import qqmusic_api as api

        self.loader = loader
        self.quality = quality
        if url_resolver is not None:
            self.url_resolver = url_resolver
        else:
            self.url_resolver = lambda mid: api.get_audio_url(mid, self.quality)
        self.ring = RingBuffer()
        self.streamer: TrackStreamer | None = None
        self.queue = PlaybackQueue()
        self.context = ""
        self.on_like: Callable[[], None] = lambda: logger.info("like 未接线")
        self._advance_timer: threading.Timer | None = None
        self._gen = 0
        self._fail_streak = 0
        self._lock = threading.RLock()
        # 简化取舍：换曲期间（URL 解析最长 ~20s）status/control 会阻塞；音频流不受影响（不走本锁）。

    def attach_streamer(self, streamer: TrackStreamer) -> None:
        self.streamer = streamer

    def load_context(self, key: str) -> None:
        with self._lock:
            self._gen += 1
            self.context = key
            songs = self.loader(key)
            mode = self.queue.mode
            self.queue = PlaybackQueue(mode=mode)
            self.queue.load(songs)
            self._play_current(reschedule=True)

    def _play_current(self, reschedule: bool) -> None:
        # 调用方已持锁
        self._cancel_timer()
        song = self.queue.current()
        if song is None or self.streamer is None:
            return
        gen = self._gen
        try:
            url = self.url_resolver(song.mid)
        except Exception as exc:
            # 风控纪律：失败即顺延，不重试放大；连续 5 首失败（如登录过期）则熔断
            self._fail_streak += 1
            logger.warning(
                "解析 %s 失败（%d/5）：%s", song.display_name(), self._fail_streak, exc
            )
            if self._fail_streak >= 5:
                logger.error("连续 5 首解析失败，停止自动推进。请检查登录态后 reload。")
                return
            self.control("next")
            return
        self._fail_streak = 0
        self.streamer.play(url)
        logger.info("正在播：%s", song.display_name())
        if reschedule and song.duration > 0:
            t = threading.Timer(song.duration + 2.0, self._on_track_end, args=(gen,))
            t.daemon = True
            self._advance_timer = t
            t.start()

    def _on_track_end(self, gen: int) -> None:
        with self._lock:
            if gen != self._gen:
                return
            if self.queue.next() is None:
                logger.info("已在队列末尾；如需重播请 reload。")
                return
            self._play_current(reschedule=True)

    def _cancel_timer(self) -> None:
        if self._advance_timer is not None:
            self._advance_timer.cancel()
            self._advance_timer = None

    def control(self, cmd: str) -> dict:
        with self._lock:
            if cmd == "next":
                if self.queue.next() is None:
                    # order 队尾：不重启末曲（避免定时器无限重播），提示可 reload
                    logger.info("已在队列末尾；如需重播请 reload。")
                    return self.status()
                self._play_current(reschedule=True)
            elif cmd == "prev":
                if self.queue.prev() is None:
                    logger.info("已在队列开头。")
                    return self.status()
                self._play_current(reschedule=True)
            elif cmd == "reload":
                self.load_context(self.context)
            elif cmd == "like":
                self.on_like()
            return self.status()

    def shutdown(self) -> None:
        with self._lock:
            self._gen += 1
            self._cancel_timer()
            if self.streamer is not None:
                self.streamer.stop()
            self.ring.close()

    def status(self) -> dict:
        with self._lock:
            snap = self.queue.snapshot()
            return {"context": self.context, **snap}


def make_server(host: str, port: int, app: RadioApp) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/stream.mp3"):
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    # 客户端先于首包连接时保持连接等待（电台语义），关闭时才断开
                    while not app.ring.is_closed():
                        chunk = app.ring.read(32 * 1024, timeout=1.0)
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except OSError:
                    pass
            elif self.path.startswith("/status.json"):
                body = json.dumps(app.status(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path.startswith("/control"):
                qs = parse_qs(urlparse(self.path).query)
                cmd = (qs.get("cmd") or [""])[0]
                result = app.control(cmd) if cmd else {"error": "no cmd"}
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            logger.debug(fmt, *args)

    return ThreadingHTTPServer((host, port), Handler)
