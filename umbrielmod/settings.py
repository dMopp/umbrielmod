"""UmbrielMod's own preferences (not Umbriel's): ~/.config/umbrielmod/settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from . import paths


def path() -> Path:
    return paths.config_home() / "umbrielmod" / "settings.json"


def load() -> dict:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - mirrors get()
    data = load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    save(data)
