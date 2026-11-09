"""Raw TOML editor and backup browser."""

from __future__ import annotations

import tomlkit
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from .. import config as cfgmod
from ..context import AppContext
from ..i18n import _
from ..widgets import esc


class RawPage(Gtk.Box):
    def __init__(self, ctx: AppContext):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctx = ctx
        self._loading = False
        self._edited = False

        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        self.files = Gtk.DropDown()
        self.files.connect("notify::selected", lambda *_: self.load())
        bar.append(self.files)
        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.status.add_css_class("dim-label")
        bar.append(self.status)
        check = Gtk.Button(label=_("Validate"))
        check.connect("clicked", lambda *_: self.check())
        apply = Gtk.Button(label=_("Apply"), css_classes=["suggested-action"])
        apply.connect("clicked", lambda *_: self.apply())
        bar.append(check)
        bar.append(apply)
        self.append(bar)

        self.buffer = Gtk.TextBuffer(enable_undo=True)
        self.buffer.connect("changed", self._changed)
        self.match_tag = self.buffer.create_tag("search-match", background="rgba(246, 211, 45, 0.45)")
        self.view = Gtk.TextView(buffer=self.buffer, monospace=True, wrap_mode=Gtk.WrapMode.NONE,
                                 top_margin=8, bottom_margin=8, left_margin=12, right_margin=12)
        self.append(self._build_search())
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.view)
        self.append(scroller)

        keys = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>f"),
                                       action=Gtk.CallbackAction.new(lambda *_: self.open_search() or True)))
        self.add_controller(keys)
        self.refresh()

    # ----------------------------------------------------------------- search

    def _build_search(self) -> Gtk.SearchBar:
        self._matches: list[tuple[int, int]] = []
        self._match = -1
        self.search = Gtk.SearchEntry(hexpand=True, placeholder_text=_("Search in the file"))
        self.search.connect("search-changed", lambda *_: self._find())
        self.search.connect("activate", lambda *_: self._step(1))
        self.search.connect("next-match", lambda *_: self._step(1))
        self.search.connect("previous-match", lambda *_: self._step(-1))
        self.search.connect("stop-search", lambda *_: self.close_search())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._search_key)
        self.search.add_controller(keys)
        self.case = Gtk.ToggleButton(label="Aa", tooltip_text=_("Match case"))
        self.case.connect("toggled", lambda *_: self._find())
        prev = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=_("Previous match (Shift+Enter)"))
        prev.connect("clicked", lambda *_: self._step(-1))
        nxt = Gtk.Button(icon_name="go-down-symbolic", tooltip_text=_("Next match (Enter)"))
        nxt.connect("clicked", lambda *_: self._step(1))
        self.match_label = Gtk.Label(width_chars=8, xalign=1)
        self.match_label.add_css_class("dim-label")
        nav = Gtk.Box(css_classes=["linked"])
        nav.append(prev)
        nav.append(nxt)
        box = Gtk.Box(spacing=6)
        for w in (self.search, self.match_label, self.case, nav):
            box.append(w)
        clamp = Adw.Clamp(maximum_size=640, child=box)
        self.search_bar = Gtk.SearchBar(child=clamp, show_close_button=True)
        self.search_bar.connect_entry(self.search)
        self.search_bar.connect("notify::search-mode-enabled", self._search_mode)
        return self.search_bar

    def open_search(self):
        sel = self.buffer.get_selection_bounds()
        if sel and sel[0].get_line() == sel[1].get_line():
            self.search.set_text(self.buffer.get_text(sel[0], sel[1], False))
        self.search_bar.set_search_mode(True)
        self.search.grab_focus()
        self.search.select_region(0, -1)
        self._find()

    def close_search(self):
        self.search_bar.set_search_mode(False)

    def _search_mode(self, *_):
        if self.search_bar.get_search_mode():
            return
        self._clear_matches()
        self.match_label.set_label("")
        self.view.grab_focus()

    def _search_key(self, _ctrl, keyval, _code, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.SHIFT_MASK:
            self._step(-1)
            return True
        return False

    def _clear_matches(self):
        start, end = self.buffer.get_bounds()
        self.buffer.remove_tag(self.match_tag, start, end)
        self._matches = []
        self._match = -1

    def _find(self, keep: int | None = None, select: bool = True):
        """Highlight every match and select the first one at or after *keep* (default: the cursor).

        With ``select=False`` (while the user types in the text) only the
        highlights and the counter follow, the cursor stays where it is.
        """
        if self._loading or not self.search_bar.get_search_mode():
            return
        self._clear_matches()
        needle = self.search.get_text()
        if not needle:
            self.match_label.set_label("")
            self.search.remove_css_class("error")
            return
        flags = Gtk.TextSearchFlags.TEXT_ONLY
        if not self.case.get_active():
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE
        it = self.buffer.get_start_iter()
        while (found := it.forward_search(needle, flags, None)) is not None:
            start, end = found
            self.buffer.apply_tag(self.match_tag, start, end)
            self._matches.append((start.get_offset(), end.get_offset()))
            if end.equal(it):  # zero-length guard
                break
            it = end
        if not self._matches:
            self.match_label.set_label(_("No match"))
            self.search.add_css_class("error")
            return
        self.search.remove_css_class("error")
        if keep is None:
            keep = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()
            sel = self.buffer.get_selection_bounds()
            if sel:
                keep = sel[0].get_offset()
        self._match = next((i for i, (s, _e) in enumerate(self._matches) if s >= keep), 0)
        if select:
            self._show_match()
        else:
            self._update_count()

    def _step(self, delta: int):
        if not self.search_bar.get_search_mode():
            return
        if not self._matches:
            self._find()
            return
        self._match = (self._match + delta) % len(self._matches)
        self._show_match()

    def _show_match(self):
        s, e = self._matches[self._match]
        start, end = self.buffer.get_iter_at_offset(s), self.buffer.get_iter_at_offset(e)
        self.buffer.select_range(start, end)
        self.view.scroll_to_iter(start, 0.1, False, 0, 0)
        self._update_count()

    def _update_count(self):
        self.match_label.set_label(_("{current} of {total}").format(current=self._match + 1,
                                                                    total=len(self._matches)))

    def _current(self) -> cfgmod.TomlFile:
        idx = self.files.get_selected()
        files = self.ctx.cfg.files
        return files[idx] if idx < len(files) else self.ctx.cfg.main

    def refresh(self):
        names = [str(f.path).replace(str(self.ctx.cfg.dir) + "/", "") for f in self.ctx.cfg.files]
        sel = min(self.files.get_selected(), len(names) - 1) if self.files.get_model() else 0
        self._loading = True
        self.files.set_model(Gtk.StringList.new(names))
        self.files.set_selected(max(sel, 0))
        self._loading = False
        self.load()

    def load(self):
        if self._loading:
            return
        tf = self._current()
        self._loading = True
        self.buffer.set_text(tf.as_string())
        self._loading = False
        self._edited = False
        self.status.set_label(str(tf.path))
        self._find(keep=0)

    def _changed(self, *_args):  # not *_: that would shadow the gettext _
        if not self._loading:
            self._edited = True
            self.status.set_label(_("Edited – “Apply” loads the text into the editor"))
            if self.search_bar.get_search_mode():
                GLib.idle_add(self._refind)

    def _refind(self):
        self._find(select=False)
        return False

    def _text(self) -> str:
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def check(self):
        tf = self._current()
        text = self._text()
        try:
            tomlkit.parse(text)
        except Exception as exc:
            self.status.set_label(_("TOML error: {error}").format(error=exc))
            return
        overrides = {f.real_path: f.as_string() for f in self.ctx.cfg.dirty_files()}
        overrides[tf.real_path] = text
        ok, msg = self.ctx.cfg.validate(overrides)
        self.status.set_label(("✓ " if ok else "✗ ") + msg.splitlines()[-1] if msg else "")
        if not ok:
            self.ctx.toast(msg.splitlines()[0] if msg else _("Invalid"))

    def apply(self):
        tf = self._current()
        try:
            self.ctx.cfg.checkpoint(tf)
            tf.set_text(self._text())
        except ValueError as exc:
            self.status.set_label(_("TOML error: {error}").format(error=exc))
            return
        if tf is self.ctx.cfg.main:
            self.ctx.cfg.resolve_includes()
        self._edited = False
        self.ctx.changed()
        self.ctx.toast(_("Text applied – not saved yet"))


class BackupsPage(Adw.PreferencesPage):
    def __init__(self, ctx: AppContext, on_restored):
        super().__init__()
        self.ctx = ctx
        self.on_restored = on_restored
        self.group = Adw.PreferencesGroup(
            title=_("Backups"),
            description=esc(_("Before every save a copy is stored in {dir} (the last 50 per file).").format(
                dir=cfgmod.backup_dir())),
        )
        self.add(self.group)
        self._rows = []
        self.refresh()

    def refresh(self):
        for r in self._rows:
            self.group.remove(r)
        self._rows.clear()
        backups = cfgmod.list_backups()
        for when, path, original in backups[:200]:
            row = Adw.ActionRow(title=when.strftime("%d.%m.%Y %H:%M:%S"),
                                subtitle=esc(str(original).replace(str(cfgmod.config_dir()) + "/", "")))
            btn = Gtk.Button(label=_("Restore"), valign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda *_, p=path, o=original: self.restore(p, o))
            row.add_suffix(btn)
            self.group.add(row)
            self._rows.append(row)
        if not backups:
            row = Adw.ActionRow(title=_("No backups yet"))
            self.group.add(row)
            self._rows.append(row)

    def restore(self, backup, original):
        tf = self.ctx.cfg.file_for(original)
        if tf is None:
            self.ctx.toast(_("This file is no longer part of the configuration"))
            return
        self.ctx.cfg.checkpoint(tf)
        try:
            tf.set_text(backup.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.ctx.toast(_("Error: {message}").format(message=exc))
            return
        if tf is self.ctx.cfg.main:
            self.ctx.cfg.resolve_includes()
        self.ctx.changed()
        GLib.idle_add(lambda: self.on_restored() and False)
        self.ctx.toast(_("Backup loaded – press “Save” to keep it"))
