"""Self-update for installations made by install.sh.

The launcher written by the installer exports ``UMBRIELMOD_MANAGED=1`` (plus
the branch and its own path). Only then does UmbrielMod look for updates:
``git ls-remote`` against the install's origin, and – if the branch moved –
it runs the *new* version's ``install.sh --install --skip-deps``, exactly as a
user re-running the curl command would. The running app keeps working (all
modules are already imported); a restart picks up the new version.
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
    branch: str
    local: str
    remote: str

    @property
    def available(self) -> bool:
        return bool(self.remote) and self.remote != self.local


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


def check(root: Path = ROOT, timeout: float = 10) -> UpdateInfo | None:
    """Compare the installed commit with the remote branch (one network call).
    Returns None when the check could not be done (offline, no git …)."""
    try:
        br = branch(root)
        local = _git(root, "rev-parse", "HEAD").stdout.strip()
        proc = _git(root, "ls-remote", "origin", f"refs/heads/{br}", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not local:
        return None
    remote = proc.stdout.split()[0] if proc.stdout.strip() else ""
    return UpdateInfo(br, local, remote)


def apply(info: UpdateInfo, root: Path = ROOT) -> tuple[bool, str]:
    """Fetch the new version and run its installer. Blocking; returns (ok, log)."""
    log: list[str] = []
    try:
        fetch = _git(root, "fetch", "--depth", "1", "origin", info.branch, timeout=300)
        log.append(fetch.stdout + fetch.stderr)
        if fetch.returncode != 0:
            return False, "".join(log).strip()
        script = _git(root, "show", "FETCH_HEAD:install.sh").stdout
        if not script.startswith("#!"):
            return False, "install.sh not found in the new version"
        url = _git(root, "remote", "get-url", "origin").stdout.strip()
        with tempfile.NamedTemporaryFile("w", suffix=".sh", prefix="umbrielmod-install-", delete=False) as fh:
            fh.write(script)
            path = fh.name
        try:
            env = dict(_ENV, UMBRIELMOD_REPO=url, LC_ALL=os.environ.get("LC_ALL", ""))
            proc = subprocess.run(
                ["bash", path, "--install", "--skip-deps", "--branch", info.branch],
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
    """Subject of the installed commit, e.g. after an update."""
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
