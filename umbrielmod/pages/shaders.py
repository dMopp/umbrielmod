"""Effects & shaders: community catalog, installed presets, tuning, live test."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk, Pango

from .. import shaders, umbriel
from ..config import TomlFile, toml_literal
from ..context import AppContext
from ..docs import DOCS_SITE, section_url
from ..i18n import N_, _
from ..widgets import AnimatedPicture, color_swatches, doc_button, esc, icon_button, option_doc_url, option_row, rgba_from_string, rgba_to_string
from .schema_page import MapGroup, leaf_groups

ANIMATION_EVENTS_LABELS = {
    "windows_in": N_("Window opens"),
    "windows_out": N_("Window closes"),
    "windows_move": N_("Window moves"),
    "workspaces": N_("Workspace switch"),
    "overview": N_("Overview"),
    "scratchpad": N_("Scratchpad"),
    "border": N_("Border"),
    "dim_unfocused": N_("Dim unfocused"),
    "layers": N_("Layer surfaces"),
}


def kind_label(kind: str) -> str:
    return _(shaders.KIND_LABELS.get(kind, kind))


def _markdown_to_text(md: str) -> str:
    text = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), md, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _load_thumb(path: Path, width: int, height: int, picture: Gtk.Picture):
    def work():
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height, True)
        except GLib.Error:
            return
        GLib.idle_add(lambda: picture.set_paintable(Gdk.Texture.new_for_pixbuf(pb)) and False)

    _THUMB_POOL.append(work)
    _kick_pool()


_THUMB_POOL: list = []
_POOL_RUNNING = [False]


def _kick_pool():
    if _POOL_RUNNING[0]:
        return
    _POOL_RUNNING[0] = True

    def run():
        while _THUMB_POOL:
            job = _THUMB_POOL.pop(0)
            job()
        _POOL_RUNNING[0] = False

    threading.Thread(target=run, daemon=True).start()


def _with_header(content: Gtk.Widget, end: Gtk.Widget | None = None) -> Gtk.Widget:
    """Toolbar with its own header bar so pushed pages get a back button."""
    tv = Adw.ToolbarView(content=content)
    header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
    if end is not None:
        header.pack_end(end)
    tv.add_top_bar(header)
    return tv


def _active_selections(ctx: AppContext, name: str) -> list[str]:
    return [".".join(str(p) for p in path) for path in shaders.references(ctx.cfg, {name})]


# =========================================================================== page


class ShadersPage(Gtk.Box):
    def __init__(self, ctx: AppContext, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctx = ctx
        self.window = window
        self.nav = Adw.NavigationView(vexpand=True)
        self.append(self.nav)

        self.stack = Adw.ViewStack()
        self.installed_page = InstalledView(self)
        self.catalog_page = CatalogView(self)
        self.global_page = GlobalEffectsView(ctx)
        self.stack.add_titled_with_icon(self.installed_page, "installed", _("Installed"), "emblem-ok-symbolic")
        self.stack.add_titled_with_icon(self.catalog_page, "catalog", _("Catalogue"), "system-software-install-symbolic")
        self.stack.add_titled_with_icon(self.global_page, "global", _("Selection & pools"), "emblem-system-symbolic")
        switcher = Adw.InlineViewSwitcher(stack=self.stack, halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=4)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(switcher)
        box.append(self.stack)
        self.stack.set_vexpand(True)
        self.nav.add(Adw.NavigationPage(title=_("Effects & shaders"), tag="root", child=box))
        if not shaders.installed():
            self.stack.set_visible_child_name("catalog")

    def refresh(self):
        self.installed_page.refresh()
        self.catalog_page.refresh()
        self.global_page.refresh()
        page = self.nav.get_visible_page()
        if hasattr(page, "refresh"):
            page.refresh()

    # ----------------------------------------------------------------- operations

    def preview(self, effect: shaders.Effect):
        from .preview_window import PreviewWindow

        PreviewWindow.show(self.ctx, effect, self.window)

    def show_detail(self, effect: shaders.Effect):
        self.nav.push(DetailPage(self, effect))

    def show_config(self, tf: TomlFile, preset: str, effect: shaders.Effect | None):
        self.nav.push(PresetPage(self, tf, preset, effect))

    def install(self, effect: shaders.Effect, activate: bool):
        try:
            shaders.install_files(effect)
        except OSError as exc:
            self.window.error_dialog(_("Installation failed"), str(exc))
            return
        installed = shaders.load_effect(shaders.install_root(), shaders.installed_dir(effect))
        tf = self.ctx.cfg.main

        def do():
            shaders.add_include(self.ctx.cfg, installed)
            if activate:
                shaders.apply_activation(self.ctx.cfg, effect)

        self.ctx.edit(tf, do)
        if self.window.save():
            self.ctx.toast((_("{name} installed and activated") if activate else _("{name} installed")).format(name=effect.title))
        else:
            self.ctx.cfg.undo()
            self.ctx.changed()
        self.window.refresh_all()

    def uninstall(self, effect: shaders.Effect):
        installed = shaders.load_effect(shaders.install_root(), shaders.installed_dir(effect))
        names = set(installed.presets)
        refs = shaders.references(self.ctx.cfg, names)
        body = _("The files in {dir} will be deleted.").format(dir=shaders.installed_dir(effect))
        if refs:
            body += "\n\n" + _("These selections will be removed:") + "\n" + "\n".join("• " + ".".join(map(str, r)) for r in refs)
        dlg = Adw.AlertDialog(heading=_("Uninstall {name}?").format(name=effect.title), body=body)
        dlg.add_response("cancel", _("Cancel"))
        dlg.add_response("remove", _("Uninstall"))
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r != "remove":
                return
            self.ctx.edit(self.ctx.cfg.main, lambda: (shaders.clear_references(self.ctx.cfg, names),
                                                      shaders.remove_include(self.ctx.cfg, installed)))
            if self.window.save():
                shaders.remove_files(installed)
                self.ctx.toast(_("{name} removed").format(name=effect.title))
                while self.nav.get_visible_page().get_tag() != "root":
                    self.nav.pop()
            else:
                self.ctx.cfg.undo()
                self.ctx.changed()
            self.window.refresh_all()

        dlg.connect("response", resp)
        dlg.present(self.window)


# =========================================================================== catalog


class CatalogView(Gtk.Box):
    def __init__(self, page: ShadersPage):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.page = page
        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search effects…"), hexpand=True)
        self.search.connect("search-changed", lambda *_: self.flow.invalidate_filter())
        self.kind = Gtk.DropDown(model=Gtk.StringList.new([_("All")] + [kind_label(k) for k in shaders.KINDS]))
        self.kind.connect("notify::selected", lambda *_: self.flow.invalidate_filter())
        self.sync_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Update the catalogue from GitHub"))
        self.sync_btn.connect("clicked", lambda *_: self.sync())
        self.status = Gtk.Label(css_classes=["dim-label", "caption"])
        for w in (self.search, self.kind, self.status, self.sync_btn,
                  doc_button(page.ctx, f"{DOCS_SITE}/effects/", _("Effects"))):
            bar.append(w)
        self.append(bar)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
                                max_children_per_line=6, row_spacing=6, column_spacing=6,
                                margin_start=12, margin_end=12, margin_bottom=12, valign=Gtk.Align.START)
        self.flow.set_filter_func(self._filter)
        self.flow.connect("child-activated", lambda _f, child: self.page.show_detail(child.effect))
        self.scroller = Gtk.ScrolledWindow(vexpand=True, child=self.flow)
        self.empty = Adw.StatusPage(
            icon_name="folder-download-symbolic", title=_("Get the community shaders"),
            description=_("Downloads the collection from github.com/{repo} (about 40 MB) to {dir}.").format(
                repo=shaders.REPO_SLUG, dir=shaders.cache_repo_dir()),
            vexpand=True,
        )
        dl = Gtk.Button(label=_("Download"), css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        dl.connect("clicked", lambda *_: self.sync())
        self.empty.set_child(dl)
        self.append(self.scroller)
        self.append(self.empty)
        self.refresh()

    def refresh(self):
        while (child := self.flow.get_first_child()) is not None:
            self.flow.remove(child)
        effects = shaders.catalog()
        has = bool(effects)
        self.scroller.set_visible(has)
        self.empty.set_visible(not has)
        rev = shaders.repo_revision()
        self.status.set_label(_("{n} effects · {revision}").format(n=len(effects), revision=rev) if has else "")
        for eff in effects:
            self.flow.append(self._card(eff))

    def _card(self, eff: shaders.Effect) -> Gtk.FlowBoxChild:
        child = Gtk.FlowBoxChild()
        child.effect = eff
        child.haystack = f"{eff.title} {eff.rel} {eff.summary}".lower()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["card", "effect-card"])
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, height_request=120, width_request=200)
        if eff.preview:
            _load_thumb(eff.preview, 360, 220, pic)
        box.append(pic)
        top = Gtk.Box(spacing=6)
        title = Gtk.Label(label=eff.title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"])
        top.append(title)
        if shaders.is_installed(eff):
            top.append(Gtk.Image(icon_name="emblem-ok-symbolic", tooltip_text=_("Installed")))
        box.append(top)
        badge = Gtk.Label(label=kind_label(eff.kind), xalign=0, halign=Gtk.Align.START,
                          css_classes=["kind-badge"])
        box.append(badge)
        child.set_child(box)
        return child

    def _filter(self, child) -> bool:
        idx = self.kind.get_selected()
        if idx > 0 and child.effect.kind != shaders.KINDS[idx - 1]:
            return False
        q = self.search.get_text().lower().strip()
        return not q or all(p in child.haystack for p in q.split())

    def sync(self):
        self.sync_btn.set_sensitive(False)
        self.status.set_label(_("Loading…"))
        self.page.ctx.toast(_("Fetching the community shaders from GitHub…"))

        def work():
            ok, msg = shaders.sync_repo()
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            self.sync_btn.set_sensitive(True)
            self.refresh()
            self.page.installed_page.refresh()
            self.page.ctx.toast(_("Catalogue updated ({revision})").format(revision=msg) if ok
                                else _("Error: {message}").format(message=msg))

        threading.Thread(target=work, daemon=True).start()


class DetailPage(Adw.NavigationPage):
    def __init__(self, page: ShadersPage, effect: shaders.Effect):
        super().__init__(title=effect.title)
        self.page, self.effect = page, effect
        self.body = Adw.PreferencesPage()
        self.set_child(_with_header(self.body))
        self._groups = []
        self.refresh()

    def _preview_effect(self) -> shaders.Effect:
        """Prefer the installed copy (it may be tuned), else the catalogue files."""
        if shaders.is_installed(self.effect):
            return shaders.load_effect(shaders.install_root(), shaders.installed_dir(self.effect))
        return self.effect

    def refresh(self):
        for g in self._groups:
            self.body.remove(g)
        self._groups = []
        eff = self.effect
        ctx = self.page.ctx

        head = Adw.PreferencesGroup()
        overlay = Gtk.Overlay()
        if eff.animated_preview:
            pic = AnimatedPicture(eff.animated_preview, content_fit=Gtk.ContentFit.CONTAIN, height_request=300,
                                  can_shrink=True)
        else:
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=300, can_shrink=True)
            if eff.preview:
                _load_thumb(eff.preview, 900, 600, pic)
        overlay.set_child(Gtk.Frame(child=pic, css_classes=["card"]))
        play = Gtk.Button(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, css_classes=["osd", "pill", "preview-play"],
                          tooltip_text=_("Opens a window on which Umbriel renders this effect – "
                                         "nothing in your config changes."))
        play.set_child(Adw.ButtonContent(icon_name="media-playback-start-symbolic", label=_("Live preview")))
        play.connect("clicked", lambda *_: self.page.preview(self._preview_effect()))
        overlay.add_overlay(play)
        head.add(overlay)

        actions = Gtk.Box(spacing=8, margin_top=12)
        live = Gtk.Button(css_classes=["pill"])
        live.set_child(Adw.ButtonContent(icon_name="media-playback-start-symbolic", label=_("Live preview")))
        live.connect("clicked", lambda *_: self.page.preview(self._preview_effect()))
        actions.append(live)
        spacer = Gtk.Box(hexpand=True)
        actions.append(spacer)
        self._action_box = actions
        head.add(actions)
        self._push(head)

        info = Adw.PreferencesGroup(title=esc(eff.title), description=esc(eff.summary))
        installed = shaders.is_installed(eff)
        btns = self._action_box
        if installed:
            upd = Gtk.Button(label=_("Update"), css_classes=["pill"])
            upd.connect("clicked", lambda *_: self.page.install(eff, activate=False))
            rm = Gtk.Button(label=_("Uninstall"), css_classes=["destructive-action", "pill"])
            rm.connect("clicked", lambda *_: self.page.uninstall(eff))
            btns.append(upd)
            btns.append(rm)
        else:
            inst = Gtk.Button(label=_("Install"), css_classes=["pill"])
            inst.connect("clicked", lambda *_: self.page.install(eff, activate=False))
            act = Gtk.Button(label=_("Install & activate"), css_classes=["suggested-action", "pill"])
            act.connect("clicked", lambda *_: self._confirm_activate())
            btns.append(inst)
            btns.append(act)
        gh = icon_button("web-browser-symbolic", _("View on GitHub"),
                         lambda: ctx.open_uri(f"{shaders.REPO_URL}/tree/main/{eff.rel}"))
        btns.append(gh)

        def row(title, subtitle):
            r = Adw.ActionRow(title=esc(title), subtitle=esc(subtitle))
            r.set_subtitle_selectable(True)
            info.add(r)

        row(_("Kind"), kind_label(eff.kind))
        row(_("Preset names"), ", ".join(eff.presets) or "—")
        if eff.companions():
            row(_("Companion effects (installed too)"), ", ".join(str(Path(c).name) for c in eff.companions()))
        row(_("Install location"), str(shaders.installed_dir(eff)))
        lic = [p.name for p in eff.license_files]
        if lic:
            row(_("Licence"), ", ".join(lic))
        if eff.needs_pointer_history:
            warn = Adw.ActionRow(title=_("Needs the cursor history API"),
                                 subtitle=_("Uses umbriel_pointer_path/umbriel_pointer_count – only works with "
                                            "newer Umbriel builds."))
            warn.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            info.add(warn)
        changes = shaders.activation_changes(eff)
        if changes:
            row(_("Activation sets"), "\n".join(f"{'.'.join(map(str, p))} = {toml_literal(v)}" for p, v in changes))
        if installed:
            for name in eff.presets:
                cfg_row = Adw.ActionRow(title=esc(_("Configure preset “{name}”").format(name=name)), activatable=True)
                cfg_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                inst_eff = shaders.load_effect(shaders.install_root(), shaders.installed_dir(eff))
                tf = ctx.cfg.file_for(inst_eff.effect_toml)
                if tf is None:
                    cfg_row.set_sensitive(False)
                    cfg_row.set_subtitle(_("Not included"))
                else:
                    cfg_row.connect("activated", lambda *_, t=tf, n=name, e=inst_eff: self.page.show_config(t, n, e))
                info.add(cfg_row)
        self._push(info)

        readme = Adw.PreferencesGroup(title="README")
        exp = Adw.ExpanderRow(title=_("Description, options and shader controls"))
        lbl = Gtk.Label(label=_markdown_to_text(eff.readme), wrap=True, xalign=0, selectable=True,
                        margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        exp.add_row(lbl)
        readme.add(exp)
        self._push(readme)

    def _confirm_activate(self):
        changes = shaders.activation_changes(self.effect)
        current = []
        for path, value in changes:
            old = self.page.ctx.cfg.main.get(path)
            if old is not None and old != value:
                current.append(f"• {'.'.join(map(str, path))}: {old!r} → {value!r}")
        if not current:
            self.page.install(self.effect, activate=True)
            return
        dlg = Adw.AlertDialog(heading=_("Overwrite existing settings?"),
                              body=_("The activation example changes:") + "\n" + "\n".join(current))
        dlg.add_response("cancel", _("Cancel"))
        dlg.add_response("only", _("Install only"))
        dlg.add_response("ok", _("Apply"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.connect("response", lambda _d, r: r in ("ok", "only") and self.page.install(self.effect, activate=r == "ok"))
        dlg.present(self.page.window)

    def _push(self, g):
        self.body.add(g)
        self._groups.append(g)


# =========================================================================== installed


class InstalledView(Adw.PreferencesPage):
    def __init__(self, page: ShadersPage):
        super().__init__()
        self.page = page
        self._groups = []
        self.refresh()

    def refresh(self):
        for g in self._groups:
            self.remove(g)
        self._groups = []
        ctx = self.page.ctx
        installed = shaders.installed()
        catalog = {str(e.rel): e for e in shaders.catalog()}
        by_kind: dict[str, list] = {}
        for eff in installed:
            by_kind.setdefault(eff.kind, []).append(eff)
        seen_presets = set()
        for kind in shaders.KINDS:
            effs = by_kind.get(kind)
            if not effs:
                continue
            g = Adw.PreferencesGroup(title=kind_label(kind))
            for eff in effs:
                seen_presets.update(eff.presets)
                g.add(self._row(eff, catalog.get(str(eff.rel))))
            self._push(g)

        # presets defined elsewhere (own effects, examples …)
        other = []
        for tf in ctx.cfg.files:
            for name, p in (tf.get(("effects", "preset")) or {}).items():
                if name not in seen_presets:
                    other.append((tf, name, p))
        if other:
            g = Adw.PreferencesGroup(title=_("Other presets"), description=_("Defined in the configuration, not from the catalogue."))
            for tf, name, p in other:
                r = Adw.ActionRow(title=esc(name), subtitle=esc(f"{kind_label(p.get('kind', ''))} · {tf.path.name}"),
                                  activatable=True)
                r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                r.connect("activated", lambda *_, t=tf, n=name: self.page.show_config(t, n, None))
                g.add(r)
            self._push(g)

        if not installed and not other:
            g = Adw.PreferencesGroup()
            st = Adw.StatusPage(icon_name="applications-graphics-symbolic", title=_("No effects installed yet"),
                                description=_("The catalogue has the community shaders for Umbriel."))
            g.add(st)
            self._push(g)

    def _row(self, eff: shaders.Effect, cat: shaders.Effect | None) -> Adw.ActionRow:
        ctx = self.page.ctx
        title = cat.title if cat else eff.title
        tf = ctx.cfg.file_for(eff.effect_toml)
        active = []
        for name in eff.presets:
            active += _active_selections(ctx, name)
        sub = ", ".join(eff.presets)
        if tf is None:
            sub += " · " + _("not included")
        elif active:
            sub += " · " + _("active: {where}").format(where=", ".join(active))
        row = Adw.ActionRow(title=esc(title), subtitle=esc(sub), activatable=tf is not None)
        if active:
            row.add_prefix(Gtk.Image(icon_name="media-playback-start-symbolic", tooltip_text=_("Active")))
        row.add_suffix(icon_button("media-playback-start-symbolic", _("Live preview"),
                                   lambda: self.page.preview(eff)))
        if tf is None:
            inc = Gtk.Button(label=_("Include"), valign=Gtk.Align.CENTER)

            def include():
                ctx.edit(ctx.cfg.main, lambda: shaders.add_include(ctx.cfg, eff))
                self.page.window.refresh_all()

            inc.connect("clicked", lambda *_: include())
            row.add_suffix(inc)
        else:
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda *_: self.page.show_config(tf, eff.name, eff))
        if cat is not None:
            row.add_suffix(icon_button("help-about-symbolic", _("Details"), lambda: self.page.show_detail(cat)))
        row.add_suffix(icon_button("user-trash-symbolic", _("Uninstall"), lambda: self.page.uninstall(eff)))
        return row

    def _push(self, g):
        self.add(g)
        self._groups.append(g)


# =========================================================================== preset config


class PresetPage(Adw.NavigationPage):
    """Settings Umbriel supports for one preset, plus GLSL constants."""

    def __init__(self, page: ShadersPage, tf: TomlFile, name: str, effect: shaders.Effect | None):
        super().__init__(title=name)
        self.page, self.tf, self.name, self.effect = page, tf, name, effect
        self.body = Adw.PreferencesPage()
        self.set_child(_with_header(self.body))
        self._groups = []
        self.refresh()

    @property
    def preset(self) -> dict:
        return self.tf.get(("effects", "preset", self.name)) or {}

    def refresh(self):
        for g in self._groups:
            self.body.remove(g)
        self._groups = []
        ctx = self.page.ctx
        kind = self.preset.get("kind", "")
        base = ("effects", "preset", self.name)

        # ---- selection
        sel = Adw.PreferencesGroup(title=_("Use"),
                                   description=_("Selection in your config.toml. Window rules and outputs can "
                                                 "set their own effects as well."))
        sel.set_header_suffix(doc_button(ctx, section_url("effects", "Settings"), _("Use")))
        main = ctx.cfg.main
        if kind in shaders.SLOT_KINDS:
            sw = Adw.SwitchRow(title=esc(_("Use as default effect ({kind})").format(kind=kind_label(kind))),
                               subtitle=esc(f"[effects] {kind} = \"{self.name}\""),
                               active=main.get(("effects", kind)) == self.name)

            def toggled(row, *_):
                if row.get_active():
                    ctx.set(main, ("effects", kind), self.name)
                elif main.get(("effects", kind)) == self.name:
                    ctx.delete(main, ("effects", kind))

            sw.connect("notify::active", toggled)
            sel.add(sw)

        elif kind == "animation":
            for event in self._animation_events():
                path = ("animation", event, "effect")
                sw = Adw.SwitchRow(title=esc(_(ANIMATION_EVENTS_LABELS.get(event, event))),
                                   subtitle=esc(f"animation.{event}.effect"),
                                   active=main.get(path) == self.name)

                def toggled(row, *_, p=path):
                    if row.get_active():
                        ctx.set(main, p, self.name)
                    elif main.get(p) == self.name:
                        ctx.delete(main, p)

                sw.connect("notify::active", toggled)
                eff_opt = ctx.schema.options.get(f"animation.{event}.effect")
                if eff_opt is not None:
                    sw.add_suffix(doc_button(ctx, option_doc_url(ctx, eff_opt), f"animation.{event}.effect"))
                sel.add(sw)
        if self.effect is not None:
            live = Adw.ActionRow(title=_("Live preview"),
                                 subtitle=_("Opens a window on which Umbriel renders this effect – "
                                            "nothing in your config changes."))
            btn = Gtk.Button(label=_("Open"), valign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda *_: self.page.preview(self.effect))
            live.add_suffix(btn)
            sel.add(live)
        if self.effect is not None:
            cat = next((e for e in shaders.catalog() if e.rel == self.effect.rel), None)
            if cat is not None and shaders.activation_changes(cat):
                ex = Adw.ButtonRow(title=_("Apply the activation example"))
                ex.connect("activated", lambda *_: (ctx.edit(main, lambda: shaders.apply_activation(ctx.cfg, cat)),
                                                     self.refresh()))
                sel.add(ex)
        self._push(sel)

        # ---- preset keys
        grp = Adw.PreferencesGroup(title=_("Preset"), description=esc(f"[effects.preset.\"{self.name}\"] – {self.tf.path}"))
        grp.set_header_suffix(doc_button(ctx, section_url("effects", "Define a preset"), _("Preset")))
        kind_row = Adw.ActionRow(title=_("Kind"), subtitle=esc(kind_label(kind)))
        grp.add(kind_row)
        shader_row = Adw.ActionRow(title=_("Shader"), subtitle=esc(str(self.preset.get("shader", "—"))))
        grp.add(shader_row)
        for key in shaders.PRESET_KEYS.get(kind, ("palette",)):
            opt = ctx.schema.options.get(f"effects.preset.<name>.{key}")
            if opt is None:
                continue
            grp.add(option_row(ctx, opt, base + (key,), self.tf))
            if key == "palette":
                grp.add(self._palette_row())
        if kind == "border" and self._ring_padding() is not None:
            sync = Adw.ButtonRow(title=_("Match ring_padding in the shader to padding"))
            sync.connect("activated", lambda *_: self._sync_padding())
            grp.add(sync)
        self._push(grp)

        # ---- light (border only)
        if kind == "border":
            lg = Adw.PreferencesGroup(title=_("Light"),
                                      description=_("The border casts light onto its surroundings. Off without the table."))
            light_opt = ctx.schema.options.get("effects.preset.<name>.light.spread")
            if light_opt is not None:
                lg.set_header_suffix(doc_button(ctx, option_doc_url(ctx, light_opt), _("Light")))
            has_light = self.tf.has(base + ("light",))
            sw = Adw.SwitchRow(title=_("Enable light"), active=has_light)

            def light_toggled(row, *_):
                if row.get_active():
                    ctx.set(self.tf, base + ("light",), dict(shaders.LIGHT_DEFAULTS))
                else:
                    ctx.delete(self.tf, base + ("light",), prune=False)
                GLib.idle_add(lambda: self.refresh() and False)

            sw.connect("notify::active", light_toggled)
            lg.add(sw)
            if has_light:
                for key in shaders.LIGHT_KEYS:
                    opt = ctx.schema.options.get(f"effects.preset.<name>.light.{key}")
                    if opt is not None:
                        lg.add(option_row(ctx, opt, base + ("light", key), self.tf))
            self._push(lg)

        # ---- GLSL constants
        for shader_path in self._shader_paths():
            self._push(self._constants_group(shader_path))

    def _palette_row(self) -> Adw.ActionRow:
        ctx = self.page.ctx
        row = Adw.ActionRow(
            title=_("Theme colours for this effect"),
            subtitle=esc(_("With “Palette” on, the shader recolours its artwork with these colours from [colors] "
                           "(accent_primary, accent_secondary, warning, error). Off shows the shader's original "
                           "colours – as in the catalogue previews.")),
        )
        row.set_subtitle_lines(4)
        row.add_suffix(color_swatches(shaders.palette_colors(ctx.cfg, ctx.schema)))
        return row

    def _animation_events(self) -> list[str]:
        out = []
        for p in self.page.ctx.schema.options:
            m = re.fullmatch(r"animation\.(\w+)\.effect", p)
            if m:
                out.append(m.group(1))
        return out

    def _shader_paths(self) -> list[Path]:
        rel = self.preset.get("shader")
        if not rel:
            return []
        p = (self.tf.real_path.parent / rel).resolve()
        return [p] if p.exists() else []

    def _ring_padding(self):
        for sp in self._shader_paths():
            for c in shaders.parse_constants(self.page.ctx.cfg.raw_text(sp)):
                if c.name == "ring_padding":
                    return c
        return None

    def _sync_padding(self):
        padding = self.preset.get("padding", 0)
        for sp in self._shader_paths():
            cfg = self.page.ctx.cfg
            cfg.set_raw(sp, shaders.sync_ring_padding(cfg.raw_text(sp), int(padding)))
        self.page.ctx.changed()
        self.refresh()

    def _constants_group(self, shader_path: Path) -> Adw.PreferencesGroup:
        ctx = self.page.ctx
        cfg = ctx.cfg
        src = cfg.raw_text(shader_path)
        consts = shaders.parse_constants(src)
        g = Adw.PreferencesGroup(
            title=esc(_("Shader controls ({file})").format(file=shader_path.name)),
            description=_("Top-level constants from the GLSL code – the collection's documented way to fine-tune. "
                          "Written to the shader file when you save."),
        )
        orig = shader_path.with_name(shader_path.name + ".orig")
        if orig.exists():
            def restore():
                cfg.set_raw(shader_path, orig.read_text())
                ctx.changed()
                self.refresh()

            g.set_header_suffix(icon_button("edit-undo-symbolic", _("Restore the original"), restore, flat=False))
        if not consts:
            g.add(Adw.ActionRow(title=_("No adjustable constants found")))
            return g

        def write(const, values):
            text = cfg.raw_text(shader_path)
            fresh = {c.name: c for c in shaders.parse_constants(text)}.get(const.name, const)
            cfg.set_raw(shader_path, shaders.set_constant(text, fresh, values))
            ctx.changed()

        for c in consts:
            if c.name.startswith(("umbriel_",)) or c.name in ("ring_size", "ring_width", "ring_radius"):
                continue
            title = esc(c.name)
            sub = esc(c.comment) if c.comment else esc(f"{c.kind} {c.type}")
            if c.name == "ring_padding":
                sub = _("Must match the preset padding")
            if c.type == "bool":
                row = Adw.SwitchRow(title=title, subtitle=sub, active=bool(c.values[0]))
                row.connect("notify::active", lambda r, *_, c=c: write(c, [r.get_active()]))
            elif c.type in ("float", "int"):
                v = c.values[0]
                span = max(abs(v) * 10, 1.0) if c.type == "float" else max(abs(v) * 10, 10)
                lo = 0.0 if v >= 0 else -span
                row = Adw.SpinRow.new_with_range(lo, span, 1 if c.type == "int" else 0.01)
                row.set_title(title)
                row.set_subtitle(sub)
                row.set_digits(0 if c.type == "int" else 3)
                row.set_value(v)
                row.connect("notify::value", lambda r, *_, c=c: write(c, [r.get_value()]))
            elif c.is_color:
                row = Adw.ActionRow(title=title, subtitle=sub)
                btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=c.type == "vec4"), valign=Gtk.Align.CENTER)
                rgba = c.values + ([1.0] if c.type == "vec3" else [])
                btn.set_rgba(rgba_from_string(rgba_to_string(Gdk.RGBA(red=rgba[0], green=rgba[1], blue=rgba[2], alpha=rgba[3]))))

                def color_changed(b, *_, c=c):
                    col = b.get_rgba()
                    vals = [col.red, col.green, col.blue] + ([col.alpha] if c.type == "vec4" else [])
                    write(c, [round(x, 4) for x in vals])

                btn.connect("notify::rgba", color_changed)
                row.add_suffix(btn)
            else:
                row = Adw.EntryRow(title=f"{title} ({c.type})")
                row.set_text(", ".join(shaders.format_float(x) for x in c.values))

                def vec_changed(r, *_, c=c):
                    try:
                        vals = [float(x) for x in r.get_text().split(",")]
                    except ValueError:
                        r.add_css_class("error")
                        return
                    if len(vals) != int(c.type[-1]):
                        r.add_css_class("error")
                        return
                    r.remove_css_class("error")
                    write(c, vals)

                row.connect("changed", vec_changed)
            g.add(row)
        return g

    def _push(self, g):
        self.body.add(g)
        self._groups.append(g)


# =========================================================================== global


class GlobalEffectsView(Adw.PreferencesPage):
    """``[effects]`` slots and options plus pools – straight from the schema."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._groups = []
        self.refresh()

    def refresh(self):
        for g in self._groups:
            self.remove(g)
        self._groups = []
        for g in leaf_groups(self.ctx, "effects", ("effects",), title=_("Global effects")):
            self.add(g)
            self._groups.append(g)
        pools = MapGroup(self.ctx, "effects.pool", ("effects", "pool"))
        self.add(pools)
        self._groups.append(pools)
