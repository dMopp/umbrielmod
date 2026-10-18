"""Main window: sidebar navigation, save/undo header, external-change banner."""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from . import __version__, i18n, settings, theme, updater
from . import docs as docsmod
from .context import AppContext
from .i18n import N_, _
# Import every page up front: a self-update may replace the sources while the
# app runs, and lazily imported modules would then mix versions.
from .pages import keybinds as _keybinds, outputs as _outputs, raw as _raw  # noqa: F401
from .pages import rules as _rules, shaders as _shaders_page  # noqa: F401
from .pages.schema_page import SchemaPage
from .widgets import doc_button, esc

# (id, title, Tabler icon, sections or factory name, docs page)
PAGES: list[tuple[str, str, str, object, str]] = [
    ("outputs", N_("Outputs"), "device-desktop", "outputs", "outputs"),
    ("input", N_("Input"), "keyboard", ["input"], "input"),
    ("keybinds", N_("Keybinds"), "command", "keybinds", "keybinds"),
    ("appearance", N_("Appearance"), "palette", ["appearance", "colors"], "appearance"),
    ("layout", N_("Layout"), "layout-columns", ["layout"], "layout"),
    ("workspaces", N_("Workspaces"), "stack-2",
     ["workspaces", "workspace", "overview", "hot_corners", "scratchpad"], "workspaces"),
    ("animation", N_("Animations"), "player-play", ["animation"], "animation"),
    ("window_rule", N_("Window rules"), "app-window", "rules", "window-rules"),
    ("layer_rule", N_("Layer rules"), "layers-subtract", ["layer_rule"], "layer-rules"),
    ("shaders", N_("Effects & shaders"), "sparkles", "shaders", "effects"),
    ("general", N_("General"), "settings",
     ["general", "environment", "events", "screencast", "include", "drm", "security_context_rule"], "configuration"),
    ("raw", N_("Raw editor"), "code", "raw", "configuration"),
    ("backups", N_("Backups"), "history", "backups", ""),
]

CUSTOM_SECTIONS = {"output", "keybinds", "effects", "window_rule"}


class MainWindow(Adw.ApplicationWindow):
    _update_checked = False  # once per process, not again after a language switch
    _update_installed = ""

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
                    PAGES[i] = (page[0], page[1], page[2], list(page[3]) + missing, page[4])

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
        if MainWindow._update_installed:
            self._show_update_banner(MainWindow._update_installed)
        elif not MainWindow._update_checked and self._auto_update_enabled():
            MainWindow._update_checked = True
            GLib.timeout_add_seconds(2, lambda: self.check_updates(quiet=True) and False)

    # ----------------------------------------------------------------- layout

    def _sidebar(self) -> Adw.NavigationPage:
        self.sidebar = Gtk.ListBox(css_classes=["navigation-sidebar"])
        for pid, title, icon, *_rest in PAGES:
            row = Gtk.ListBoxRow()
            row.page_id = pid
            box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, margin_start=4)
            box.append(theme.icon(icon))
            box.append(Gtk.Label(label=_(title), xalign=0))
            row.set_child(box)
            self.sidebar.append(row)
        self.sidebar.connect("row-selected", self._on_row)
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append(_("Reload"), "win.reload")
        menu.append(_("Update schema and descriptions"), "win.refresh-docs")
        langs = Gio.Menu()
        langs.append(_("System default"), "win.language('')")
        for code, name in i18n.available_languages().items():
            langs.append(name, f"win.language('{code}')")
        menu.append_submenu(_("Language"), langs)
        if updater.is_managed():
            upd = Gio.Menu()
            upd.append(_("Check for updates"), "win.check-updates")
            upd.append(_("Update automatically"), "win.auto-update")
            menu.append_section(None, upd)
        menu.append(_("About UmbrielMod"), "win.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Menu")))
        tv.add_top_bar(header)
        tv.set_content(Gtk.ScrolledWindow(child=self.sidebar, hscrollbar_policy=Gtk.PolicyType.NEVER))
        return Adw.NavigationPage(title="UmbrielMod", child=tv)

    def _content(self) -> Adw.NavigationPage:
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="", subtitle=str(self.ctx.cfg.main.path))
        header.set_title_widget(self.title)
        self.undo_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text=_("Undo (Ctrl+Z)"), action_name="win.undo")
        self.redo_btn = Gtk.Button(icon_name="edit-redo-symbolic", tooltip_text=_("Redo (Ctrl+Shift+Z)"), action_name="win.redo")
        header.pack_start(self.undo_btn)
        header.pack_start(self.redo_btn)
        self.save_btn = Gtk.Button(label=_("Save"), css_classes=["suggested-action"], action_name="win.save",
                                   tooltip_text=_("Validate and save (Ctrl+S) – Umbriel reloads automatically"))
        self.discard_btn = Gtk.Button(label=_("Discard"), action_name="win.discard")
        header.pack_end(self.save_btn)
        header.pack_end(self.discard_btn)
        self.page_doc = Gtk.Box()
        header.pack_end(self.page_doc)
        tv.add_top_bar(header)
        self.banner = Adw.Banner(title=_("The configuration was changed outside UmbrielMod."),
                                 button_label=_("Reload (discards changes)"))
        self.banner.connect("button-clicked", lambda *_: self.reload(force=True))
        tv.add_top_bar(self.banner)
        self.update_banner = Adw.Banner(button_label=_("Restart now"))
        self.update_banner.connect("button-clicked", lambda *_: self.restart())
        tv.add_top_bar(self.update_banner)
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
        title, spec, docpage = next((_(t), s, d) for p, t, _i, s, d in PAGES if p == pid)
        child = self.page_doc.get_first_child()
        if child is not None:
            self.page_doc.remove(child)
        if docpage:
            self.page_doc.append(doc_button(self.ctx, f"{docsmod.DOCS_SITE}/{docpage}/", title))
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
        add("check-updates", lambda: self.check_updates(quiet=False))
        auto = Gio.SimpleAction.new_stateful("auto-update", None, GLib.Variant("b", self._auto_update_enabled()))

        def toggle_auto(action, _param):
            value = not action.get_state().get_boolean()
            action.set_state(GLib.Variant("b", value))
            settings.set("auto_update", value)

        auto.connect("activate", toggle_auto)
        self.add_action(auto)
        lang = Gio.SimpleAction.new_stateful("language", GLib.VariantType.new("s"),
                                             GLib.Variant("s", settings.get("language", "") or ""))
        lang.connect("activate", lambda a, v: self.set_language(a, v.get_string()))
        self.add_action(lang)

    def _update_state(self):
        dirty = self.ctx.cfg.dirty
        self.act_save.set_enabled(dirty)
        self.act_discard.set_enabled(dirty)
        self.act_undo.set_enabled(bool(self.ctx.cfg.undo_stack))
        self.act_redo.set_enabled(bool(self.ctx.cfg.redo_stack))
        names = ", ".join([f.path.name for f in self.ctx.cfg.dirty_files()] +
                          [p.name for p in self.ctx.cfg.dirty_raw()])
        self.title.set_subtitle(_("Unsaved: {files}").format(files=names) if dirty else str(self.ctx.cfg.main.path))

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
            self.toast(_("Saved – Umbriel applies the changes automatically"))
            self._watch_files()
        else:
            self.error_dialog(_("Invalid configuration – not saved"), message)
        self._update_state()
        return ok

    def reload(self, force: bool):
        if self.ctx.cfg.dirty and not force:
            dlg = Adw.AlertDialog(heading=_("Discard unsaved changes?"),
                                  body=_("The configuration will be reloaded from disk."))
            dlg.add_response("cancel", _("Cancel"))
            dlg.add_response("discard", _("Discard"))
            dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
            dlg.connect("response", lambda _d, r: r == "discard" and self.reload(force=True))
            dlg.present(self)
            return
        self.ctx.cfg.reload()
        self.banner.set_revealed(False)
        self._watch_files()
        self.refresh_all()

    def refresh_docs(self):
        self.toast(_("Fetching the Umbriel documentation for the installed version…"))
        schema = self.ctx.schema
        revision = schema.revision

        def work():
            ok, msg = docsmod.refresh(revision, list(schema.options))
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            if ok:
                self.ctx.docs = docsmod.Docs.load(revision)
                self.refresh_all()
            self.toast(msg if ok else _("Error: {message}").format(message=msg))

        threading.Thread(target=work, daemon=True).start()

    # ----------------------------------------------------------------- self-update

    def _auto_update_enabled(self) -> bool:
        return (updater.is_managed() and settings.get("auto_update", True) is not False
                and os.environ.get("UMBRIELMOD_NO_UPDATE") != "1")

    def check_updates(self, quiet: bool):
        if not updater.is_managed():
            return
        if not quiet:
            self.toast(_("Checking for updates…"))

        def work():
            info = updater.check()
            if info is None or not info.available:
                GLib.idle_add(lambda: (not quiet and self.toast(
                    _("Could not check for updates") if info is None else _("UmbrielMod is up to date"))) and False)
                return
            GLib.idle_add(lambda: self.toast(_("Installing an UmbrielMod update…")) and False)
            ok, log = updater.apply(info)
            GLib.idle_add(done, ok, log)

        def done(ok, log):
            if ok:
                MainWindow._update_installed = updater.summary()
                self._show_update_banner(MainWindow._update_installed)
            else:
                self.error_dialog(_("Update failed"), log[-4000:])

        threading.Thread(target=work, daemon=True).start()

    def _show_update_banner(self, summary: str):
        self.update_banner.set_title(esc(_("UmbrielMod was updated ({version}). Restart to use it.").format(
            version=summary)))
        self.update_banner.set_revealed(True)

    def restart(self):
        if self.ctx.cfg.dirty:
            dlg = Adw.AlertDialog(heading=_("Unsaved changes"),
                                  body=_("Save the changes before restarting?"))
            dlg.add_response("cancel", _("Cancel"))
            dlg.add_response("discard", _("Discard"))
            dlg.add_response("save", _("Save"))
            dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
            dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

            def resp(_d, r):
                if r == "discard" or (r == "save" and self.save()):
                    updater.restart(sys.argv)

            dlg.connect("response", resp)
            dlg.present(self)
            return
        updater.restart(sys.argv)

    def set_language(self, action: Gio.SimpleAction, code: str):
        action.set_state(GLib.Variant("s", code))
        settings.set("language", code or None)
        i18n.load(code or None)
        # rebuild the window in the new language; config state lives in ctx
        app, ctx = self.get_application(), self.ctx
        ctx._listeners.clear()
        new = MainWindow(app, ctx)
        new.set_default_size(self.get_width(), self.get_height())
        new.present()
        self._monitors_cancel()
        self.destroy()

    def _monitors_cancel(self):
        for m in self._monitors:
            m.cancel()
        self._monitors = []

    def about(self):
        about = Adw.AboutDialog(
            application_name="UmbrielMod",
            application_icon="io.github.umbrielmod",
            version=__version__,
            comments=_("Graphical configuration for the Umbriel Wayland compositor"),
            translator_credits=_("translator-credits") if _("translator-credits") != "translator-credits" else "",
            license_type=Gtk.License.MIT_X11,
            website="https://github.com/dMopp/umbrielmod",
            developer_name="Daniel Quolke",
            debug_info=f"Umbriel schema: {self.ctx.schema.version} ({self.ctx.schema.revision})\n"
                       f"Descriptions: revision {self.ctx.docs.revision or '—'}\n"
                       f"Language: {i18n.current_language()} (locale dirs: "
                       f"{', '.join(str(d) for d in i18n.search_dirs())})",
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
            self.toast(_("The configuration changed on disk and was reloaded"))
        return False

    def _on_close(self, *_):
        if not self.ctx.cfg.dirty:
            return False
        dlg = Adw.AlertDialog(heading=_("Unsaved changes"),
                              body=_("Save the changes before closing?"))
        dlg.add_response("cancel", _("Cancel"))
        dlg.add_response("discard", _("Discard"))
        dlg.add_response("save", _("Save"))
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r == "discard" or (r == "save" and self.save()):
                self.ctx.cfg.reload()
                self.destroy()

        dlg.connect("response", resp)
        dlg.present(self)
        return True
