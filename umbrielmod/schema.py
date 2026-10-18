"""Access to Umbriel's configuration schema (`umbriel config schema --json`).

Schema paths use `<name>` for map keys and `[]` for array-of-tables entries,
e.g. `output.<name>.mode` or `window_rule[].match.app_id`. Config paths in this
project are tuples such as ("output", "HDMI-A-1", "mode") or
("window_rule", 3, "match", "app_id").
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import umbriel

CONTAINER_TYPES = {"table", "map", "array_of_tables"}

Path_ = tuple  # config path: tuple[str | int, ...]


@dataclass
class Option:
    path: str
    type: str
    default: object = None
    has_default: bool = False
    min: float | None = None
    max: float | None = None
    values: list[str] = field(default_factory=list)
    format: str | None = None

    @property
    def key(self) -> str:
        return self.path.rsplit(".", 1)[-1].removesuffix("[]")

    @property
    def is_container(self) -> bool:
        return self.type in CONTAINER_TYPES


class Schema:
    def __init__(self, data: dict):
        self.version = data.get("version", "")
        self.revision = data.get("revision", "")
        self.options: dict[str, Option] = {}
        for raw in data["options"]:
            self.options[raw["path"]] = Option(
                path=raw["path"],
                type=raw["type"],
                default=raw.get("default"),
                has_default="default" in raw,
                min=raw.get("min"),
                max=raw.get("max"),
                values=list(raw.get("values", [])),
                format=raw.get("format"),
            )

    # ----------------------------------------------------------------- loading

    @classmethod
    def load(cls) -> "Schema":
        """Load the schema from the umbriel binary, cached per revision."""
        cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "umbrielmod"
        try:
            ver = umbriel.version().replace(" ", "_").replace("/", "_")
        except umbriel.UmbrielError:
            ver = ""
        cache = cache_dir / f"schema-{ver}.json" if ver else None
        if cache and cache.exists():
            try:
                return cls(json.loads(cache.read_text()))
            except (ValueError, KeyError):
                pass
        data = umbriel.schema_json()
        if cache:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
        return cls(data)

    # ----------------------------------------------------------------- lookups

    def schema_path(self, path: Path_) -> str | None:
        """Translate a config path tuple into its schema path."""
        cur = ""
        for seg in path:
            if isinstance(seg, int):
                cur += "[]"
                if cur not in self.options and not self._has_prefix(cur + "."):
                    return None
                continue
            literal = f"{cur}.{seg}" if cur else seg
            if literal in self.options:
                cur = literal
                continue
            wildcard = f"{cur}.<name>" if cur else "<name>"
            if wildcard in self.options:
                cur = wildcard
                continue
            # array-of-tables are listed without [] for the container itself
            if f"{literal}[]" in self.options or self._has_prefix(f"{literal}[]."):
                cur = literal
                continue
            return None
        return cur

    def lookup(self, path: Path_) -> Option | None:
        sp = self.schema_path(path)
        return self.options.get(sp) if sp else None

    def _has_prefix(self, prefix: str) -> bool:
        return any(p.startswith(prefix) for p in self.options)

    def children(self, schema_prefix: str) -> list[Option]:
        """Direct children of a schema path (``""`` for the top level)."""
        pre = schema_prefix + "." if schema_prefix else ""
        return sorted(
            (o for p, o in self.options.items() if p.startswith(pre) and "." not in p[len(pre):]),
            key=lambda o: o.path,
        )

    def leaves(self, schema_prefix: str, *, stop_at_collections: bool = True) -> list[Option]:
        """All leaf options below a prefix.

        With ``stop_at_collections`` options below maps (``<name>``) and
        arrays of tables (``[]``) are skipped; those get dedicated editors.
        """
        out = []
        pre = schema_prefix + "." if schema_prefix else ""
        for p, opt in self.options.items():
            if not p.startswith(pre) or opt.is_container:
                continue
            rest = p[len(pre):]
            if stop_at_collections and ("<name>" in rest or "[]" in rest):
                continue
            out.append(opt)
        return sorted(out, key=lambda o: o.path)

    def sections(self) -> list[str]:
        return sorted({p.split(".", 1)[0].removesuffix("[]") for p in self.options})

    def collections(self, schema_prefix: str) -> list[Option]:
        """Maps and arrays of tables directly or indirectly below a prefix
        (but not nested inside another collection)."""
        pre = schema_prefix + "." if schema_prefix else ""
        out = []
        for p, opt in self.options.items():
            if opt.type not in ("map", "array_of_tables") or not p.startswith(pre):
                continue
            rest = p[len(pre):]
            if "<name>" in rest or "[]" in rest:
                continue
            out.append(opt)
        return sorted(out, key=lambda o: o.path)


def humanize(key: str) -> str:
    text = key.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:]
