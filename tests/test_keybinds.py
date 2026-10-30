from umbrielmod.umbriel import split_action
from umbrielmod.pages.keybinds import compose_bind, find_conflicts, normalize_combo, parse_bind


def test_normalize():
    assert normalize_combo("Mod+Shift+Q") == normalize_combo("shift+mod+q")
    assert normalize_combo("Control+Alt+Delete") == normalize_combo("Ctrl+Alt+Delete")
    assert normalize_combo("Mod") == "mod"


def test_conflicts_respect_submap():
    binds = {
        "Mod+Shift+Q": "a",
        "Shift+Mod+Q": "b",
        "Mod+Q": "c",
        "mod+q": {"action": "d", "submap": "resize"},
    }
    assert set(find_conflicts(binds)) == {"Mod+Shift+Q", "Shift+Mod+Q"}


def test_compose_roundtrip():
    assert compose_bind("window-close", {"repeat": True, "submap": ""}) == "window-close"
    value = compose_bind("spawn:kitty", {"repeat": False, "cooldown_ms": 0})
    assert value == {"action": "spawn:kitty", "repeat": False}
    assert parse_bind(value) == ("spawn:kitty", {"repeat": False})


def test_split_action():
    assert split_action("workspace-switch 1") == ("workspace-switch", "1")
    assert split_action("workspace-switch:1") == ("workspace-switch", "1")
    assert split_action("spawn foot -e a:b") == ("spawn", "foot -e a:b")
    assert split_action("window-close") == ("window-close", "")
