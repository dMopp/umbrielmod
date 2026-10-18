"""Thin wrappers around the `umbriel` command line interface."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field

BINARY = "umbriel"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class UmbrielError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which(BINARY) is not None


def _run(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [BINARY, *args], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UmbrielError(str(exc)) from exc


def version() -> str:
    return _run("--version").stdout.strip()


def schema_json() -> dict:
    proc = _run("config", "schema", "--json")
    if proc.returncode != 0:
        raise UmbrielError(proc.stderr.strip() or "umbriel config schema failed")
    return json.loads(proc.stdout)


def validate(config_path: str) -> tuple[bool, str]:
    """Run `umbriel config validate -c <path>`; returns (ok, message)."""
    proc = _run("config", "validate", "-c", config_path)
    message = _ANSI_RE.sub("", proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, message


def msg(action: str) -> tuple[bool, str]:
    """Send an action to the running compositor."""
    proc = _run("msg", action)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


# --------------------------------------------------------------------------- actions


@dataclass
class Action:
    name: str  # e.g. "workspace-switch"
    arg: str  # e.g. "<index>", "[<window-id>]" or "" when it takes none
    group: str
    description: str

    @property
    def takes_arg(self) -> bool:
        return bool(self.arg)

    @property
    def arg_required(self) -> bool:
        return self.arg.startswith("<")


_ACTION_RE = re.compile(r"^  (\S+?)(?::(\S+))?\s{2,}(.+)$")


def parse_actions(help_text: str) -> list[Action]:
    actions: list[Action] = []
    group = ""
    for line in help_text.splitlines():
        if line and not line.startswith(" ") and not line.endswith(":") and not line.startswith(("Usage", "Send", "Use", "Available")):
            group = line.strip()
            continue
        m = _ACTION_RE.match(line)
        if m and group:
            actions.append(Action(m.group(1), m.group(2) or "", group, m.group(3).strip()))
    return actions


def actions() -> list[Action]:
    try:
        return parse_actions(_run("msg", "--help").stdout)
    except UmbrielError:
        return []


# --------------------------------------------------------------------------- outputs


@dataclass
class Mode:
    width: int
    height: int
    refresh: float
    preferred: bool = False
    current: bool = False

    def config_string(self) -> str:
        hz = round(self.refresh)
        return f"{self.width}x{self.height}@{hz}"

    def label(self) -> str:
        from .i18n import _

        tags = [t for t, on in ((_("current"), self.current), (_("preferred"), self.preferred)) if on]
        extra = f"  ({', '.join(tags)})" if tags else ""
        return f"{self.width}×{self.height} @ {self.refresh:.3f} Hz{extra}"


@dataclass
class Output:
    name: str
    description: str = ""
    config_name: str = ""
    enabled: bool = True
    position: tuple[int, int] = (0, 0)
    scale: float = 1.0
    transform: str = "normal"
    modes: list[Mode] = field(default_factory=list)

    @property
    def current_mode(self) -> Mode | None:
        return next((m for m in self.modes if m.current), self.modes[0] if self.modes else None)

    def logical_size(self) -> tuple[int, int]:
        mode = self.current_mode
        if not mode:
            return (1920, 1080)
        w, h = mode.width, mode.height
        if self.transform in ("90", "270", "flipped-90", "flipped-270"):
            w, h = h, w
        return (round(w / self.scale), round(h / self.scale))


_MODE_RE = re.compile(r"^\s+(\d+)x(\d+) @ ([\d.]+) Hz(.*)$")


def parse_outputs(text: str) -> list[Output]:
    outputs: list[Output] = []
    cur: Output | None = None
    for line in text.splitlines():
        if line and not line.startswith(" "):
            name, _sep, desc = line.partition(" ")
            cur = Output(name=name, description=desc.strip().strip('"'))
            outputs.append(cur)
            continue
        if cur is None:
            continue
        s = line.strip()
        if m := _MODE_RE.match(line):
            flags = m.group(4)
            cur.modes.append(
                Mode(int(m.group(1)), int(m.group(2)), float(m.group(3)),
                     "preferred" in flags, "current" in flags)
            )
        elif s.startswith("Config name:"):
            cur.config_name = s.split(":", 1)[1].strip().strip('"')
        elif s.startswith("Enabled:"):
            cur.enabled = s.endswith("yes")
        elif s.startswith("Position:"):
            x, _sep, y = s.split(":", 1)[1].strip().partition(",")
            cur.position = (int(x), int(y))
        elif s.startswith("Scale:"):
            cur.scale = float(s.split(":", 1)[1])
        elif s.startswith("Transform:"):
            cur.transform = s.split(":", 1)[1].strip()
    return outputs


def outputs() -> list[Output]:
    try:
        proc = _run("outputs")
    except UmbrielError:
        return []
    return parse_outputs(proc.stdout) if proc.returncode == 0 else []


# --------------------------------------------------------------------------- windows


def windows() -> list[dict]:
    """Snapshot of open windows (first event of `umbriel subscribe windows`)."""
    try:
        proc = subprocess.Popen(
            [BINARY, "subscribe", "windows"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
    except OSError:
        return []
    try:
        import select

        ready, _w, _x = select.select([proc.stdout], [], [], 2.0)
        line = proc.stdout.readline() if ready else ""
    finally:
        proc.kill()
        proc.wait()
    try:
        return list(json.loads(line).get("data", []))
    except ValueError:
        return []
