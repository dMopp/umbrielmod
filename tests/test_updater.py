import subprocess
from pathlib import Path

from umbrielmod import updater


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def test_check_detects_new_remote_commit(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    (src / "f").write_text("1")
    git("add", "f", cwd=src)
    git("commit", "-qm", "one", cwd=src)
    git("clone", "-q", "--bare", str(src), str(tmp_path / "remote.git"), cwd=tmp_path)
    git("clone", "-q", "--depth", "1", f"file://{tmp_path / 'remote.git'}", str(tmp_path / "app"), cwd=tmp_path)
    app = tmp_path / "app"

    monkeypatch.delenv("UMBRIELMOD_MANAGED", raising=False)
    assert not updater.is_managed(app)
    monkeypatch.setenv("UMBRIELMOD_MANAGED", "1")
    monkeypatch.setenv("UMBRIELMOD_BRANCH", "main")
    assert updater.is_managed(app)

    assert not updater.check(app).available
    (src / "f").write_text("2")
    git("commit", "-qam", "two", cwd=src)
    git("push", "-q", str(tmp_path / "remote.git"), "main", cwd=src)
    info = updater.check(app)
    assert info.available and info.branch == "main"


def test_check_offline_returns_none(tmp_path: Path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    git("init", "-q", cwd=app)
    assert updater.check(app) is None  # no commit, no origin
