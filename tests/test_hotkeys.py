from qqm import hotkeys


class FakeKeyboard:
    def __init__(self):
        self.handlers = {}
        self.add_calls = []

    def add_hotkey(self, combo, fn):
        self.add_calls.append(combo)
        self.handlers[combo] = fn


def test_register_maps_controls():
    kb = FakeKeyboard()
    fired = []
    ok = hotkeys.register(
        kb,
        {
            "next": lambda: fired.append("next"),
            "prev": lambda: fired.append("prev"),
            "like": lambda: fired.append("like"),
        },
    )
    assert ok is True
    assert kb.add_calls == ["ctrl+alt+right", "ctrl+alt+left", "ctrl+alt+down"]
    kb.handlers["ctrl+alt+right"]()
    kb.handlers["ctrl+alt+left"]()
    kb.handlers["ctrl+alt+down"]()
    assert fired == ["next", "prev", "like"]


def test_missing_lib_returns_false(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "keyboard", None)  # import keyboard 会失败
    assert hotkeys.register(None, {}) is False
