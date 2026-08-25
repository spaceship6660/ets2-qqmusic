import pytest

from qqm import cli


@pytest.fixture
def routed(monkeypatch):
    calls = []
    names = (
        "cmd_login", "cmd_logout", "cmd_status", "cmd_search",
        "cmd_playlists", "cmd_songs", "cmd_like",
        "cmd_serve", "cmd_radio_install", "cmd_radio_remove",
    )

    def mk(name):
        def fn(args, cfg):
            calls.append((name, args))
            return 0
        return fn

    for name in names:
        monkeypatch.setattr(cli, name, mk(name))
    return calls


def test_login(routed):
    cli.main(["login"])
    assert routed[-1][0] == "cmd_login"


def test_search(routed):
    cli.main(["search", "稻香"])
    name, args = routed[-1]
    assert name == "cmd_search" and args.keyword == "稻香"


def test_serve_playlist(routed):
    cli.main(["serve", "--playlist", "123"])
    name, args = routed[-1]
    assert name == "cmd_serve" and args.playlist == "123" and args.liked is False


def test_serve_liked(routed):
    cli.main(["serve", "--liked"])
    _, args = routed[-1]
    assert args.liked is True and args.playlist is None


def test_radio_install(routed):
    cli.main(["radio", "install", "--station", "我的歌单:123", "--station", "我喜欢:liked"])
    name, args = routed[-1]
    assert name == "cmd_radio_install"
    assert args.station == ["我的歌单:123", "我喜欢:liked"]
    assert args.force is False


def test_radio_remove(routed):
    cli.main(["radio", "remove"])
    assert routed[-1][0] == "cmd_radio_remove"


def test_songs_liked(routed):
    cli.main(["songs", "--liked"])
    _, args = routed[-1]
    assert args.liked is True
