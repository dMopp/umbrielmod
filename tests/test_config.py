from pathlib import Path

import pytest

from umbrielmod.config import Config, TomlFile, parse_literal, toml_literal

SAMPLE = """\
# Kopf
[general]
autostart = ["kitty"]

[output.HDMI-A-1]
scale = 1.333333
mode = "5120x2160@165" # game-hz
hdr = "on" # game-hz

# Kommentar zum Layout
[layout]

[layout.scrolling]
center_focused = "never"

# ==== Keybinds

[keybinds]
"Mod+Return" = { action = "spawn:kitty", repeat = false }
"Mod+H" = "window-focus-left"

# Regel 1
[[window_rule]]
blur = true

# Regel 2
[[window_rule]]
match.app_id = "Bitwarden"
default_floating = true

[include.optional]
files = ["extra.toml"]
"""

EXTRA = """\
[colors]
background = "#282828FF"
"""


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    (tmp_path / "config.toml").write_text(SAMPLE)
    (tmp_path / "extra.toml").write_text(EXTRA)
    return Config(tmp_path / "config.toml")


def test_roundtrip_untouched(cfg: Config):
    assert cfg.main.as_string() == SAMPLE
    assert not cfg.dirty


def test_replace_keeps_trailing_comment(cfg: Config):
    cfg.main.set(("output", "HDMI-A-1", "mode"), "5120x2160@100")
    assert 'mode = "5120x2160@100" # game-hz' in cfg.main.as_string()


def test_new_key_goes_before_next_section_comment(cfg: Config):
    cfg.main.set(("output", "HDMI-A-1", "vrr"), "fullscreen")
    text = cfg.main.as_string()
    assert text.index('vrr = "fullscreen"') < text.index("# Kommentar zum Layout")


def test_new_subtable_created_as_table(cfg: Config):
    cfg.main.set(("layout", "struts", "top"), 4)
    assert "[layout.struts]" in cfg.main.as_string()
    assert cfg.main.get(("layout", "struts", "top")) == 4


def test_rule_children_are_inline(cfg: Config):
    cfg.main.set(("window_rule", 0, "default_position", "x"), 10)
    assert "default_position = {x = 10}" in cfg.main.as_string()
    cfg.main.set(("window_rule", 1, "match", "title"), "Vault")
    assert cfg.main.get(("window_rule", 1, "match")) == {"app_id": "Bitwarden", "title": "Vault"}


def test_delete_and_prune(cfg: Config):
    cfg.main.delete(("layout", "scrolling", "center_focused"), prune=True)
    assert cfg.main.get(("layout", "scrolling")) is None


def test_keybind_string_and_table(cfg: Config):
    assert cfg.main.get(("keybinds", "Mod+H")) == "window-focus-left"
    cfg.main.set(("keybinds", "Mod+H"), {"action": "window-focus-left", "repeat": False})
    assert '"Mod+H" = {action = "window-focus-left", repeat = false}' in cfg.main.as_string()


def test_aot_append_move_delete(cfg: Config):
    idx = cfg.main.append_table(("window_rule",), {"opacity": 0.9})
    assert idx == 2
    cfg.main.move_table(("window_rule",), 2, 0)
    assert cfg.main.get(("window_rule", 0, "opacity")) == 0.9
    cfg.main.delete(("window_rule", 0))
    assert len(cfg.main.get(("window_rule",))) == 2
    TomlFile.set_text(cfg.main, cfg.main.as_string())  # still valid TOML


def test_includes_and_effective(cfg: Config):
    assert [f.path.name for f in cfg.files] == ["config.toml", "extra.toml"]
    assert cfg.includes()[0].optional
    assert cfg.effective(("colors", "background")) == "#282828FF"
    assert [f.path.name for f in cfg.definers(("colors", "background"))] == ["extra.toml"]


def test_undo_redo(cfg: Config):
    cfg.checkpoint()
    cfg.main.set(("general", "autostart"), ["kitty", "foot"])
    assert cfg.undo()
    assert cfg.main.as_string() == SAMPLE
    assert cfg.redo()
    assert cfg.main.get(("general", "autostart")) == ["kitty", "foot"]


def test_literals():
    assert parse_literal(toml_literal([0.1, 0.9])) == [0.1, 0.9]
    with pytest.raises(ValueError):
        parse_literal("[1,")


def test_rename_keeps_position(cfg: Config):
    cfg.main.rename(("keybinds", "Mod+Return"), "Mod+Shift+Return", {"action": "spawn:foot"})
    text = cfg.main.as_string()
    assert '"Mod+Shift+Return" = {action = "spawn:foot"}' in text
    assert text.index("Mod+Shift+Return") < text.index("Mod+H")
