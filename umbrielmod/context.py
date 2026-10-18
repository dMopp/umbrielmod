"""State shared by all pages: config, schema, docs and change notification."""

from __future__ import annotations

import time
from typing import Callable

from . import umbriel
from .config import Config, TomlFile
from .docs import Docs
from .schema import Schema


class AppContext:
    def __init__(self, cfg: Config, schema: Schema, docs: Docs):
        self.cfg = cfg
        self.schema = schema
        self.docs = docs
        self._actions: list[umbriel.Action] | None = None
        self._listeners: list[Callable[[], None]] = []
        self.toast: Callable[[str], None] = print
        self.open_uri: Callable[[str], None] = lambda uri: None
        self._last_edit: tuple = ()
        self._last_edit_time = 0.0

    # ----------------------------------------------------------------- lazy data

    @property
    def actions(self) -> list[umbriel.Action]:
        if self._actions is None:
            self._actions = umbriel.actions()
        return self._actions

    # ----------------------------------------------------------------- edits

    def on_changed(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def changed(self) -> None:
        for cb in list(self._listeners):
            cb()

    def checkpoint(self, tf: TomlFile, path: tuple = ()) -> None:
        """Record an undo step; rapid edits of the same field are coalesced."""
        now = time.monotonic()
        key = (str(tf.real_path), path)
        if key != self._last_edit or now - self._last_edit_time > 1.5 or not path:
            self.cfg.checkpoint(tf)
        self._last_edit, self._last_edit_time = key, now

    def set(self, tf: TomlFile, path: tuple, value) -> None:
        self.checkpoint(tf, path)
        tf.set(path, value)
        self.changed()

    def delete(self, tf: TomlFile, path: tuple, *, prune: bool = True) -> None:
        self.checkpoint(tf, path)
        tf.delete(path, prune=prune)
        self.changed()

    def edit(self, tf: TomlFile, fn: Callable[[], None]) -> None:
        """Run a structural edit (several changes) as one undo step."""
        self.cfg.checkpoint(tf)
        self._last_edit = ()
        fn()
        self.changed()
