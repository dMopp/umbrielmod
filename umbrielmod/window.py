"""Main window: sidebar navigation, save/undo header, external-change banner."""

from __future__ import annotations

import threading
from typing import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from . import __version__
from . import docs as docsmod
from .context import AppContext
from .pages.schema_page import SchemaPage
from .widgets import esc

# (id, title, icon, sections or factory name)
PAGES: list[tuple[str, str, str, object]] = [
    ("outputs", "Ausgaben", "video-display-symbolic", "outputs"),
    ("input", "Eingabe", "input-keyboard-symbolic", ["input"]),
    ("keybinds", "Tastenkürzel", "preferences-desktop-keyboard-shortcuts-symbolic", "keybinds"),
    ("appearance", "Darstellung", "preferences-desktop-appearance-symbolic", ["appearance", "colors"]),
    ("layout", "Layout", "view-grid-symbolic", ["layout"]),
    ("workspaces", "Arbeitsbereiche", "view-paged-symbolic", ["workspaces", "workspace", "overview", "hot_corners", "scratchpad"]),
    ("animation", "Animationen", "media-playback-start-symbolic", ["animation"]),
    ("window_rule", "Fensterregeln", "window-new-symbolic", "rules"),
    ("layer_rule", "Layer-Regeln", "view-list-symbolic", ["layer_rule"]),
    ("shaders", "Effekte & Shader", "applications-graphics-symbolic", "shaders"),
    ("general", "Allgemein", "preferences-system-symbolic",
     ["general", "environment", "events", "screencast", "include", "drm", "security_context_rule"]),
    ("raw", "Roh-Editor", "text-x-generic-symbolic", "raw"),
    ("backups", "Sicherungen", "document-open-recent-symbolic", "backups"),
]

CUSTOM_SECTIONS = {"output", "keybinds", "effects", "window_rule"}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, ctx: AppContext):
        super().__init__(application=app, title="UmbrielMod", default_width=1180, default_height=820)
        self.ctx = ctx
        ctx.toast = self.toast
        ctx.open_uri = self.open_uri
        ctx.on_changed(self._update_state)
        self._pages: dict[str, Gtk.Widget] = {}
        self._stale: set[str] = set()
        self._ignore_monitor_until = 0.0
        self._monitors: list[Gio.FileMonitor] = []

        # every schema section must be reachable, even ones added after this was written
        assigned = {s for *_, spec in PAGES if isinstance(spec, list) for s in spec} | CUSTOM_SECTIONS
        missing = [s for s in ctx.schema.sections() if s not in assigned]
        if missing:
            for i, page in enumerate(PAGES):
                if page[0] == "general":
                    PAGES[i] = (page[0], page[1], page[2], list(page[3]) + missing)

        self.toasts = Adw.ToastOverlay()
        split = Adw.NavigationSplitView(min_sidebar_width=210, max_sidebar_width=260)
        split.set_sidebar(self._sidebar())
        split.set_content(self._content())
        self.split = split

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 700sp"))
        bp.add_setter(split, "collapsed", True)
        self.add_breakpoint(bp)

        self.toasts.set_child(split)
        self.set_content(self.toasts)
        self._install_actions(app)
        self._watch_files()
        self.connect("close-request", self._on_close)
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))
        self._update_state()

    # ----------------------------------------------------------------- layout

    def _sidebar(self) -> Adw.NavigationPage:
        self.sidebar = Gtk.ListBox(css_classes=["navigation-sidebar"])
        for pid, title, icon, _ in PAGES:
            row = Gtk.ListBoxRow()
            row.page_id = pid
            box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6)
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=title, xalign=0))
            row.set_child(box)
            self.sidebar.append(row)
        self.sidebar.connect("row-selected", self._on_row)
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Neu laden", "win.reload")
        menu.append("Schema/Beschreibungen aktualisieren", "win.refresh-docs")
        menu.append("Über UmbrielMod", "win.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menü"))
        tv.add_top_bar(header)
        tv.set_content(Gtk.ScrolledWindow(child=self.sidebar, hscrollbar_policy=Gtk.PolicyType.NEVER))
        return Adw.NavigationPage(title="UmbrielMod", child=tv)

    def _content(self) -> Adw.NavigationPage:
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="", subtitle=str(self.ctx.cfg.main.path))
        header.set_title_widget(self.title)
        self.undo_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Rückgängig (Strg+Z)", action_name="win.undo")
        self.redo_btn = Gtk.Button(icon_name="edit-redo-symbolic", tooltip_text="Wiederholen (Strg+Umschalt+Z)", action_name="win.redo")
        header.pack_start(self.undo_btn)
        header.pack_start(self.redo_btn)
        self.save_btn = Gtk.Button(label="Speichern", css_classes=["suggested-action"], action_name="win.save",
                                   tooltip_text="Prüfen und speichern (Strg+S) – Umbriel lädt automatisch neu")
        self.discard_btn = Gtk.Button(label="Verwerfen", action_name="win.discard")
        header.pack_end(self.save_btn)
        header.pack_end(self.discard_btn)
        tv.add_top_bar(header)
        self.banner = Adw.Banner(title="Die Konfiguration wurde außerhalb von UmbrielMod geändert.",
                                 button_label="Neu laden (verwirft Änderungen)")
        self.banner.connect("button-clicked", lambda *_: self.reload(force=True))
        tv.add_top_bar(self.banner)
        tv.set_content(self.stack)
        self.content_page = Adw.NavigationPage(title="", child=tv)
        return self.content_page

    def _make_page(self, pid: str, spec) -> Gtk.Widget:
        ctx = self.ctx
        if isinstance(spec, list):
            return SchemaPage(ctx, spec)
        if spec == "outputs":
            from .pages.outputs import OutputsPage
            return OutputsPage(ctx)
        if spec == "keybinds":
            from .pages.keybinds import KeybindsPage
            return KeybindsPage(ctx)
        if spec == "rules":
            from .pages.rules import WindowRulesPage
            return WindowRulesPage(ctx)
        if spec == "shaders":
            from .pages.shaders import ShadersPage
            return ShadersPage(ctx, self)
        if spec == "raw":
            from .pages.raw import RawPage
            return RawPage(ctx)
        if spec == "backups":
            from .pages.raw import BackupsPage
            return BackupsPage(ctx, self.refresh_all)
        raise ValueError(spec)

    def _on_row(self, _lb, row):
        if row is None:
            return
        pid = row.page_id
        title, spec = next((t, s) for p, t, _i, s in PAGES if p == pid)
        if pid not in self._pages:
            page = self._make_page(pid, spec)
            self._pages[pid] = page
            self.stack.add_named(page, pid)
        elif pid in self._stale and hasattr(self._pages[pid], "refresh"):
            self._pages[pid].refresh()
        self._stale.discard(pid)
        self.stack.set_visible_child_name(pid)
        self.title.set_title(title)
        self.content_page.set_title(title)
        self.split.set_show_content(True)

    def current_page_id(self) -> str | None:
        return self.stack.get_visible_child_name()

    def refresh_all(self):
        cur = self.current_page_id()
        for pid, page in self._pages.items():
            if pid == cur:
                if hasattr(page, "refresh"):
                    page.refresh()
            else:
                self._stale.add(pid)
        self._update_state()

    # ----------------------------------------------------------------- actions

    def _install_actions(self, app: Adw.Application):
        def add(name: str, cb: Callable, accels: list[str] | None = None):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda *_: cb())
            self.add_action(act)
            if accels:
                app.set_accels_for_action(f"win.{name}", accels)
            return act

        self.act_save = add("save", self.save, ["<Control>s"])
        self.act_discard = add("discard", lambda: self.reload(force=True))
        self.act_undo = add("undo", self.undo, ["<Control>z"])
        self.act_redo = add("redo", self.redo, ["<Control><Shift>z", "<Control>y"])
        add("reload", lambda: self.reload(force=False), ["<Control>r"])
        add("refresh-docs", self.refresh_docs)
        add("about", self.about)

    def _update_state(self):
        dirty = self.ctx.cfg.dirty
        self.act_save.set_enabled(dirty)
        self.act_discard.set_enabled(dirty)
        self.act_undo.set_enabled(bool(self.ctx.cfg.undo_stack))
        self.act_redo.set_enabled(bool(self.ctx.cfg.redo_stack))
        names = ", ".join([f.path.name for f in self.ctx.cfg.dirty_files()] +
                          [p.name for p in self.ctx.cfg.dirty_raw()])
        self.title.set_subtitle(f"Ungespeichert: {names}" if dirty else str(self.ctx.cfg.main.path))

    def undo(self):
        if self.ctx.cfg.undo():
            self.refresh_all()

    def redo(self):
        if self.ctx.cfg.redo():
            self.refresh_all()

    def save(self) -> bool:
        cfg = self.ctx.cfg
        if not cfg.dirty:
            return True
        self._ignore_monitor_until = GLib.get_monotonic_time() + 2_000_000
        ok, message = cfg.save()
        if ok:
            self.toast("Gespeichert – Umbriel übernimmt die Änderungen automatisch")
            self._watch_files()
        else:
            self.error_dialog("Konfiguration ungültig – nicht gespeichert", message)
        self._update_state()
        return ok

    def reload(self, force: bool):
        if self.ctx.cfg.dirty and not force:
            dlg = Adw.AlertDialog(heading="Ungespeicherte Änderungen verwerfen?",
                                  body="Die Konfiguration wird von der Festplatte neu geladen.")
            dlg.add_response("cancel", "Abbrechen")
            dlg.add_response("discard", "Verwerfen")
            dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
            dlg.connect("response", lambda _d, r: r == "discard" and self.reload(force=True))
            dlg.present(self)
            return
        self.ctx.cfg.reload()
        self.banner.set_revealed(False)
        self._watch_files()
        self.refresh_all()

    def refresh_docs(self):
        self.toast("Lade Umbriel-Dokumentation für die installierte Version…")
        schema = self.ctx.schema
        revision = schema.revision

        def work():
            ok, msg = docsmod.refresh(revision, list(schema.options))
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            if ok:
                self.ctx.docs = docsmod.Docs.load(revision)
                self.refresh_all()
            self.toast(msg if ok else f"Fehler: {msg}")

        threading.Thread(target=work, daemon=True).start()

    def about(self):
        about = Adw.AboutDialog(
            application_name="UmbrielMod",
            application_icon="io.github.umbrielmod",
            version=__version__,
            comments="Grafische Konfiguration für den Umbriel-Wayland-Compositor",
            license_type=Gtk.License.MIT_X11,
            website="https://github.com/dmopp/umbrielmod",
            developer_name="Daniel Quolke",
            debug_info=f"Umbriel-Schema: {self.ctx.schema.version} ({self.ctx.schema.revision})\n"
                       f"Beschreibungen: Revision {self.ctx.docs.revision or '—'}",
        )
        about.present(self)

    # ----------------------------------------------------------------- feedback

    def toast(self, message: str):
        self.toasts.add_toast(Adw.Toast(title=esc(message), timeout=4))

    def open_uri(self, uri: str):
        Gtk.UriLauncher(uri=uri).launch(self, None, None, None)

    def error_dialog(self, heading: str, message: str):
        dlg = Adw.AlertDialog(heading=heading)
        label = Gtk.Label(label=message, wrap=True, selectable=True, xalign=0, css_classes=["monospace"])
        dlg.set_extra_child(Gtk.ScrolledWindow(child=label, min_content_height=120, max_content_height=400,
                                               propagate_natural_height=True))
        dlg.add_response("ok", "OK")
        dlg.present(self)

    # ----------------------------------------------------------------- file monitoring

    def _watch_files(self):
        for m in self._monitors:
            m.cancel()
        self._monitors = []
        for f in self.ctx.cfg.files:
            try:
                mon = Gio.File.new_for_path(str(f.real_path)).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error:
                continue
            mon.connect("changed", self._on_file_changed)
            self._monitors.append(mon)

    def _on_file_changed(self, *_):
        GLib.timeout_add(300, self._check_external)

    def _check_external(self):
        if GLib.get_monotonic_time() < self._ignore_monitor_until:
            return False
        if not self.ctx.cfg.changed_on_disk():
            return False
        if self.ctx.cfg.dirty:
            self.banner.set_revealed(True)
        else:
            self.ctx.cfg.reload()
            self._watch_files()
            self.refresh_all()
            self.toast("Konfiguration wurde extern geändert und neu geladen")
        return False

    def _on_close(self, *_):
        if not self.ctx.cfg.dirty:
            return False
        dlg = Adw.AlertDialog(heading="Ungespeicherte Änderungen",
                              body="Sollen die Änderungen vor dem Beenden gespeichert werden?")
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("discard", "Verwerfen")
        dlg.add_response("save", "Speichern")
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r == "discard" or (r == "save" and self.save()):
                self.ctx.cfg.reload()
                self.destroy()

        dlg.connect("response", resp)
        dlg.present(self)
        return True
