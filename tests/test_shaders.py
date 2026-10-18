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
