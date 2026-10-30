import subprocess
from pathlib import Path

import pytest

from umbrielmod import config as cfgmod
from umbrielmod import shaders

GLSL = """\
// Flowering vine
#define ring_padding 8.0
#define ring_size (umbriel_border_hole.zw * umbriel_size)
const float VINE_SPEED = 0.75; // growth speed
const int PETALS = 5;
const vec3 LEAF_COLOR = vec3(0.2, 0.8, 0.3);
const vec3 GREY = vec3(0.5);
/*
const float HIDDEN = 1.0;
*/
float f() {
    const float quarter = 1.57;
    return quarter;
}
"""


def test_parse_constants():
    consts = {c.name: c for c in shaders.parse_constants(GLSL)}
    assert set(consts) == {"ring_padding", "VINE_SPEED", "PETALS", "LEAF_COLOR", "GREY"}
    assert consts["VINE_SPEED"].comment == "growth speed"
    assert consts["GREY"].values == [0.5, 0.5, 0.5]
    assert consts["LEAF_COLOR"].is_color


def test_set_constant_and_ring_padding():
    consts = {c.name: c for c in shaders.parse_constants(GLSL)}
    out = shaders.set_constant(GLSL, consts["VINE_SPEED"], [1.5])
    assert "const float VINE_SPEED = 1.5; // growth speed" in out
    out = shaders.set_constant(out, consts["LEAF_COLOR"], [1, 0, 0])
    assert "vec3(1.0, 0.0, 0.0)" in out
    assert "#define ring_padding 12.0" in shaders.sync_ring_padding(out, 12)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    repo = tmp_path / "repo"
    border = repo / "border" / "vine"
    overlay = repo / "window" / "vine-overlay"
    for d in (border, overlay):
        d.mkdir(parents=True)
    (repo / "LICENSES").mkdir()
    (repo / "LICENSES" / "X-MIT.txt").write_text("MIT")
    (border / "effect.toml").write_text(
        '[include]\nfiles = ["../../window/vine-overlay/effect.toml"]\n\n'
        '[effects.preset."vine"]\nkind = "border"\nshader = "shader.glsl"\npadding = 8\noverlay = "vine-overlay"\n'
    )
    (border / "shader.glsl").write_text(GLSL)
    (border / "README.md").write_text("# Vine\n\nA growing vine.\n\nLicense: [MIT](../../LICENSES/X-MIT.txt).\n")
    (border / "config.toml").write_text(
        '[include]\nfiles = ["shaders/community/border/vine/effect.toml"]\n\n[effects]\nborder = "vine"\n'
    )
    (overlay / "effect.toml").write_text('[effects.preset."vine-overlay"]\nkind = "window"\nshader = "shader.glsl"\n')
    (overlay / "shader.glsl").write_text("void main() {}\n")
    cfg_dir = tmp_path / "cfg" / "umbriel"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text("[general]\nxwayland = true\n")
    return repo


def test_install_activate_uninstall(env: Path):
    eff = next(e for e in shaders.scan(env) if e.rel.name == "vine")
    assert eff.kind == "border" and eff.name == "vine" and eff.title == "Vine"
    assert eff.summary == "A growing vine."
    dirs = shaders.install_files(eff)
    assert {d.name for d in dirs} == {"vine", "vine-overlay"}
    assert (shaders.install_root() / "border/vine/X-MIT.txt").exists()
    assert (shaders.install_root() / "border/vine/shader.glsl.orig").exists()

    cfg = cfgmod.Config()
    shaders.add_include(cfg, eff)
    shaders.apply_activation(cfg, eff)
    assert cfg.main.get(("include", "files")) == ["shaders/community/border/vine/effect.toml"]
    assert cfg.main.get(("effects", "border")) == "vine"
    # the border's own include pulls in the overlay
    assert {f.path.parent.name for f in cfg.includes()} == {"vine", "vine-overlay"}
    assert shaders.suggestions_for(cfg, "border") == ["vine"]

    assert shaders.references(cfg, {"vine"}) == [("effects", "border")]
    shaders.clear_references(cfg, {"vine"})
    shaders.remove_include(cfg, eff)
    assert cfg.main.get(("include",)) is None
    assert cfg.main.get(("effects",)) is None
    shaders.remove_files(eff)
    assert not (shaders.install_root() / "border").exists()


def test_parse_progress():
    assert shaders.parse_progress("Receiving objects:  50% (1/2), 1.00 MiB | 2.00 MiB/s") == pytest.approx(0.425)
    assert shaders.parse_progress("Resolving deltas: 100% (3/3), done.") == pytest.approx(0.95)
    assert shaders.parse_progress("Updating files: 100% (9/9), done.") == pytest.approx(1.0)
    assert shaders.parse_progress("remote: Compressing objects: 100% (9/9), done.") is None
    assert shaders.parse_progress("fatal: repository not found") is None


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


def test_sync_repo_reports_rising_progress(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    (src / "f.txt").write_text("x" * 100_000)
    _git("add", "f.txt", cwd=src)
    _git("commit", "-qm", "one", cwd=src)
    monkeypatch.setattr(shaders, "REPO_URL", f"file://{src}")
    seen: list[float] = []
    repo = tmp_path / "cache" / "repo"

    ok, _msg = shaders.sync_repo(repo, seen.append)
    assert ok and (repo / "f.txt").exists() and not repo.with_name("repo.new").exists()
    assert seen and seen == sorted(seen) and 0 <= seen[0] and seen[-1] <= 1

    (src / "f.txt").write_text("y")
    _git("commit", "-qam", "two", cwd=src)
    ok, _msg = shaders.sync_repo(repo, seen.append)
    assert ok and (repo / "f.txt").read_text() == "y"


def test_sync_repo_returns_git_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(shaders, "REPO_URL", f"file://{tmp_path}/missing")
    ok, msg = shaders.sync_repo(tmp_path / "cache" / "repo", lambda f: None)
    assert not ok and "missing" in msg and not (tmp_path / "cache" / "repo").exists()
