"""Option descriptions extracted from the Umbriel repository.

The schema (`umbriel config schema --json`) says which options exist, but has
no prose. Umbriel's user documentation (`docs/user/*.md`) documents options in
key tables preceded by TOML examples; this module maps those rows onto schema
paths. A bundled ``data/docs.json`` ships with UmbrielMod; ``refresh()`` builds
one for the exact revision of the installed compositor.

Run ``python -m umbrielmod.docs <umbriel-repo> [out.json]`` to regenerate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import paths

DOCS_SITE = "https://docs.noctalia.dev/umbriel"
REPO_URL = "https://github.com/noctalia-dev/umbriel"
BUNDLED = Path(__file__).parent / "data" / "docs.json"


def action_url(group: str) -> str:
    """Docs section for an action group from `umbriel msg --help`."""
    return f"{DOCS_SITE}/actions/?section={_anchor(group)}#{_anchor(group)}"


def section_url(page: str, heading: str) -> str:
    a = _anchor(heading)
    return f"{DOCS_SITE}/{page}/?section={a}#{a}"


def cache_dir() -> Path:
    return paths.cache_home() / "umbrielmod"


# --------------------------------------------------------------------------- extraction

_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9_.\"-]+)\s*=")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _split_key_path(text: str) -> list[str]:
    """Split a TOML dotted key, honouring quotes."""
    parts, cur, quote = [], "", False
    for ch in text:
        if ch == '"':
            quote = not quote
        elif ch == "." and not quote:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def _anchor(heading: str) -> str:
    """GitHub-style slug as used by the docs site ("Move & size" → "move--size")."""
    slug = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s", "-", slug)


def _clean(cell: str) -> str:
    text = _LINK_RE.sub(r"\1", cell.strip())
    return text.replace("\\|", "|")


def _cells(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _schema_regex(schema_path: str) -> re.Pattern:
    parts = []
    for seg in schema_path.split("."):
        if seg == "<name>":
            parts.append(r"[^.]+")
        else:
            parts.append(re.escape(seg.removesuffix("[]")))
    return re.compile("^" + r"\.".join(parts) + "$")


class _Matcher:
    def __init__(self, schema_paths: list[str]):
        self.by_key: dict[str, list[str]] = {}
        self.parent_re: dict[str, re.Pattern] = {}
        for p in schema_paths:
            parent, _, last = p.rpartition(".")
            last = last.removesuffix("[]")
            self.by_key.setdefault(last, []).append(p)
            self.parent_re[p] = _schema_regex(parent) if parent else re.compile("^$")

    def match(self, key: str, contexts: list[str]) -> list[str]:
        segs = _split_key_path(key.strip("`").split(" ")[0].split("=")[0])
        if not segs:
            return []
        last = segs[-1].removesuffix("[]")
        prefix = ".".join(segs[:-1])
        candidates = self.by_key.get(last, [])
        if not candidates:
            return []
        scoped = []
        for ctx in contexts:
            full = ".".join(x for x in (ctx, prefix) if x)
            scoped = [c for c in candidates if self.parent_re[c].match(full)]
            if scoped:
                return scoped
        if prefix:
            scoped = [c for c in candidates if c.endswith("." + prefix.replace(".", ".") + "." + last) or self.parent_re[c].pattern.endswith(re.escape(prefix) + "$")]
            if scoped:
                return scoped
        return candidates if len(candidates) == 1 else []


# Markdown file → page slug on docs.noctalia.dev where they differ
SITE_PAGES = {"scratchpad": "scratchpads"}

PAGE_SECTIONS = {
    "outputs": ["output._"],
    "window-rules": ["window_rule"],
    "layer-rules": ["layer_rule"],
    "workspaces": ["workspace", "workspaces"],
    "workspaces-overview": ["overview", "workspaces"],
    "security": ["security_context_rule"],
    "configuration": ["general", "include", "events", "screencast", "environment", "drm"],
    "input": ["input"],
}


def _page_contexts(page: str) -> list[str]:
    return PAGE_SECTIONS.get(page, [page.replace("-", "_")])


def extract(repo: Path, schema_paths: list[str]) -> dict:
    matcher = _Matcher([p for p in schema_paths])
    options: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    tables: dict[str, str] = {}
    docs = sorted((repo / "docs" / "user").glob("*.md"))
    for md in docs:
        page = md.stem
        lines = md.read_text(encoding="utf-8").splitlines()
        heading, anchor = page, ""
        contexts: list[str] = []
        in_code = False
        code_lang = ""
        table_header: list[str] | None = None
        intro, intro_done = "", False
        for i, line in enumerate(lines):
            if line.startswith("```"):
                if not in_code:
                    in_code, code_lang = True, line[3:].strip()
                    if code_lang == "toml":
                        contexts = []
                else:
                    in_code = False
                continue
            if in_code:
                if code_lang == "toml":
                    raw = line.lstrip("# ").rstrip() if line.lstrip().startswith("#") else line
                    if m := _HEADER_RE.match(raw):
                        ctx = ".".join(_split_key_path(m.group(1)))
                        if ctx not in contexts:
                            contexts.insert(0, ctx)
                continue
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
                anchor = _anchor(heading)
                table_header = None
                # a new heading starts a new context; headings may name a table
                contexts = []
                if m := re.search(r"`?\[\[?([\w.<>\"-]+)\]\]?`?", heading):
                    contexts = [".".join(_split_key_path(m.group(1)))]
                continue
            if not intro_done and page not in pages:
                if line.strip() and not line.startswith(("|", "!", "<")):
                    intro = f"{intro} {_clean(line)}".strip()
                elif intro:
                    intro_done = True
            if line.startswith("|"):
                cells = _cells(line)
                if table_header is None:
                    table_header = [c.lower() for c in cells]
                    continue
                if set(line.replace("|", "").strip()) <= set("-: "):
                    continue
                if m := re.fullmatch(r"`\[\[?([\w.<>\"-]+)\]\]?`", cells[0]):
                    tables.setdefault(".".join(_split_key_path(m.group(1))), _clean(cells[-1]))
                    continue
                if not cells[0].startswith("`") or table_header[0] in ("action", "event", "value", "mode"):
                    continue
                desc = _clean(cells[-1])
                default = ""
                if "default" in table_header:
                    default = _clean(cells[table_header.index("default")])
                for key in re.findall(r"`([^`]+)`", cells[0]) or [cells[0]]:
                    for path in matcher.match(key, contexts + _page_contexts(page)):
                        entry = options.get(path)
                        if entry and entry.get("scoped"):
                            continue
                        options[path] = {
                            "desc": desc,
                            "default_text": default,
                            "doc": f"{page}/#{anchor}" if anchor else f"{page}/",
                            "scoped": bool(contexts),
                        }
            else:
                table_header = None
        pages[page] = {"title": _title(lines) or page, "intro": intro}
    _from_example(repo / "examples" / "config.toml", matcher, options)
    _inherit(schema_paths, options)
    sections = {md.stem: _sections(md.read_text(encoding="utf-8").splitlines()) for md in docs}
    _deep_links(schema_paths, options, sections)
    for v in options.values():
        v.pop("scoped", None)
    return {"options": options, "pages": pages, "tables": tables}


def _sections(lines: list[str]) -> list[tuple[str, str, str]]:
    """(anchor, heading, body) for every heading outside code fences."""
    out: list[list] = []
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("#"):
            if line.startswith("# "):  # page title: too broad to link to
                out.append(["", "", ""])
                continue
            heading = line.lstrip("#").strip()
            out.append([_anchor(heading), heading, ""])
            continue
        if out:
            out[-1][2] += line + "\n"
    return [tuple(x) for x in out]


def _pages_for(schema_path: str) -> list[str]:
    section = schema_path.split(".", 1)[0].removesuffix("[]")
    pages = [p for p, secs in PAGE_SECTIONS.items() if section in secs or f"{section}._" in secs]
    pages.append(section.replace("_", "-") + ("s" if section.endswith("rule") else ""))
    pages.append(section.replace("_", "-"))
    return list(dict.fromkeys(pages))


_FILLER = {"and", "or", "the", "a", "an", "of"}


def _best_anchor(secs: list[tuple[str, str, str]], key: str, table_anchor: str, siblings: frozenset[str] = frozenset()) -> str:
    """Most specific heading for ``key`` (document order):

    1. a heading named after the key (``tearing`` → ``#tearing``)
    2. a heading containing the key as a word whose text uses it as code, or
       as a plain word when the heading's other words are sibling keys
       (``Position and scale`` → ``at scale 1.25``)
    3. the section holding the key table
    4. without a table: the first section that uses the key
    """
    slug = key.replace("_", "-")

    def mentions(body: str) -> bool:
        return f"`{key}`" in body or f"\n{key} =" in body or f"`{key} =" in body or f"{key} = " in body

    def says(body: str) -> bool:
        return re.search(rf"\b{re.escape(key.replace('_', ' '))}\b", body, re.I) is not None

    secs = [s for s in secs if s[0]]
    for anchor, _h, _b in secs:
        if anchor == slug or "".join(w[0] for w in anchor.split("-") if w) == slug:  # vrr → variable-refresh-rate
            return anchor
    words = set(slug.split("-"))
    for anchor, _h, body in secs:
        if words <= set(anchor.split("-")) and mentions(body):
            return anchor
    allowed = words | {w for s in siblings for w in s.split("_")} | _FILLER
    for anchor, _h, body in secs:
        if words <= set(anchor.split("-")) <= allowed and says(body):
            return anchor
    return table_anchor or next((a for a, _h, b in secs if mentions(b)), "")


def _deep_links(schema_paths: list[str], options: dict, sections: dict) -> None:
    children: dict[str, set[str]] = {}
    for path in schema_paths:
        parent, _, last = path.rpartition(".")
        if parent:  # top-level sections are not related keys
            children.setdefault(parent, set()).add(last.removesuffix("[]"))
    for path in schema_paths:
        key = path.rsplit(".", 1)[-1].removesuffix("[]")
        if key == "<name>":
            continue
        entry = options.get(path)
        if entry and entry.get("doc"):
            page, _, anchor = entry["doc"].partition("/#")
            page = page.rstrip("/")
        else:
            page = next((p for p in _pages_for(path) if p in sections), "")
            anchor = ""
            if not page:
                continue
        secs = sections.get(page, [])
        siblings = frozenset(children.get(path.rpartition(".")[0], set()) - {key})
        best = _best_anchor(secs, key, anchor, siblings) if secs else anchor
        site = SITE_PAGES.get(page, page)
        doc = f"{site}/?section={best}#{best}" if best else f"{site}/"
        if entry:
            entry["doc"] = doc
        else:
            options[path] = {"desc": "", "default_text": "", "doc": doc}


def _from_example(path: Path, matcher: "_Matcher", options: dict) -> None:
    """Use the comment block above a (commented-out) key in the example config."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    contexts: list[str] = []
    comment: list[str] = []
    for line in lines:
        raw = line.strip()
        body = raw.lstrip("#").strip()
        if m := _HEADER_RE.match(body):
            contexts = [".".join(_split_key_path(m.group(1)))]
            comment = []
            continue
        if (m := _ASSIGN_RE.match(body)) and contexts:
            if comment:
                for path in matcher.match(m.group(1), contexts):
                    options.setdefault(path, {"desc": " ".join(comment), "default_text": "", "doc": ""})
            continue
        if raw.startswith("#") and body and not body.startswith(("http", "=", "-")) and set(body) != {"="}:
            comment.append(body)
        else:
            comment = []


def _inherit(schema_paths: list[str], options: dict) -> None:
    """Undocumented options reuse the description of a documented option with
    the same key in the same section and at the same depth (e.g. a key of
    ``workspace[].layout.tabs`` documented once under ``layout.tabs``)."""
    documented = list(options)
    for path in schema_paths:
        if path in options:
            continue
        segs = path.split(".")
        best, best_len = None, 0
        for other in documented:
            osegs = other.split(".")
            if osegs[-1] != segs[-1] or len(osegs) != len(segs) or osegs[0] != segs[0]:
                continue
            common = 0
            for a, b in zip(segs, osegs):
                if a != b:
                    break
                common += 1
            if common > best_len:
                best, best_len = other, common
        if best:
            src = options[best]
            options[path] = {"desc": src["desc"], "default_text": "", "doc": src["doc"], "inherited": best}


def _title(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# --------------------------------------------------------------------------- runtime


class Docs:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.revision: str = data.get("revision", "")
        self.options: dict[str, dict] = data.get("options", {})
        self.pages: dict[str, dict] = data.get("pages", {})
        self.tables: dict[str, str] = data.get("tables", {})

    def describe(self, schema_path: str) -> str:
        """Description from Umbriel's docs, translated when a catalogue has it."""
        from .i18n import _

        desc = self.options.get(schema_path, {}).get("desc", "")
        return _(desc) if desc else ""

    def table(self, table_path: str) -> str:
        from .i18n import _

        desc = self.tables.get(table_path, "")
        return _(desc) if desc else ""

    def intro(self, page: str) -> str:
        from .i18n import _

        intro = self.pages.get(page, {}).get("intro", "")
        return _(intro) if intro else ""

    def url(self, schema_path: str) -> str | None:
        doc = self.options.get(schema_path, {}).get("doc")
        return f"{DOCS_SITE}/{doc}" if doc else None

    def page_url(self, schema_path: str) -> str:
        """Documentation page for a whole section (fallback for prose-only options)."""
        section = schema_path.split(".", 1)[0].removesuffix("[]")
        for page, sections in PAGE_SECTIONS.items():
            if section in sections:
                return f"{DOCS_SITE}/{page}/"
        page = section.replace("_", "-")
        if page in self.pages:
            return f"{DOCS_SITE}/{SITE_PAGES.get(page, page)}/"
        if section in ("hot_corners",):
            return f"{DOCS_SITE}/workspaces-overview/"
        if section == "colors":
            return f"{DOCS_SITE}/appearance/"
        return f"{DOCS_SITE}/"

    @classmethod
    def load(cls, revision: str = "") -> "Docs":
        candidates = [cache_dir() / f"docs-{_revision_sha(revision) or 'latest'}.json", BUNDLED]
        for path in candidates:
            try:
                return cls(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return cls()


def _revision_sha(revision: str) -> str:
    """The commit of a revision such as ``0.1.0-gabc123``; "" when unusable."""
    sha = revision.split("-g")[-1] if "-g" in revision else revision
    return sha if re.fullmatch(r"[0-9A-Za-z][\w.+-]*", sha) else ""


def refresh(revision: str, schema_paths: list[str]) -> tuple[bool, str]:
    """Fetch Umbriel's docs at ``revision`` and rebuild the description cache."""
    repo = cache_dir() / "umbriel-src"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    sha = _revision_sha(revision)
    try:
        if not (repo / ".git").exists():
            repo.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--filter=blob:none", "--no-checkout", REPO_URL, str(repo)]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
            if proc.returncode != 0:
                return False, proc.stderr.strip()
        else:
            subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], capture_output=True, env=env, timeout=300)
        target = sha or "origin/HEAD"
        proc = subprocess.run(
            ["git", "-C", str(repo), "checkout", "-q", "--force", target, "--", "docs/user"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300,
        )
        if proc.returncode != 0:
            return False, proc.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    try:
        data = extract(repo, schema_paths)
        data["revision"] = sha
        out = cache_dir() / f"docs-{sha or 'latest'}.json"
        out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError) as exc:
        return False, str(exc)
    from .i18n import _

    return True, _("{count} of {total} options described").format(count=len(data["options"]), total=len(schema_paths))


def main(argv: list[str]) -> int:
    from .schema import Schema

    if len(argv) < 2:
        print(__doc__)
        return 2
    repo = Path(argv[1])
    out = Path(argv[2]) if len(argv) > 2 else BUNDLED
    schema = Schema.load()
    leaf_paths = [p for p, o in schema.options.items() if not o.is_container]
    data = extract(repo, list(schema.options))
    rev = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    data["revision"] = rev
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    covered = [p for p in leaf_paths if data["options"].get(p, {}).get("desc")]
    linked = [p for p in leaf_paths if "#" in data["options"].get(p, {}).get("doc", "")]
    print(f"{out}: {len(covered)}/{len(leaf_paths)} leaf options described, "
          f"{len(linked)}/{len(leaf_paths)} with a section link (revision {rev})")
    if "-v" in argv:
        for p in leaf_paths:
            if p not in covered:
                print("  no description:", p, "->", data["options"].get(p, {}).get("doc", "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
