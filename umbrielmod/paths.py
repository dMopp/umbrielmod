"""XDG base directories. Unset, empty or relative values mean the default (per the spec)."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, default: Path) -> Path:
    value = os.environ.get(var, "")
    return Path(value) if os.path.isabs(value) else default


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config")


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", Path.home() / ".cache")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
