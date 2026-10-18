"""UmbrielMod's own preferences (not Umbriel's): ~/.config/umbrielmod/settings.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "umbrielmod" / "settings.json"


def load() -> dict:
    try:
        return json.loads(path().read_text())
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - mirrors get()
    data = load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    save(data)
