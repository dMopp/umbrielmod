"""Comment-preserving access to Umbriel's TOML configuration.

All edits go through tomlkit so comments, ordering and formatting survive
round-trips (including trailing markers such as `# game-hz`). Saving validates
the whole configuration with `umbriel config validate` on a scratch copy of
the config directory before anything on disk is replaced.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

import tomlkit
from tomlkit.container import Container
from tomlkit.items import AoT, InlineTable, Item, Table, Whitespace

from . import paths, umbriel
from .i18n import _

Path_ = tuple  # tuple[str | int, ...]

_MISSING = object()


def config_dir() -> Path:
    return paths.config_home() / "umbriel"


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def packaged_config() -> Path | None:
    """The file Umbriel falls back to without a user configuration: each
    ``$XDG_CONFIG_DIRS/umbriel/config.toml``, then the packaged one."""
    dirs = [Path(d) / "umbriel" for d in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":") if d]
    binary = shutil.which(umbriel.BINARY)
    if binary:
        dirs.append(Path(os.path.realpath(binary)).parent.parent / "share" / "umbriel")
    data_dirs = [d for d in os.environ.get("XDG_DATA_DIRS", "").split(":") if d]
    dirs += [Path(d) / "umbriel" for d in (*data_dirs, "/usr/local/share", "/usr/share")]
    return next((d / "config.toml" for d in dirs if (d / "config.toml").is_file()), None)


def state_dir() -> Path:
    return paths.state_home() / "umbrielmod"


def backup_dir() -> Path:
    return state_dir() / "backups"


# --------------------------------------------------------------------------- helpers


def _body(container) -> Container:
    """The underlying tomlkit Container of a document/table/inline table."""
    if isinstance(container, Container):
        return container
    return container.value


def _last_real_key(container) -> str | None:
    """Key of the last key/value pair, ignoring trailing comments/whitespace and
    sub-tables (so new keys are not appended after a comment that introduces
    the next section)."""
    for key, item in reversed(_body(container).body):
        if key is not None and not isinstance(item, (Table, AoT)):
            return key.key
    return None


def _last_any_key(container) -> str | None:
    for key, _item in reversed(_body(container).body):
        if key is not None:
            return key.key
    return None


def _insert(container, key: str, value) -> None:
    """Insert a new key at a sensible position inside ``container``."""
    if isinstance(container, InlineTable):
        container[key] = value
        return
    is_table = isinstance(value, (Table, AoT))
    anchor = _last_any_key(container) if is_table else _last_real_key(container)
    if anchor is None or isinstance(container, tomlkit.TOMLDocument) and is_table:
        container.add(key, value)
        return
    try:
        _body(container)._insert_after(anchor, key, value)
    except Exception:  # private tomlkit API: fall back to a plain append
        container.add(key, value)


def _copy_trivia(old: Item, new: Item) -> Item:
    if isinstance(old, Item) and isinstance(new, Item) and not isinstance(new, (Table, AoT)):
        new.trivia.comment = old.trivia.comment
        new.trivia.comment_ws = old.trivia.comment_ws
        new.trivia.indent = old.trivia.indent
    return new


def _child(container, seg):
    if isinstance(seg, int):
        if isinstance(container, (AoT, list)) and -len(container) <= seg < len(container):
            return container[seg]
        return _MISSING
    if isinstance(container, (Table, InlineTable, Container, dict)) and seg in container:
        return container[seg]
    return _MISSING


def plain(value):
    """Convert tomlkit items into plain Python values."""
    if hasattr(value, "unwrap"):
        return value.unwrap()
    return value


def toml_literal(value) -> str:
    """Render a Python value as an inline TOML literal."""
    doc = tomlkit.document()
    doc["v"] = value
    return doc.as_string().split("=", 1)[1].strip()


def parse_literal(text: str):
    """Parse an inline TOML literal (raises ValueError on syntax errors)."""
    try:
        return tomlkit.parse(f"v = {text}")["v"].unwrap()
    except Exception as exc:  # tomlkit raises its own exception hierarchy
        raise ValueError(str(exc)) from exc


# --------------------------------------------------------------------------- one TOML file


class TomlFile:
    def __init__(self, path: Path, *, included_by: "TomlFile | None" = None, optional: bool = False,
                 seed: Path | None = None):
        self.path = Path(path)
        self.seed = seed  # starting content while the file does not exist yet
        self.included_by = included_by
        self.optional = optional
        self.exists = False
        self.text = ""
        self.doc = tomlkit.document()
        self.error: str | None = None
        self.reload()

    @property
    def real_path(self) -> Path:
        return Path(os.path.realpath(self.path))

    def reload(self) -> None:
        self.error = None
        try:
            self.text = self.path.read_text(encoding="utf-8")
            self.exists = True
        except FileNotFoundError:
            self.text, self.exists = "", False
            if self.seed is not None:
                try:
                    self.text = self.seed.read_text(encoding="utf-8")
                except (OSError, ValueError):
                    self.text = ""
        except (OSError, ValueError) as exc:  # unreadable, a directory, not UTF-8
            self.text, self.exists = "", True
            self.doc = tomlkit.document()
            self.error = str(exc)
            return
        try:
            self.doc = tomlkit.parse(self.text)
        except Exception as exc:
            self.doc = tomlkit.document()
            self.error = str(exc)

    @property
    def dirty(self) -> bool:
        # A file that could not be parsed has an empty document: it must never
        # count as changed, or saving would replace it with nothing.
        return self.error is None and self.doc.as_string() != self.text

    def as_string(self) -> str:
        return self.text if self.error is not None else self.doc.as_string()

    def set_text(self, text: str) -> None:
        """Replace the whole document (raw editor); raises ValueError."""
        try:
            self.doc = tomlkit.parse(text)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        self.error = None

    # ----------------------------------------------------------------- paths

    def get(self, path: Path_, default=None):
        cur = self.doc
        for seg in path:
            cur = _child(cur, seg)
            if cur is _MISSING:
                return default
        return plain(cur)

    def get_item(self, path: Path_):
        cur = self.doc
        for seg in path:
            cur = _child(cur, seg)
            if cur is _MISSING:
                return None
        return cur

    def has(self, path: Path_) -> bool:
        return self.get_item(path) is not None

    def set(self, path: Path_, value) -> None:
        """Set a value, creating intermediate tables as needed.

        Intermediate tables below an array-of-tables entry or inside an inline
        table are created inline (``match = { ... }``); everything else gets a
        regular ``[a.b]`` table.
        """
        if not path:
            raise ValueError("empty path")
        cur = self.doc
        inline = False
        for i, seg in enumerate(path[:-1]):
            nxt = _child(cur, seg)
            if nxt is _MISSING:
                if isinstance(seg, int):
                    raise KeyError(f"index {seg} out of range in {path[:i]}")
                if inline or isinstance(cur, InlineTable) or isinstance(path[i - 1] if i else None, int):
                    nxt = tomlkit.inline_table()
                else:
                    nxt = tomlkit.table()
                    nxt.trivia.indent = ""
                    # trailing blank line keeps the next [header] visually separated;
                    # later keys are inserted before it (see _last_real_key)
                    nxt.value.body.append((None, Whitespace("\n")))
                _insert(cur, seg, nxt)
                nxt = cur[seg]
            if isinstance(seg, int):
                inline = True  # children of [[x]] entries default to inline tables
            if isinstance(nxt, InlineTable):
                inline = True
            cur = nxt
        key = path[-1]
        if isinstance(key, int):
            cur[key] = value
            return
        new = tomlkit.item(value)
        if isinstance(new, Table):  # dict values are always written inline
            it = tomlkit.inline_table()
            it.update(value)
            new = it
        if key in cur:
            old = cur.item(key) if hasattr(cur, "item") else cur[key]
            if plain(old) == value and type(plain(old)) is type(value):
                return
            cur[key] = _copy_trivia(old, new)
        else:
            _insert(cur, key, new)

    def delete(self, path: Path_, *, prune: bool = False) -> None:
        parent = self.get_item(path[:-1]) if len(path) > 1 else self.doc
        if parent is None:
            return
        key = path[-1]
        if isinstance(key, int):
            if isinstance(parent, AoT) and -len(parent) <= key < len(parent):
                body = parent.body
                body.pop(key)
            return
        if key in parent:
            del parent[key]
        if prune and len(path) > 1 and not isinstance(path[-2], int):
            if isinstance(parent, (Table, InlineTable)) and len(parent) == 0:
                self.delete(path[:-1], prune=True)

    def rename(self, path: Path_, new_key: str, value=_MISSING) -> None:
        """Rename a key in place (keeps its position and trailing comment)."""
        parent = self.get_item(path[:-1]) if len(path) > 1 else self.doc
        old_key = path[-1]
        if parent is None or old_key not in parent:
            raise KeyError(path)
        old = parent.item(old_key) if hasattr(parent, "item") else parent[old_key]
        new = old if value is _MISSING else _copy_trivia(old, tomlkit.item(value))
        if isinstance(new, Table) and not isinstance(new, InlineTable) and value is not _MISSING:
            it = tomlkit.inline_table()
            it.update(value)
            new = _copy_trivia(old, it)
        if new_key == old_key:
            parent[old_key] = new
            return
        if new_key in parent:
            raise KeyError(f"{new_key} existiert bereits")
        _body(parent)._replace(old_key, new_key, new)

    def append_table(self, path: Path_, value: dict | None = None) -> int:
        """Append an entry to an array of tables; returns its index."""
        aot = self.get_item(path)
        table = tomlkit.table()
        for k, v in (value or {}).items():
            table[k] = v
        if aot is None:
            new = tomlkit.aot()
            new.append(table)
            parent = self.get_item(path[:-1]) if len(path) > 1 else self.doc
            parent.add(path[-1], new) if parent is self.doc else _insert(parent, path[-1], new)
            return 0
        aot.append(table)
        return len(aot) - 1

    def move_table(self, path: Path_, index: int, new_index: int) -> None:
        aot = self.get_item(path)
        if not isinstance(aot, AoT) or not (0 <= new_index < len(aot)):
            return
        body = aot.body
        body.insert(new_index, body.pop(index))
        # tomlkit renders from the AoT body list, so this keeps comments in tables


# --------------------------------------------------------------------------- whole config


class Config:
    """The main config file plus everything it includes."""

    def __init__(self, path: Path | None = None):
        path = Path(path or default_config_path())
        self.main = TomlFile(path, seed=packaged_config() if path == default_config_path() else None)
        self.files: list[TomlFile] = []
        self.pending_raw: dict[Path, str] = {}  # non-TOML files (shaders) to write on save
        self.undo_stack: list[tuple[Path, str]] = []
        self.redo_stack: list[tuple[Path, str]] = []
        self.resolve_includes()

    @property
    def dir(self) -> Path:
        return self.main.real_path.parent

    def resolve_includes(self) -> None:
        old = {f.real_path: f for f in self.files[1:]}
        self.files = [self.main]
        self._walk(self.main, depth=0, seen={self.main.real_path}, old=old)

    def _walk(self, tf: TomlFile, depth: int, seen: set, old: dict) -> None:
        if depth > 8:
            return
        for optional, key in ((False, ("include", "files")), (True, ("include", "optional", "files"))):
            entries = tf.get(key, [])
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, str):
                    continue
                p = Path(os.path.expanduser(str(entry)))
                if not p.is_absolute():
                    p = Path(os.path.normpath(tf.real_path.parent / p))
                real = Path(os.path.realpath(p))
                if real in seen:
                    continue
                seen.add(real)
                child = old.get(real)
                if child is None or child.dirty is False:
                    child = TomlFile(p, included_by=tf, optional=optional)
                self.files.append(child)
                self._walk(child, depth + 1, seen, old)

    def includes(self) -> list[TomlFile]:
        return self.files[1:]

    def file_for(self, path: Path) -> TomlFile | None:
        real = Path(os.path.realpath(path))
        return next((f for f in self.files if f.real_path == real), None)

    def dirty_files(self) -> list[TomlFile]:
        return [f for f in self.files if f.dirty]

    @property
    def dirty(self) -> bool:
        return any(f.dirty for f in self.files) or bool(self.dirty_raw())

    def raw_text(self, path: Path) -> str:
        real = Path(os.path.realpath(path))
        if real in self.pending_raw:
            return self.pending_raw[real]
        return real.read_text(encoding="utf-8")

    def set_raw(self, path: Path, text: str) -> None:
        self.pending_raw[Path(os.path.realpath(path))] = text

    def dirty_raw(self) -> dict[Path, str]:
        out = {}
        for p, text in self.pending_raw.items():
            try:
                if p.read_text(encoding="utf-8") == text:
                    continue
            except (OSError, ValueError):
                pass
            out[p] = text
        return out

    def definers(self, path: Path_) -> list[TomlFile]:
        """Files that define ``path`` (main first, then includes in load order)."""
        return [f for f in self.files if f.has(path)]

    def effective(self, path: Path_, default=None):
        """Value as Umbriel sees it: includes are merged after the main file."""
        value = default
        for f in self.files:
            v = f.get(path, _MISSING)
            if v is not _MISSING:
                value = v
        return value

    # ----------------------------------------------------------------- undo

    def checkpoint(self, tf: TomlFile | None = None) -> None:
        tf = tf or self.main
        snap = (tf.real_path, tf.as_string())
        if not self.undo_stack or self.undo_stack[-1] != snap:
            self.undo_stack.append(snap)
            del self.undo_stack[:-200]
        self.redo_stack.clear()

    def _restore(self, src: list, dst: list) -> bool:
        while src:
            real, text = src.pop()
            tf = self.file_for(real)
            if tf is None:
                continue
            current = tf.as_string()
            if current == text:
                continue
            dst.append((real, current))
            tf.set_text(text)
            if tf is self.main:
                self.resolve_includes()
            return True
        return False

    def undo(self) -> bool:
        return self._restore(self.undo_stack, self.redo_stack)

    def redo(self) -> bool:
        return self._restore(self.redo_stack, self.undo_stack)

    # ----------------------------------------------------------------- disk

    def reload(self) -> None:
        for f in self.files:
            f.reload()
        self.resolve_includes()
        self.pending_raw.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

    def changed_on_disk(self) -> bool:
        for f in self.files:
            try:
                on_disk = f.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                on_disk = None
            except (OSError, ValueError):
                continue
            if on_disk != (f.text if f.exists else None):
                return True
        return False

    def validate(self, overrides: dict[Path, str] | None = None) -> tuple[bool, str]:
        """Validate the configuration with pending changes applied.

        The config directory is copied to a scratch directory so relative
        includes resolve exactly as they will after saving.
        """
        if overrides is None:
            overrides = {f.real_path: f.as_string() for f in self.dirty_files()}
        src = self.dir
        try:
            with tempfile.TemporaryDirectory(prefix="umbrielmod-") as tmp:
                root = Path(tmp) / "umbriel"
                _copy_config_dir(src, root)
                for real, text in overrides.items():
                    try:
                        rel = Path(real).relative_to(src)
                    except ValueError:
                        continue  # outside the config dir: validated in place
                    target = root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding="utf-8")
                self._pin_outside_includes(src, root)
                main_rel = self.main.real_path.relative_to(src)
                ok, message = umbriel.validate(str(root / main_rel))
                return ok, message.replace(str(root), str(src))
        except OSError as exc:
            return False, str(exc)

    def _pin_outside_includes(self, src: Path, root: Path) -> None:
        """Relative includes leaving the config dir (``../noctalia/x.toml``)
        do not exist below the scratch copy: make them absolute there."""
        for f in self.files:
            try:
                target = root / f.real_path.relative_to(src)
                doc = tomlkit.parse(target.read_text(encoding="utf-8"))
            except Exception:  # outside the config dir, unreadable or invalid
                continue
            changed = False
            for table in (doc.get("include"), (doc.get("include") or {}).get("optional")):
                entries = table.get("files") if isinstance(table, dict) else None
                if not isinstance(entries, list):
                    continue
                pinned = []
                for entry in entries:
                    p = Path(os.path.expanduser(str(entry)))
                    if not p.is_absolute():
                        real = Path(os.path.normpath(f.real_path.parent / p))
                        if not real.is_relative_to(src):
                            p, changed = real, True
                    pinned.append(str(p))
                if changed:
                    table["files"] = pinned
            if changed:
                target.write_text(doc.as_string(), encoding="utf-8")

    def save(self) -> tuple[bool, str]:
        dirty = self.dirty_files()
        raw = self.dirty_raw()
        if not dirty and not raw:
            return True, "No changes"
        ok, message = self.validate()
        if not ok:
            return False, message
        blocked = [p for p in (*raw, *(f.real_path for f in dirty)) if not _writable(p)]
        if blocked:
            return False, _("These files cannot be written (read-only or managed by another tool?):\n{files}").format(
                files="\n".join(map(str, blocked)))
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            for path, text in raw.items():
                backup_file(path, stamp)
                atomic_write(path, text)
                self.pending_raw.pop(path, None)
            for f in dirty:
                text = f.as_string()
                backup_file(f.real_path, stamp)
                atomic_write(f.real_path, text)
                f.text = text
                f.exists = True
            if raw and not dirty and self.main.exists:
                # Shaders are compiled when the config loads; rewrite the main file
                # unchanged so Umbriel's config watcher picks the new source up.
                atomic_write(self.main.real_path, self.main.as_string())
        except OSError as exc:
            return False, str(exc)
        self.pending_raw.clear()
        self.resolve_includes()
        return True, message


def _copy_config_dir(src: Path, root: Path) -> None:
    """Scratch copy for validation. Skips what a config cannot need and what
    would break copying (sockets, symlinks back to a parent directory)."""
    if not src.is_dir():
        root.mkdir(parents=True)
        return
    by_pattern = shutil.ignore_patterns("*.bak", "*.png", "*.gif", "*.jpg", ".git")

    def ignore(directory: str, names: list[str]) -> set[str]:
        skip = set(by_pattern(directory, names))
        here = os.path.realpath(directory)
        for name in names:
            p = os.path.join(directory, name)
            real = os.path.realpath(p)
            if here == real or here.startswith(real + os.sep) or not (os.path.isfile(p) or os.path.isdir(p)):
                skip.add(name)
        return skip

    try:
        shutil.copytree(src, root, ignore=ignore, copy_function=shutil.copyfile, ignore_dangling_symlinks=True)
    except shutil.Error:
        pass  # unreadable files: the validator reports whatever is really needed
    for directory, _dirs, _files in os.walk(root):
        os.chmod(directory, 0o700)  # the source may be read-only (e.g. the Nix store)


def _writable(path: Path) -> bool:
    """Files are replaced atomically, so what counts is the directory."""
    parent = Path(path).parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return os.access(parent, os.W_OK | os.X_OK)


def atomic_write(path: Path, text: str) -> None:
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".umbrielmod", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def backup_file(path: Path, stamp: str | None = None, keep: int = 50) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    stamp = stamp or _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = _backup_name(path)
    dest = backup_dir() / f"{stamp}__{name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    backups = sorted(f for f in backup_dir().iterdir() if f.name.partition("__")[2] == name)
    for old in backups[:-keep]:
        old.unlink(missing_ok=True)
    return dest


def _backup_name(path: Path) -> str:
    """Path relative to the config dir (absolute outside it) as one file name."""
    try:
        rel = str(path.relative_to(config_dir().resolve()))
    except ValueError:
        rel = str(path)
    return quote(rel, safe="").replace("__", "%5F%5F")


def _backup_original(name: str) -> Path:
    # names without "%" come from before paths were quoted
    rel = unquote(name) if "%" in name else name.replace("__", os.sep)
    return config_dir() / rel


def list_backups() -> list[tuple[_dt.datetime, Path, Path]]:
    """(timestamp, backup file, original path) — newest first."""
    out = []
    if not backup_dir().exists():
        return out
    for f in backup_dir().iterdir():
        stamp, sep, name = f.name.partition("__")
        if not sep:
            continue
        try:
            when = _dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        out.append((when, f, _backup_original(name)))
    return sorted(out, reverse=True)
