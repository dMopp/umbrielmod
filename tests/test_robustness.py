import json
import os
from pathlib import Path

import pytest

from umbrielmod import config, docs, paths, shaders, umbriel, updater
from umbrielmod.config import Config


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for var, name in (("XDG_CONFIG_HOME", "c"), ("XDG_STATE_HOME", "s"), ("XDG_CACHE_HOME", "x")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "etc"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "share"))
    monkeypatch.setattr(umbriel, "validate", lambda path: (True, "ok"))
    monkeypatch.setattr(config.shutil, "which", lambda name: None)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ------------------------------------------------------------------ config safety


def test_syntax_error_never_empties_the_file():
    p = write(config.default_config_path(), "[general]\nautostart = []\n")
    cfg = Config(p)
    broken = '[general]\nautostart = ["x"\nOOPS\n'
    p.write_text(broken)
    cfg.reload()
    assert cfg.main.error and not cfg.dirty
    assert cfg.save() == (True, "No changes")
    assert p.read_text() == broken
    assert cfg.main.as_string() == broken  # the raw editor shows what is there
    cfg.main.set_text("[general]\n")
    assert cfg.main.error is None and cfg.dirty


def test_first_save_keeps_the_packaged_defaults(tmp_path):
    write(tmp_path / "etc" / "umbriel" / "config.toml", '[keybinds]\n"Mod+Q" = "close"\n')
    cfg = Config(config.default_config_path())
    assert not cfg.main.exists and not cfg.dirty and not cfg.changed_on_disk()
    cfg.main.set(("colors", "error"), "#ff0000ff")
    assert cfg.save()[0]
    saved = config.default_config_path().read_text()
    assert '"Mod+Q" = "close"' in saved and "#ff0000ff" in saved


def test_explicit_path_is_not_seeded(tmp_path):
    write(tmp_path / "etc" / "umbriel" / "config.toml", "[general]\n")
    assert Config(tmp_path / "other.toml").main.text == ""


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write everywhere")
def test_read_only_config_is_reported(tmp_path):
    d = tmp_path / "ro"
    p = write(d / "config.toml", "[general]\n")
    os.chmod(p, 0o444)
    os.chmod(d, 0o555)
    try:
        cfg = Config(p)
        cfg.main.set(("colors", "error"), "#ff0000ff")
        ok, message = cfg.save()
        assert not ok and str(p) in message
    finally:
        os.chmod(d, 0o755)


def test_unreadable_files_do_not_crash(tmp_path):
    p = write(tmp_path / "config.toml", '[include]\nfiles = ["sub"]\noptional.files = "ab"\n')
    (tmp_path / "sub").mkdir()
    cfg = Config(p)
    assert [f.path.name for f in cfg.files] == ["config.toml", "sub"]
    assert cfg.files[1].error
    p.write_bytes(b"# \xff\n")
    assert Config(p).main.error


def test_validation_with_outside_include_and_symlink_loop(tmp_path, monkeypatch):
    seen = {}

    def validate(path):
        seen["text"] = Path(path).read_text()
        return True, "ok"

    monkeypatch.setattr(umbriel, "validate", validate)
    outside = write(tmp_path / "noctalia" / "u.toml", "[colors]\n")
    p = write(tmp_path / "umbriel" / "config.toml", '[include]\nfiles = ["../noctalia/u.toml"]\n')
    os.symlink(p.parent, p.parent / "loop")
    ok, _message = Config(p).validate({})
    assert ok and str(outside) in seen["text"]


def test_backups_restore_to_the_right_file(tmp_path):
    other = write(tmp_path / "other" / "config.toml", "a = 1\n")
    odd = write(config.config_dir() / "my__x.toml", "a = 1\n")
    config.backup_file(other)
    config.backup_file(odd.resolve())
    assert {b[2] for b in config.list_backups()} == {other, odd}


def test_old_backup_names_still_work():
    write(config.backup_dir() / "20200101-000000__shaders__a.toml", "x")
    assert config.list_backups()[0][2] == config.config_dir() / "shaders" / "a.toml"


def test_pruning_stays_within_one_file():
    for i in range(3):
        write(config.backup_dir() / f"2020010{i + 1}-000000__shaders%2Fconfig.toml", "x")
    main = write(config.config_dir() / "config.toml", "a = 1\n")
    config.backup_file(main.resolve(), keep=1)
    assert len(list(config.backup_dir().glob("*shaders*"))) == 3


def test_empty_xdg_means_default(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    assert paths.config_home() == Path.home() / ".config"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert paths.config_home() == Path.home() / ".config"


# ------------------------------------------------------------------ catalogue


def effect_dir(root: Path, toml: str, name: str = "e") -> Path:
    d = root / "border" / name
    write(d / "effect.toml", toml)
    write(d / "x.glsl", "//\n")
    return d


GOOD = '[effects.preset.e]\nkind = "border"\nshader = "x.glsl"\n'


@pytest.mark.parametrize("toml", [
    GOOD + '[keybinds]\n"Mod+X" = "spawn evil"\n',
    GOOD + '[general]\nautostart = ["evil"]\n',
    GOOD + '[include]\nfiles = ["../../../evil.toml"]\n',
    GOOD + '[include]\nfiles = ["~/evil.toml"]\n',
    '[effects.preset.e]\nkind = "border"\nshader = "../../../secret"\n',
])
def test_unsafe_effects_are_rejected(tmp_path, monkeypatch, toml):
    repo = tmp_path / "repo"
    d = effect_dir(repo, toml)
    effect = shaders.load_effect(repo, d)
    assert shaders.unsafe_reason(effect)
    with pytest.raises(shaders.UnsafeEffect):
        shaders.install_files(effect)
    monkeypatch.setattr(shaders, "cache_repo_dir", lambda: repo)
    assert shaders.catalog() == []


def test_good_effect_is_offered(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    effect_dir(repo, GOOD)
    monkeypatch.setattr(shaders, "cache_repo_dir", lambda: repo)
    assert [e.name for e in shaders.catalog()] == ["e"]


def test_install_copies_nothing_from_outside(tmp_path):
    secret = write(tmp_path / "secret.txt", "TOPSECRET")
    repo = tmp_path / "repo"
    d = effect_dir(repo, GOOD)
    write(repo / "LICENSES" / "MIT.txt", "mit")
    write(d / "README.md", "# E\n[a](../../LICENSES/MIT.txt) [b](../../LICENSES/../../secret.txt)\n")
    os.symlink(secret, d / "stolen.md")
    dst = shaders.install_files(shaders.load_effect(repo, d))[0]
    names = {f.name for f in dst.iterdir()}
    assert "MIT.txt" in names and "secret.txt" not in names and "stolen.md" not in names


def test_activation_only_selects_effects(tmp_path):
    repo = tmp_path / "repo"
    d = effect_dir(repo, GOOD)
    write(d / "config.toml", '[effects]\nborder = "e"\n[animation.windows_in]\neffect = "e"\n'
                             '[general]\nautostart = ["evil"]\n[keybinds]\n"Mod+X" = "spawn evil"\n')
    changes = shaders.activation_changes(shaders.load_effect(repo, d))
    assert sorted(p[0] for p, _v in changes) == ["animation", "effects"]


@pytest.mark.parametrize("toml", ["effects = 3\n", "[effects]\npreset = 3\n", "[effects.preset]\na = 1\n", "[include]\nfiles = 3\n"])
def test_malformed_effect_does_not_break_the_scan(tmp_path, toml):
    d = effect_dir(tmp_path, toml)
    write(d / "README.md", "x")
    effect = shaders.scan(tmp_path)[0]
    assert effect.kind == "border" and effect.title and effect.shader_paths == []


def test_invalid_utf8_readme(tmp_path):
    d = effect_dir(tmp_path, GOOD)
    (d / "README.md").write_bytes(b"\xff\xfe# x")
    assert shaders.scan(tmp_path)[0].title


# ------------------------------------------------------------------ umbriel, updater, docs


def test_unexpected_outputs_text(monkeypatch):
    import subprocess

    done = subprocess.CompletedProcess([], 0, "A x\n  Position: foo\n", "")
    monkeypatch.setattr(umbriel, "_run", lambda *a, **k: done)
    assert umbriel.outputs() == []


def test_missing_binary_is_reported(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(umbriel, "BINARY", "/nonexistent/umbriel")
    assert umbriel.validate("x")[0] is False
    assert umbriel.msg("x")[0] is False
    assert umbriel.windows() == []
    with pytest.raises(umbriel.UmbrielError):
        umbriel.schema_json()


def test_schema_json_garbage(monkeypatch):
    import subprocess

    monkeypatch.setattr(umbriel, "_run", lambda *a, **k: subprocess.CompletedProcess([], 0, "not json", ""))
    with pytest.raises(umbriel.UmbrielError):
        umbriel.schema_json()


def test_prerelease_tags_are_ignored(monkeypatch):
    import subprocess

    out = "a\trefs/tags/v0.3.0\nb\trefs/tags/v0.4.0-rc1\nc\trefs/tags/v9$(evil)\n"
    monkeypatch.setattr(updater, "_git", lambda *a, **k: subprocess.CompletedProcess([], 0, out, ""))
    assert updater.latest_release(Path("/")) == "0.3.0"
    assert updater.parse_version("0.4.0-rc1") == (0, 4, 0)


def test_update_lock_is_exclusive():
    with updater.update_lock() as first:
        assert first is True
        with updater.update_lock() as second:
            assert second is False
    with updater.update_lock() as again:
        assert again is True


def test_docs_cache_name_matches_refresh():
    sha = docs._revision_sha("0.1.0-gabc123")
    assert sha == "abc123"
    assert docs._revision_sha("--upload-pack=evil") == ""
    assert docs._revision_sha("../../evil") == ""
    write(docs.cache_dir() / f"docs-{sha}.json", json.dumps({"revision": sha}))
    assert docs.Docs.load("0.1.0-gabc123").revision == sha
