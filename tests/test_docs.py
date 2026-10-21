from umbrielmod.docs import _best_anchor

OUTPUTS = [
    ("settings", "Settings", "| `position` | ... |\n| `scale` | ... |\n"),
    ("position-and-scale", "Position and scale", "An output at scale `1.25` ...\nOmit `position` to place outputs ...\n"),
    ("window-capture-resolution", "Window capture resolution", "... at scale 2.5 ...\n"),
]


def test_heading_with_sibling_key_links_plain_mention():
    assert _best_anchor(OUTPUTS, "scale", "settings", frozenset({"position", "mode"})) == "position-and-scale"
    assert _best_anchor(OUTPUTS, "position", "settings", frozenset({"scale"})) == "position-and-scale"


def test_heading_with_unrelated_words_keeps_table():
    secs = [
        ("settings", "Settings", "| `window` | ... |\n"),
        ("turn-a-default-off-for-one-window-or-output", "Turn a default off", "... one window ...\n"),
    ]
    assert _best_anchor(secs, "window", "settings", frozenset({"output"})) == "settings"
    assert _best_anchor(OUTPUTS, "scale", "settings") == "settings"
