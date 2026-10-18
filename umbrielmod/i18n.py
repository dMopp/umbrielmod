"""Translations from gettext ``.po`` files, read directly (no compile step).

Source strings in the code are English and wrapped in ``_()``. Catalogues are
looked up in this order, later ones overriding earlier ones entry by entry:

1. ``umbrielmod/locale/<lang>.po`` shipped with UmbrielMod
2. ``$XDG_DATA_HOME/umbrielmod/locale/<lang>.po`` (default ``~/.local/share``)
3. every directory in ``$UMBRIELMOD_LOCALE_DIR`` (``:``-separated)

So a new language is added by dropping ``<lang>.po`` into one of these
directories, and an existing one can be fixed without touching the install.
The language comes from the in-app setting, ``$UMBRIELMOD_LANG``, or the
usual ``LANGUAGE``/``LC_ALL``/``LC_MESSAGES``/``LANG`` variables.

Maintainer commands::

    python -m umbrielmod.i18n extract   # refresh locale/umbrielmod.pot from the sources
    python -m umbrielmod.i18n update    # merge the template into every shipped .po
    python -m umbrielmod.i18n stats     # show translation coverage
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
LOCALE_DIR = PACKAGE_DIR / "locale"
SOURCE_LANG = "en"

_catalog: dict[str, str] = {}
_language = SOURCE_LANG


def _(message: str) -> str:
    """Translate ``message`` (English source text)."""
    return _catalog.get(message) or message


def N_(message: str) -> str:
    """Mark a string for extraction without translating it yet."""
    return message


# --------------------------------------------------------------------------- .po parsing


def _unquote(s: str) -> str:
    s = s.strip()
    if not (s.startswith('"') and s.endswith('"')):
        raise ValueError(s)
    return json.loads(s) if "\\" in s else s[1:-1]


def parse_po(text: str) -> dict[str, str]:
    """Minimal PO reader: msgid/msgstr (multi-line), skips fuzzy and plural entries."""
    entries: dict[str, str] = {}
    msgid = msgstr = None
    target = None
    fuzzy = False

    def flush():
        nonlocal msgid, msgstr, fuzzy
        if msgid and msgstr and not fuzzy:
            entries[msgid] = msgstr
        msgid = msgstr = None
        fuzzy = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            target = None
            continue
        if line.startswith("#,") and "fuzzy" in line:
            flush()
            fuzzy = True
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgid "):
            if msgid is not None:
                f = fuzzy
                flush()
                fuzzy = f
            msgid, target = _unquote(line[6:]), "id"
        elif line.startswith("msgstr "):
            msgstr, target = _unquote(line[7:]), "str"
        elif line.startswith('"') and target:
            if target == "id":
                msgid = (msgid or "") + _unquote(line)
            else:
                msgstr = (msgstr or "") + _unquote(line)
        else:  # msgctxt, msgid_plural, msgstr[n]: unsupported, skip entry
            target = None
            msgstr = None
    flush()
    return entries


def _po_quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _po_entry(msgid: str, msgstr: str, refs: list[str] | None = None) -> str:
    lines = []
    for ref in refs or []:
        lines.append(f"#: {ref}")
    lines.append(f"msgid {_po_quote(msgid)}")
    lines.append(f"msgstr {_po_quote(msgstr)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- lookup


def search_dirs() -> list[Path]:
    dirs = [LOCALE_DIR]
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    dirs.append(data / "umbrielmod" / "locale")
    for d in os.environ.get("UMBRIELMOD_LOCALE_DIR", "").split(":"):
        if d:
            dirs.append(Path(d).expanduser())
    return dirs


def _po_header_value(text: str, key: str) -> str:
    m = re.search(rf'"{key}:\s*([^"\\]+)', text)
    return m.group(1).strip() if m else ""


def available_languages() -> dict[str, str]:
    """language code → display name (from the PO header ``Language-Team``)."""
    langs = {SOURCE_LANG: "English"}
    for d in search_dirs():
        for po in sorted(d.glob("*.po")) if d.is_dir() else []:
            try:
                text = po.read_text()
            except OSError:
                continue
            langs[po.stem] = _po_header_value(text, "Language-Team").split("<")[0].strip() or po.stem
    return langs


def system_language() -> str:
    for var in ("UMBRIELMOD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX"):
            return value.split(":")[0].split(".")[0]
    return SOURCE_LANG


def _candidates(lang: str) -> list[str]:
    lang = lang.replace("-", "_")
    base = lang.split("_")[0]
    return [lang, base] if base != lang else [lang]


def load(lang: str | None = None) -> str:
    """Activate a language; returns the code actually used."""
    global _catalog, _language
    lang = lang or system_language()
    catalog: dict[str, str] = {}
    used = SOURCE_LANG
    for code in _candidates(lang):
        if code == SOURCE_LANG:
            break
        found = False
        for d in search_dirs():
            po = d / f"{code}.po"
            if po.is_file():
                try:
                    catalog.update(parse_po(po.read_text()))
                    found = True
                except (OSError, ValueError):
                    continue
        if found:
            used = code
            break
    _catalog, _language = catalog, used
    return used


def current_language() -> str:
    return _language


# --------------------------------------------------------------------------- maintainer tools


def _extract() -> dict[str, list[str]]:
    """msgid → source references for every ``_("…")``/``N_("…")`` call."""
    found: dict[str, list[str]] = {}
    root = PACKAGE_DIR.parent
    for py in sorted(PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, []).append(f"{py.relative_to(root)}:{node.lineno}")
    return found


POT_HEADER = '''# UmbrielMod translation template.
# Copy to <lang>.po (e.g. fr.po), fill in msgstr and drop it into
# ~/.local/share/umbrielmod/locale/ – or send it upstream.
msgid ""
msgstr ""
"Project-Id-Version: UmbrielMod\\n"
"Language-Team: LANGUAGE NAME\\n"
"Language: \\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
'''


def _docs_strings() -> dict[str, list[str]]:
    """Descriptions taken from Umbriel's documentation (data/docs.json)."""
    try:
        data = json.loads((PACKAGE_DIR / "data" / "docs.json").read_text())
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for path, info in sorted(data.get("options", {}).items()):
        if info.get("desc") and not info.get("inherited"):
            out.setdefault(info["desc"], []).append(f"umbriel-docs:{path}")
    for table, desc in sorted(data.get("tables", {}).items()):
        if desc and not table.startswith("<"):
            out.setdefault(desc, []).append(f"umbriel-docs:[{table}]")
    for page, info in sorted(data.get("pages", {}).items()):
        if info.get("intro"):
            out.setdefault(info["intro"], []).append(f"umbriel-docs:{page}")
    return out


def write_pot() -> Path:
    found = _extract()
    for msgid, refs in _docs_strings().items():
        found.setdefault(msgid, []).extend(refs)
    out = LOCALE_DIR / "umbrielmod.pot"
    LOCALE_DIR.mkdir(exist_ok=True)
    body = "\n\n".join(_po_entry(m, "", refs) for m, refs in found.items())
    out.write_text(POT_HEADER + "\n" + body + "\n")
    return out


def update_po(po: Path) -> tuple[int, int]:
    """Merge current msgids (UI and Umbriel docs) into ``po``, keeping existing
    translations. Returns (translated UI strings, total UI strings)."""
    found = _extract()
    ui = set(found)
    for msgid, refs in _docs_strings().items():
        found.setdefault(msgid, []).extend(refs)
    text = po.read_text()
    old = parse_po(text)
    header_end = text.find("\n\n")
    header = text[: header_end if header_end > 0 else len(text)]
    body = "\n\n".join(_po_entry(m, old.get(m, ""), refs) for m, refs in found.items())
    obsolete = [m for m in old if m not in found]
    if obsolete:
        body += "\n\n" + "\n\n".join("#~ msgid " + _po_quote(m) + "\n#~ msgstr " + _po_quote(old[m]) for m in obsolete)
    po.write_text(header + "\n\n" + body + "\n")
    return sum(1 for m in ui if old.get(m)), len(ui)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "stats"
    if cmd == "extract":
        print(write_pot())
    elif cmd in ("update", "stats"):
        found = _extract()
        for po in sorted(LOCALE_DIR.glob("*.po")):
            if cmd == "update":
                done, total = update_po(po)
            else:
                cat = parse_po(po.read_text())
                done, total = sum(1 for m in found if cat.get(m)), len(found)
            missing = total - done
            docs = _docs_strings()
            cat = parse_po(po.read_text())
            ddone = sum(1 for m in docs if cat.get(m))
            print(f"{po.name}: {done}/{total} interface strings" + (f", {missing} missing" if missing else "")
                  + f"; {ddone}/{len(docs)} Umbriel doc descriptions")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
