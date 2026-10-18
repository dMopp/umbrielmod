"""Separate window that shows an effect live, rendered by Umbriel."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from .. import preview, shaders, umbriel
from ..context import AppContext
from ..i18n import _
from ..widgets import esc

SAMPLE_TEXT = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore "
    "et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
    "aliquip ex ea commodo consequat."
)

# which compositor actions demonstrate an animation event
EVENT_DEMOS = {
    "windows_in": "window",
    "windows_out": "window",
    "workspaces": "workspace",
    "overview": "overview",
}


class PreviewWindow(Adw.Window):
    _open: "PreviewWindow | None" = None

    @classmethod
    def show(cls, ctx: AppContext, effect: shaders.Effect, parent: Gtk.Window | None = None):
        if cls._open is not None:
            cls._open.close()
        win = cls(ctx, effect, parent)
        cls._open = win
        win.present()
        return win

    def __init__(self, ctx: AppContext, effect: shaders.Effect, parent: Gtk.Window | None):
        title = _("Preview: {name}").format(name=effect.title)
        super().__init__(title=title, default_width=980, default_height=660)
        self.ctx, self.effect = ctx, effect
        self.parent_window = parent
        self.session = preview.PreviewSession(ctx.cfg, effect)
        self.window_id: str | None = None
        self._tries = 0

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=esc(title), subtitle=esc(
            _("Rendered live by Umbriel · {kind}").format(kind=_(shaders.KIND_LABELS.get(effect.kind, effect.kind))))))
        tv.add_top_bar(header)
        self.banner = Adw.Banner()
        tv.add_top_bar(self.banner)
        tv.set_content(self._sample_content())
        tv.add_bottom_bar(self._controls())
        self.set_content(tv)
        self.connect("close-request", self._on_close)
        self.connect("map", lambda *_: GLib.idle_add(self._start))

    # ----------------------------------------------------------------- content

    def _sample_content(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24,
                      margin_start=32, margin_end=32)
        h = Gtk.Label(label=self.effect.title, xalign=0, css_classes=["title-1"])
        box.append(h)
        p = Gtk.Label(label=SAMPLE_TEXT, xalign=0, wrap=True, css_classes=["body"])
        box.append(p)
        swatches = Gtk.Box(spacing=12, homogeneous=True)
        for css in ("accent", "success", "warning", "error"):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"], height_request=90)
            lbl = Gtk.Label(label=css, css_classes=[css, "heading"], vexpand=True)
            card.append(lbl)
            swatches.append(card)
        box.append(swatches)
        lst = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for i, text in enumerate((_("First line"), _("Second line"), _("Third line"))):
            row = Adw.ActionRow(title=text, subtitle=SAMPLE_TEXT[: 40 + i * 20])
            row.add_suffix(Gtk.Switch(active=i % 2 == 0, valign=Gtk.Align.CENTER))
            lst.append(row)
        box.append(lst)
        if self.effect.preview:
            pic = Gtk.Picture.new_for_filename(str(self.effect.preview))
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(-1, 160)
            box.append(pic)
        return Gtk.ScrolledWindow(child=box, vexpand=True)

    def _controls(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=8, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.status = Gtk.Label(xalign=0, hexpand=True, wrap=True, css_classes=["dim-label"])
        bar.append(self.status)
        kind = self.effect.kind
        if kind in ("screen", "cursor"):
            label = _("Apply to the whole screen") if kind == "screen" else _("Show cursor effect")
            self.global_toggle = Gtk.ToggleButton(label=label, active=True)
            self.global_toggle.connect("toggled", lambda b: self._global(b.get_active()))
            bar.append(self.global_toggle)
        if kind == "animation":
            for event in self.session.animation_events():
                demo = EVENT_DEMOS.get(event)
                btn = Gtk.Button(label=_("Play: {event}").format(event=event))
                btn.set_sensitive(demo is not None)
                btn.connect("clicked", lambda *_, d=demo: self._play(d))
                bar.append(btn)
        again = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Apply again"))
        again.connect("clicked", lambda *_: self._apply())
        bar.append(again)
        close = Gtk.Button(label=_("Close preview"), css_classes=["suggested-action"])
        close.connect("clicked", lambda *_: self.close())
        bar.append(close)
        return bar

    # ----------------------------------------------------------------- lifecycle

    def _start(self):
        ok, msg = self.session.start()
        if not ok:
            self._fail(_("Umbriel could not load the effect:") + "\n" + msg)
            return False
        if self.session.replaced:
            self.banner.set_title(_("A temporary copy of your configuration is active while the preview is open."))
            self.banner.set_revealed(True)
        if self.ctx.cfg.dirty_raw():
            self.status.set_label(_("Unsaved shader changes become visible after saving."))
        GLib.timeout_add(300, self._find_window)
        return False

    def _find_window(self):
        self.window_id = preview.find_window_id(self.get_title())
        if self.window_id is None:
            self._tries += 1
            if self._tries > 20:
                self._fail(_("This window could not be found in Umbriel's window list."))
                return False
            return True
        self._apply()
        return False

    def _apply(self):
        kind = self.effect.kind
        if kind in ("border", "window") and self.window_id:
            ok, msg = self.session.apply_to_window(self.window_id)
            hint = _("Border effects show while this window is focused.") if kind == "border" else ""
            self._report(ok, msg, hint)
        elif kind in ("screen", "cursor"):
            active = getattr(self, "global_toggle", None)
            self._global(active.get_active() if active else True)
        elif kind == "animation":
            self._report(True, "", _("Use the buttons below to play the transition."))

    def _global(self, enabled: bool):
        ok, msg = self.session.set_global(enabled)
        hint = (_("The effect is shown on your screen until the preview closes.") if self.effect.kind == "screen"
                else _("Move the pointer to see the cursor effect."))
        self._report(ok, msg, hint if enabled else "")

    def _play(self, demo: str | None):
        if demo == "window":
            w = Adw.Window(title=_("Animation test"), default_width=420, default_height=260)
            w.set_content(Adw.StatusPage(title=_("Animation test"), icon_name="window-new-symbolic"))
            w.present()
            GLib.timeout_add(1800, lambda: w.close() and False)
        elif demo == "workspace":
            umbriel.msg("workspace-next")
            GLib.timeout_add(2600, lambda: umbriel.msg("workspace-previous") and False)
        elif demo == "overview":
            umbriel.msg("overview-toggle")
            GLib.timeout_add(2200, lambda: umbriel.msg("overview-toggle") and False)

    def _report(self, ok: bool, msg: str, hint: str):
        if ok:
            self.status.set_label(hint or _("Effect active."))
        else:
            self._fail(msg)

    def _fail(self, msg: str):
        self.status.set_label(msg)
        self.status.remove_css_class("dim-label")
        self.status.add_css_class("error")

    def _on_close(self, *_):
        self.session.stop()
        if PreviewWindow._open is self:
            PreviewWindow._open = None
        return False
