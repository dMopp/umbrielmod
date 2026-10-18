"""Install and configure effects from the community Umbriel shader collection.

Only settings that Umbriel itself understands are exposed:

* preset keys from ``[effects.preset."name"]`` (which depend on the kind),
* the border ``light`` table,
* selection via ``[effects]`` slots, ``animation.<event>.effect``,
  window rules, output ``screen_effect`` and pools,
* tuning via top-level ``#define`` / ``const`` values in the GLSL source,
  which is how the collection documents per-shader adjustments.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit

from . import config as cfgmod
from .i18n import N_

REPO_SLUG = "noctalia-dev/community-umbriel-shaders"
REPO_URL = f"https://github.com/{REPO_SLUG}"

KINDS = ("border", "window", "screen", "cursor", "animation")
# display names (translate with i18n._ when shown)
KIND_LABELS = {
    "border": N_("Border"),
    "window": N_("Window"),
    "screen": N_("Screen"),
    "cursor": N_("Cursor"),
    "animation": N_("Animation"),
}
SLOT_KINDS = ("border", "window", "screen", "cursor")

# Umbriel's preset keys per kind (upstream docs/user/effects.md): every kind has
# kind/shader/palette; only borders take padding/speed/animated/overlay/light and
# only cursors take radius.
PRESET_KEYS = {
    "border": ("palette", "padding", "speed", "animated", "overlay"),
    "window": ("palette",),
    "screen": ("palette",),
    "cursor": ("palette", "radius"),
    "animation": ("palette",),
}
LIGHT_KEYS = ("spread", "intensity", "threshold")
LIGHT_DEFAULTS = {"spread": 80, "intensity": 1.0, "threshold": 0.5}
PRESET_DEFAULTS = {"palette": False, "padding": 0, "speed": 1.0, "animated": True, "overlay": "", "radius": 0}

POINTER_HISTORY_TOKENS = ("umbriel_pointer_path", "umbriel_pointer_count")


def cache_repo_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "umbrielmod" / "community-umbriel-shaders"


def install_root() -> Path:
    return cfgmod.config_dir() / "shaders" / "community"


# --------------------------------------------------------------------------- repository


def repo_revision(repo: Path | None = None) -> str:
    repo = repo or cache_repo_dir()
    if not (repo / ".git").exists():
        return ""
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%h · %cs"],
        capture_output=True, text=True,
    )
    return proc.stdout.strip()


def sync_repo(repo: Path | None = None) -> tuple[bool, str]:
    """Clone or fast-forward the collection (shallow). Blocking."""
    repo = repo or cache_repo_dir()
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        if (repo / ".git").exists():
            steps = [
                ["git", "-C", str(repo), "fetch", "--depth", "1", "origin"],
                ["git", "-C", str(repo), "reset", "--hard", "FETCH_HEAD"],
            ]
        else:
            repo.parent.mkdir(parents=True, exist_ok=True)
            steps = [["git", "clone", "--depth", "1", REPO_URL, str(repo)]]
        for cmd in steps:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
            if proc.returncode != 0:
                return False, (proc.stderr or proc.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return True, repo_revision(repo)


# --------------------------------------------------------------------------- effects


def _read_toml(path: Path) -> dict:
    try:
        return tomlkit.parse(path.read_text()).unwrap()
    except Exception:
        return {}


def _presets_of(data: dict) -> dict[str, dict]:
    return dict(data.get("effects", {}).get("preset", {}))


def _includes_of(data: dict) -> list[str]:
    inc = data.get("include", {})
    return list(inc.get("files", [])) + list(inc.get("optional", {}).get("files", []))


_HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)
_LICENSE_RE = re.compile(r"\]\(((?:\.\./)+LICENSES/[^)]+)\)")


@dataclass
class Effect:
    """An effect directory containing ``effect.toml`` (catalog or installed)."""

    root: Path  # collection root (repo or install root)
    rel: Path  # e.g. border/flowering-vine
    presets: dict[str, dict] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return self.root / self.rel

    @property
    def effect_toml(self) -> Path:
        return self.dir / "effect.toml"

    @property
    def kind(self) -> str:
        for p in self.presets.values():
            if p.get("kind") in KINDS:
                return p["kind"]
        return self.rel.parts[0] if self.rel.parts else ""

    @property
    def name(self) -> str:
        """The main preset name (the one matching the directory if possible)."""
        names = list(self.presets)
        if not names:
            return self.rel.name
        return next((n for n in names if n == self.rel.name), names[0])

    @property
    def shader_paths(self) -> list[Path]:
        out = []
        for p in self.presets.values():
            if p.get("shader"):
                out.append((self.dir / p["shader"]).resolve())
        return out

    @property
    def readme(self) -> str:
        try:
            return (self.dir / "README.md").read_text()
        except OSError:
            return ""

    @property
    def title(self) -> str:
        m = _HEADING_RE.search(self.readme)
        return m.group(1).strip() if m else self.rel.name.replace("-", " ").title()

    @property
    def summary(self) -> str:
        """First prose paragraph of the README."""
        text = self.readme
        for para in re.split(r"\n\s*\n", text):
            p = para.strip()
            if not p or p.startswith(("#", "!", "|", "```", "<", "-", "*")):
                continue
            return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", " ".join(p.split()))
        return ""

    @property
    def preview(self) -> Path | None:
        for name in ("preview.png", "preview.gif", "preview.jpg"):
            if (self.dir / name).exists():
                return self.dir / name
        return None

    @property
    def needs_pointer_history(self) -> bool:
        for sp in self.shader_paths:
            try:
                src = sp.read_text()
            except OSError:
                continue
            if any(tok in src for tok in POINTER_HISTORY_TOKENS):
                return True
        return False

    @property
    def activation(self) -> dict:
        """The activation example (config.toml next to the effect) without
        its ``[include]`` table."""
        data = _read_toml(self.dir / "config.toml")
        data.pop("include", None)
        return data

    @property
    def license_files(self) -> list[Path]:
        out = []
        for m in _LICENSE_RE.finditer(self.readme):
            p = (self.dir / m.group(1)).resolve()
            if p.exists() and p not in out:
                out.append(p)
        return out

    def companions(self) -> list[Path]:
        """Effect directories pulled in by this effect's own ``[include]``."""
        out = []
        for inc in self.includes:
            p = (self.dir / inc).resolve()
            out.append(p.parent if p.name == "effect.toml" else p)
        return out


def load_effect(root: Path, effect_dir: Path) -> Effect:
    data = _read_toml(effect_dir / "effect.toml")
    return Effect(root=root, rel=effect_dir.relative_to(root), presets=_presets_of(data), includes=_includes_of(data))


def scan(root: Path) -> list[Effect]:
    """All effect directories below ``root`` (sorted by kind, then name)."""
    if not root.exists():
        return []
    effects = []
    for toml in root.glob("*/*/effect.toml"):
        if ".git" in toml.parts:
            continue
        effects.append(load_effect(root, toml.parent))
    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(effects, key=lambda e: (order.get(e.kind, 99), e.rel.name))


def catalog() -> list[Effect]:
    return scan(cache_repo_dir())


def installed() -> list[Effect]:
    return scan(install_root())


def installed_dir(effect: Effect) -> Path:
    return install_root() / effect.rel


def is_installed(effect: Effect) -> bool:
    return (installed_dir(effect) / "effect.toml").exists()


# --------------------------------------------------------------------------- install


def install_files(effect: Effect) -> list[Path]:
    """Copy an effect plus its companion overlays into the install root.

    Shaders already installed and edited locally are kept as ``.local`` copies
    so updating never silently discards tuning. Returns the installed dirs.
    """
    done: list[Path] = []
    pending = [effect.dir.resolve()]
    repo_root = effect.root.resolve()
    while pending:
        src = pending.pop()
        try:
            rel = src.relative_to(repo_root)
        except ValueError:
            continue
        dst = install_root() / rel
        if dst in done:
            continue
        dst.mkdir(parents=True, exist_ok=True)
        eff = load_effect(repo_root, src)
        for f in src.iterdir():
            if f.is_file() and f.suffix in (".toml", ".glsl", ".md") and f.name != "config.toml":
                target = dst / f.name
                if f.suffix == ".glsl" and target.exists():
                    orig = dst / (f.name + ".orig")
                    if orig.exists() and orig.read_text() != target.read_text():
                        shutil.copy2(target, dst / (f.name + ".local"))
                shutil.copy2(f, target)
                if f.suffix == ".glsl":
                    shutil.copy2(f, dst / (f.name + ".orig"))
        for lic in eff.license_files:
            shutil.copy2(lic, dst / lic.name)
        done.append(dst)
        pending.extend(eff.companions())
    return done


def remove_files(effect: Effect) -> None:
    """Delete an installed effect directory (companions are kept because
    other effects may share them)."""
    d = installed_dir(effect)
    if d.exists() and install_root().resolve() in d.resolve().parents:
        shutil.rmtree(d)
        parent = d.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


# --------------------------------------------------------------------------- config integration


def include_entry(effect: Effect) -> str:
    """Include path as written in the main config (relative to its dir)."""
    target = installed_dir(effect) / "effect.toml"
    try:
        return str(target.relative_to(cfgmod.config_dir()))
    except ValueError:
        return str(target)


def is_included(cfg: cfgmod.Config, effect: Effect) -> bool:
    real = (installed_dir(effect) / "effect.toml").resolve()
    return any(f.real_path == real for f in cfg.includes())


def add_include(cfg: cfgmod.Config, effect: Effect) -> None:
    if is_included(cfg, effect):
        return
    files = list(cfg.main.get(("include", "files"), []) or [])
    files.append(include_entry(effect))
    cfg.main.set(("include", "files"), _array(files))
    cfg.resolve_includes()


def _array(items: list):
    """A TOML array that goes multi-line once it holds several paths."""
    arr = tomlkit.array()
    arr.extend(items)
    if len(items) > 1:
        arr.multiline(True)
    return arr


def remove_include(cfg: cfgmod.Config, effect: Effect) -> None:
    real = (installed_dir(effect) / "effect.toml").resolve()
    for key in (("include", "files"), ("include", "optional", "files")):
        entries = cfg.main.get(key)
        if not entries:
            continue
        keep = []
        for e in entries:
            p = Path(os.path.expanduser(e))
            p = p if p.is_absolute() else cfg.dir / p
            if p.resolve() != real:
                keep.append(e)
        if keep != entries:
            if keep:
                cfg.main.set(key, _array(keep))
            else:
                cfg.main.delete(key, prune=True)
    cfg.resolve_includes()


def references(cfg: cfgmod.Config, names: set[str]) -> list[tuple]:
    """Paths in the main config that select one of ``names``."""
    out: list[tuple] = []
    m = cfg.main
    for slot in SLOT_KINDS:
        if m.get(("effects", slot)) in names:
            out.append(("effects", slot))
    for event, table in (m.get(("animation",)) or {}).items():
        if isinstance(table, dict) and table.get("effect") in names:
            out.append(("animation", event, "effect"))
    for i, rule in enumerate(m.get(("window_rule",)) or []):
        for key in ("border_effect", "window_effect"):
            if rule.get(key) in names:
                out.append(("window_rule", i, key))
    for name, out_cfg in (m.get(("output",)) or {}).items():
        if isinstance(out_cfg, dict) and out_cfg.get("screen_effect") in names:
            out.append(("output", name, "screen_effect"))
    for pool, pcfg in (m.get(("effects", "pool")) or {}).items():
        if any(c in names for c in pcfg.get("choose", [])):
            out.append(("effects", "pool", pool, "choose"))
    return out


def clear_references(cfg: cfgmod.Config, names: set[str]) -> int:
    refs = references(cfg, names)
    for path in reversed(refs):
        if path[-1] == "choose":
            keep = [c for c in cfg.main.get(path) if c not in names]
            cfg.main.set(path, keep)
        else:
            cfg.main.delete(path, prune=True)
    return len(refs)


def _flatten(data: dict, prefix: tuple = ()) -> list[tuple[tuple, object]]:
    out = []
    for k, v in data.items():
        if isinstance(v, dict):
            out.extend(_flatten(v, prefix + (k,)))
        else:
            out.append((prefix + (k,), v))
    return out


def activation_changes(effect: Effect) -> list[tuple[tuple, object]]:
    return _flatten(effect.activation)


def apply_activation(cfg: cfgmod.Config, effect: Effect) -> list[tuple]:
    changes = activation_changes(effect)
    for path, value in changes:
        cfg.main.set(path, value)
    return [p for p, _ in changes]


def preset_names(cfg: cfgmod.Config) -> dict[str, str]:
    """All preset names known to the configuration → kind."""
    out: dict[str, str] = {}
    for f in cfg.files:
        for name, p in (f.get(("effects", "preset")) or {}).items():
            out[name] = p.get("kind", "")
    return out


def pool_names(cfg: cfgmod.Config) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in cfg.files:
        for name, p in (f.get(("effects", "pool")) or {}).items():
            out[name] = p.get("kind", "")
    return out


def suggestions_for(cfg: cfgmod.Config, kind: str | None, *, pools: bool = True, off: bool = False) -> list[str]:
    names = [n for n, k in preset_names(cfg).items() if kind is None or k == kind]
    if pools:
        names += [n for n, k in pool_names(cfg).items() if kind is None or k == kind]
    if off:
        names.append("off")
    return sorted(set(names), key=str.lower)


def kind_for_option(schema_path: str) -> tuple[str | None, bool, bool]:
    """Which preset kind an option of format ``effect`` selects.

    Returns (kind, pools allowed, "off" allowed).
    """
    if schema_path.startswith("animation."):
        return "animation", False, False
    if schema_path.endswith(".overlay"):
        return "window", False, False
    if schema_path.endswith("border_effect"):
        return "border", True, True
    if schema_path.endswith("window_effect"):
        return "window", True, True
    if schema_path.endswith("screen_effect"):
        return "screen", True, True
    if schema_path.startswith("effects.pool"):
        return None, False, False
    for slot in SLOT_KINDS:
        if schema_path == f"effects.{slot}":
            return slot, True, False
    return None, True, False


# --------------------------------------------------------------------------- GLSL constants


@dataclass
class ShaderConst:
    name: str
    kind: str  # "define" or "const"
    type: str  # float, int, bool, vec2, vec3, vec4
    values: list
    line: int
    start: int  # value span within the line
    end: int
    comment: str = ""

    @property
    def is_color(self) -> bool:
        return self.type in ("vec3", "vec4") and bool(re.search(r"col|tint|hue|rgb", self.name, re.I)) \
            and all(0.0 <= v <= 1.0 for v in self.values)


_NUM = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
_DEFINE_RE = re.compile(rf"^#define\s+(\w+)\s+(?P<v>{_NUM})\s*(?://\s*(?P<c>.*))?$")
_CONST_RE = re.compile(
    rf"^const\s+(?P<t>float|int|bool|vec2|vec3|vec4)\s+(?P<n>\w+)\s*=\s*(?P<v>[^;]+?)\s*;\s*(?://\s*(?P<c>.*))?$"
)
_VEC_RE = re.compile(rf"^vec([234])\(\s*({_NUM}(?:\s*,\s*{_NUM})*)\s*\)$")


def parse_constants(src: str) -> list[ShaderConst]:
    """Top-level numeric ``#define`` and ``const`` declarations."""
    out: list[ShaderConst] = []
    in_block = False
    for i, line in enumerate(src.splitlines()):
        stripped = line
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        if line.lstrip().startswith("/*") and "*/" not in line:
            in_block = True
            continue
        if line[:1].isspace():
            continue  # locals inside functions
        if m := _DEFINE_RE.match(stripped):
            raw = m.group("v")
            typ = "float" if re.search(r"[.eE]", raw) else "int"
            val = float(raw) if typ == "float" else int(raw)
            out.append(ShaderConst(m.group(1), "define", typ, [val], i, m.start("v"), m.end("v"), (m.group("c") or "").strip()))
            continue
        if m := _CONST_RE.match(stripped):
            typ, raw = m.group("t"), m.group("v").strip()
            values: list | None = None
            if typ == "bool" and raw in ("true", "false"):
                values = [raw == "true"]
            elif typ in ("float", "int") and re.fullmatch(_NUM, raw):
                values = [float(raw) if typ == "float" else int(float(raw))]
            elif typ.startswith("vec") and (vm := _VEC_RE.match(raw)):
                n = int(typ[-1])
                comps = [float(x) for x in re.split(r"\s*,\s*", vm.group(2).strip())]
                if len(comps) == 1:
                    comps *= n
                if len(comps) == n:
                    values = comps
            if values is not None:
                out.append(ShaderConst(m.group("n"), "const", typ, values, i, m.start("v"), m.end("v"), (m.group("c") or "").strip()))
    return out


def format_float(v: float) -> str:
    s = f"{v:.6g}"
    if not re.search(r"[.eEn]", s):  # nan/inf contain n
        s += ".0"
    return s


def format_value(const: ShaderConst, values: list) -> str:
    if const.type == "bool":
        return "true" if values[0] else "false"
    if const.type == "int":
        return str(int(values[0]))
    if const.type == "float":
        return format_float(float(values[0]))
    return f"{const.type}({', '.join(format_float(float(v)) for v in values)})"


def set_constant(src: str, const: ShaderConst, values: list) -> str:
    lines = src.splitlines(keepends=True)
    line = lines[const.line]
    lines[const.line] = line[: const.start] + format_value(const, values) + line[const.end:]
    return "".join(lines)


def sync_ring_padding(src: str, padding: int) -> str:
    """Keep ``#define ring_padding`` equal to the preset's ``padding``
    (the collection requires both to match)."""
    for c in parse_constants(src):
        if c.name == "ring_padding" and c.kind == "define":
            return set_constant(src, c, [float(padding)])
    return src
