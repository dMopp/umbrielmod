"""Raw TOML editor and backup browser."""

from __future__ import annotations

import tomlkit
from gi.repository import Adw, GLib, Gtk, Pango

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
        view = Gtk.TextView(buffer=self.buffer, monospace=True, wrap_mode=Gtk.WrapMode.NONE,
                            top_margin=8, bottom_margin=8, left_margin=12, right_margin=12)
        scroller = Gtk.ScrolledWindow(vexpand=True, child=view)
        self.append(scroller)
        self.refresh()

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

    def _changed(self, *_):
        if not self._loading:
            self._edited = True
            self.status.set_label(_("Edited – “Apply” loads the text into the editor"))

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
