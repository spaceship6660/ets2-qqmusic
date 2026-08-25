from qqm.models import Song
from qqm.queue_logic import PlaybackQueue


def mk(i: int) -> Song:
    return Song(mid=f"M{i}", songid=i, title=f"T{i}")


def test_load_current_next_prev():
    q = PlaybackQueue()
    q.load([mk(i) for i in range(3)], start=1)
    assert q.current().mid == "M1"
    assert q.next().mid == "M2"
    assert q.next() is None
    assert q.prev().mid == "M1"
    assert q.prev().mid == "M0"
    assert q.prev() is None


def test_loop_wraps():
    q = PlaybackQueue(mode="loop")
    q.load([mk(i) for i in range(2)], start=0)
    q.next()
    assert q.next().mid == "M0"
    assert q.prev().mid == "M1"


def test_random_shuffles_rest_keeps_current_first():
    q = PlaybackQueue()
    q.load([mk(i) for i in range(50)], start=0)
    q.set_mode("random")
    cur = q.current()
    assert cur.mid == "M0"
    order = [q.next().mid for _ in range(49)]
    assert sorted(order) == sorted(f"M{i}" for i in range(1, 50))


def test_replace_queue_keeps_mode():
    q = PlaybackQueue(mode="loop")
    q.load([mk(1)])
    q.load([mk(2), mk(3)], start=0)
    assert q.mode == "loop"
    assert q.current().mid == "M2"


def test_snapshot_shape():
    q = PlaybackQueue()
    q.load([mk(1), mk(2)], start=0)
    snap = q.snapshot()
    assert snap["mode"] == "order"
    assert snap["pos"] == 0
    assert snap["current"] == "T1"
    assert snap["songs"] == ["T1", "T2"]


def test_single_song_and_empty_edges():
    q = PlaybackQueue()
    assert q.next() is None and q.prev() is None and q.current() is None
    q.load([mk(0)])
    q.set_mode("random")
    assert q.current().mid == "M0" and q.next() is None
    q2 = PlaybackQueue(mode="loop")
    q2.load([mk(0)])
    assert q2.next().mid == "M0" and q2.prev().mid == "M0"
