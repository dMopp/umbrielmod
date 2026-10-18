"""Self-update for installations made by install.sh.

The launcher written by the installer exports ``UMBRIELMOD_MANAGED=1`` plus the
update channel and its own path. Only then does UmbrielMod look for updates
with one ``git ls-remote`` against the install's origin:

* ``release`` channel (default): the newest ``vX.Y.Z`` tag is compared with
  the installed version;
* ``branch`` channel (``install.sh --branch main``): the branch head is
  compared with the installed commit.

When something newer exists it runs the *new* version's
``install.sh --install --skip-deps``, exactly as re-running the curl command
would. The running app keeps working (all modules are already imported); a
restart picks up the new version.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")


@dataclass
class UpdateInfo:
    channel: str  # "release" or "branch"
    ref: str  # tag (vX.Y.Z) or branch name to install
    local: str  # installed version or commit
    remote: str  # newest version or commit

    @property
    def available(self) -> bool:
        if not self.remote:
            return False
        if self.channel == "release":
            return parse_version(self.remote) > parse_version(self.local)
        return self.remote != self.local

    @property
    def branch(self) -> str:  # backwards compatible name
        return self.ref


def parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for p in text.lstrip("v").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def channel() -> str:
    """Launchers from before releases existed set only a branch (always main by
    default); they move to the release channel."""
    value = os.environ.get("UMBRIELMOD_CHANNEL", "")
    return value if value in ("release", "branch") else "release"


def is_managed(root: Path = ROOT) -> bool:
    return os.environ.get("UMBRIELMOD_MANAGED") == "1" and (root / ".git").exists()


def _git(root: Path, *args: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=_ENV, timeout=timeout)


def branch(root: Path = ROOT) -> str:
    env_branch = os.environ.get("UMBRIELMOD_BRANCH", "")
    if env_branch:
        return env_branch
    out = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return out if out and out != "HEAD" else "main"


def latest_release(root: Path = ROOT, timeout: float = 10) -> str | None:
    """Newest ``X.Y.Z`` from the origin's ``vX.Y.Z`` tags ("" when none)."""
    proc = _git(root, "ls-remote", "--tags", "--refs", "origin", "v*", timeout=timeout)
    if proc.returncode != 0:
        return None
    versions = []
    for line in proc.stdout.splitlines():
        tag = line.rsplit("refs/tags/", 1)[-1]
        if tag.startswith("v") and tag[1:2].isdigit():
            versions.append(tag[1:])
    return max(versions, key=parse_version) if versions else ""


def check(root: Path = ROOT, timeout: float = 10) -> UpdateInfo | None:
    """One network call: is a newer release (or branch commit) available?
    Returns None when the check could not be done (offline, no git …)."""
    try:
        if channel() == "release":
            from . import __version__

            latest = latest_release(root, timeout)
            if latest is None:
                return None
            return UpdateInfo("release", f"v{latest}" if latest else "", __version__, latest)
        br = branch(root)
        local = _git(root, "rev-parse", "HEAD").stdout.strip()
        proc = _git(root, "ls-remote", "origin", f"refs/heads/{br}", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not local:
        return None
    remote = proc.stdout.split()[0] if proc.stdout.strip() else ""
    return UpdateInfo("branch", br, local, remote)


def apply(info: UpdateInfo, root: Path = ROOT) -> tuple[bool, str]:
    """Fetch the new version and run its installer. Blocking; returns (ok, log)."""
    log: list[str] = []
    try:
        if info.channel == "release":
            fetch = _git(root, "fetch", "--depth", "1", "--force", "origin", "tag", info.ref, timeout=300)
            script_ref = info.ref
        else:
            fetch = _git(root, "fetch", "--depth", "1", "origin", info.ref, timeout=300)
            script_ref = "FETCH_HEAD"
        log.append(fetch.stdout + fetch.stderr)
        if fetch.returncode != 0:
            return False, "".join(log).strip()
        script = _git(root, "show", f"{script_ref}:install.sh").stdout
        if not script.startswith("#!"):
            return False, "install.sh not found in the new version"
        url = _git(root, "remote", "get-url", "origin").stdout.strip()
        with tempfile.NamedTemporaryFile("w", suffix=".sh", prefix="umbrielmod-install-", delete=False) as fh:
            fh.write(script)
            path = fh.name
        try:
            env = dict(_ENV, UMBRIELMOD_REPO=url, LC_ALL=os.environ.get("LC_ALL", ""))
            target = ["--version", info.ref] if info.channel == "release" else ["--branch", info.ref]
            proc = subprocess.run(
                ["bash", path, "--install", "--skip-deps", *target],
                capture_output=True, text=True, env=env, timeout=900,
            )
        finally:
            os.unlink(path)
        log.append(proc.stdout + proc.stderr)
        return proc.returncode == 0, "".join(log).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.append(str(exc))
        return False, "".join(log).strip()


def summary(root: Path = ROOT) -> str:
    """The installed version: release tag if HEAD is one, else the commit."""
    tag = _git(root, "describe", "--tags", "--exact-match").stdout.strip()
    if tag:
        return tag
    return _git(root, "log", "-1", "--format=%h %s").stdout.strip()


def launcher() -> str | None:
    path = os.environ.get("UMBRIELMOD_LAUNCHER", "")
    return path if path and os.access(path, os.X_OK) else None


def restart(argv: list[str]) -> None:
    """Replace the running process with the (updated) launcher."""
    exe = launcher()
    if exe:
        os.execv(exe, [exe, *argv[1:]])
    import sys

    os.execv(sys.executable, [sys.executable, "-m", "umbrielmod", *argv[1:]])
