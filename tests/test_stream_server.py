import io
import threading
import urllib.request

from qqm import stream_server as ss


class TestRingBuffer:
    def test_write_read_roundtrip(self):
        rb = ss.RingBuffer(capacity=64)
        rb.write(b"hello")
        assert rb.read(5) == b"hello"

    def test_drops_oldest_when_full(self):
        rb = ss.RingBuffer(capacity=8)
        rb.write(b"12345678")
        rb.write(b"AB")
        data = rb.read(-1)
        assert data.endswith(b"AB")
        assert len(data) <= 8

    def test_reader_unblocks_on_close(self):
        rb = ss.RingBuffer(capacity=16)
        got = []

        def reader():
            got.append(rb.read(-1, timeout=0.5))

        t = threading.Thread(target=reader)
        t.start()
        rb.close()
        t.join(timeout=3)
        assert got == [b""]

    def test_no_data_timeout_then_data(self):
        rb = ss.RingBuffer(capacity=16)
        assert rb.read(4, timeout=0.05) == b""
        rb.write(b"abcd")
        assert rb.read(4, timeout=0.5) == b"abcd"


class TestFfmpegCommand:
    def test_builds_expected_args(self):
        cmd = ss.build_ffmpeg_command("http://example.com/song.mp3", ffmpeg="ffmpeg")
        i = cmd.index("-i")
        assert cmd[0] == "ffmpeg"
        assert cmd[i + 1] == "http://example.com/song.mp3"
        assert cmd[-1] == "pipe:1"
        assert "mp3" in cmd


class _FakeProc:
    def __init__(self, payload: bytes):
        self.stdout = io.BytesIO(payload)
        self.killed = False

    def kill(self):
        self.killed = True


def _fake_songs(key: str):
    from qqm.models import Song

    assert key == "ctx"
    return [
        Song(mid="M1", songid=1, title="T1", duration=30),
        Song(mid="M2", songid=2, title="T2", duration=30),
    ]


class TestStreamerAndServer:
    def _make_app(self, payload=b"FAKEDATA" * 256):
        procs: list[_FakeProc] = []
        lock = threading.Lock()

        def fake_spawn(cmd):
            p = _FakeProc(payload)
            with lock:
                procs.append(p)
            return p

        app = ss.RadioApp(
            loader=_fake_songs,
            url_resolver=lambda mid: f"http://cdn/{mid}.mp3",  # 离线：不打真网络
        )
        app.attach_streamer(ss.TrackStreamer(app.ring, spawn=fake_spawn))
        return app, procs

    def test_switch_feeds_ring_and_server_streams_headers(self):
        app, _ = self._make_app()
        app.load_context("ctx")
        server = ss.make_server("127.0.0.1", 0, app)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/stream.mp3", timeout=5
            ) as resp:
                assert resp.headers["Content-Type"] == "audio/mpeg"
                head = resp.read(64)
            assert head.startswith(b"FAKEDATA")
        finally:
            server.shutdown()

    def test_status_and_control_next(self):
        app, _ = self._make_app()
        app.load_context("ctx")
        st = app.status()
        assert st["context"] == "ctx"
        assert "T1" in st["current"]
        app.control("next")
        assert "T2" in app.status()["current"]

    def test_url_resolved_per_track(self):
        resolved = []

        def resolver(mid: str) -> str:
            resolved.append(mid)
            return f"http://cdn/{mid}.mp3"

        from qqm.models import Song

        app = ss.RadioApp(
            loader=lambda k: [Song(mid="M1", songid=1, title="T1", duration=30)],
            url_resolver=resolver,
        )
        app.attach_streamer(ss.TrackStreamer(app.ring, spawn=lambda cmd: _FakeProc(b"x")))
        app.load_context("ctx")
        assert resolved == ["M1"]
