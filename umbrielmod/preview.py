"""Live previews rendered by Umbriel itself.

Umbriel can only apply presets it has loaded. For effects that are not part of
the running configuration (catalogue effects, or animation effects that need
their event selection), a preview session writes a copy of the saved
``config.toml`` next to it that additionally includes the effect, validates it
and switches the compositor to it with ``umbriel config-replace``. Stopping the
session switches back to the real file. Nothing the user saved is modified.

Border and window presets are then applied to the preview window only
(``effect-<slot>-set:<name>/<window-id>``); screen and cursor presets are
applied globally on request and reset when the preview closes.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import config as cfgmod
from . import shaders, umbriel

PREVIEW_NAME = ".umbrielmod-preview.toml"


def preview_path(cfg: cfgmod.Config) -> Path:
    return cfg.dir / PREVIEW_NAME


def recover(cfg: cfgmod.Config) -> bool:
    """Undo a preview left behind by a crash. Returns True if one was found."""
    path = preview_path(cfg)
    if not path.exists():
        return False
    umbriel.config_replace(str(cfg.main.real_path))
    path.unlink(missing_ok=True)
    return True


def _loaded_presets(cfg: cfgmod.Config) -> set[str]:
    """Presets defined by the configuration as saved on disk."""
    disk = cfgmod.Config(cfg.main.path)
    return set(shaders.preset_names(disk))


class PreviewSession:
    def __init__(self, cfg: cfgmod.Config, effect: shaders.Effect):
        self.cfg = cfg
        self.effect = effect
        self.replaced = False
        self.applied: list[str] = []  # reset actions to run on stop

    @property
    def kind(self) -> str:
        return self.effect.kind

    @property
    def name(self) -> str:
        return self.effect.name

    def animation_events(self) -> list[str]:
        return [p[1] for p, _v in shaders.activation_changes(self.effect)
                if len(p) == 3 and p[0] == "animation" and p[2] == "effect"]

    def start(self) -> tuple[bool, str]:
        """Make sure Umbriel has the preset loaded (and, for animations,
        selected). Returns (ok, message)."""
        needs_include = self.name not in _loaded_presets(self.cfg)
        needs_activation = self.kind == "animation"
        if not needs_include and not needs_activation:
            return True, ""
        target = preview_path(self.cfg)
        target.write_text(self.cfg.main.real_path.read_text())
        tmp = cfgmod.TomlFile(target)
        if needs_include:
            files = list(tmp.get(("include", "files"), []) or [])
            files.append(str(self.effect.effect_toml))
            tmp.set(("include", "files"), files)
        if needs_activation:
            for path, value in shaders.activation_changes(self.effect):
                if path[0] == "animation":
                    tmp.set(path, value)
        target.write_text(tmp.as_string())
        ok, msg = umbriel.validate(str(target))
        if not ok:
            target.unlink(missing_ok=True)
            return False, msg
        ok, msg = umbriel.config_replace(str(target))
        if not ok:
            target.unlink(missing_ok=True)
            return False, msg
        self.replaced = True
        return True, ""

    def apply_to_window(self, window_id: str) -> tuple[bool, str]:
        if self.kind not in ("border", "window"):
            return True, ""
        ok, msg = umbriel.msg(f"effect-{self.kind}-set:{self.name}/{window_id}")
        if ok:
            self.applied.append(f"effect-{self.kind}-reset:{window_id}")
        return ok, msg

    def set_global(self, enabled: bool) -> tuple[bool, str]:
        """Screen/cursor presets: show on the whole output / pointer."""
        if self.kind not in ("screen", "cursor"):
            return True, ""
        reset = f"effect-{self.kind}-reset"
        if enabled:
            ok, msg = umbriel.msg(f"effect-{self.kind}-set:{self.name}")
            if ok and reset not in self.applied:
                self.applied.append(reset)
            return ok, msg
        if reset in self.applied:
            self.applied.remove(reset)
        return umbriel.msg(reset)

    def stop(self) -> None:
        for action in self.applied:
            umbriel.msg(action)
        self.applied.clear()
        if self.replaced:
            umbriel.config_replace(str(self.cfg.main.real_path))
            preview_path(self.cfg).unlink(missing_ok=True)
            self.replaced = False


def find_window_id(title: str, pid: int | None = None) -> str | None:
    pid = pid or os.getpid()
    for w in umbriel.windows():
        if w.get("title") == title and (not w.get("pid") or w.get("pid") == pid):
            return w.get("id")
    return None
