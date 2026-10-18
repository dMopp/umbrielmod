"""Separate window that shows an effect live, rendered by Umbriel."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from .. import preview, shaders, umbriel
from ..context import AppContext
from ..i18n import N_, _
from ..widgets import AnimatedPicture, esc

SAMPLE_TEXT = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore "
    "et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
    "aliquip ex ea commodo consequat."
)

# demo id → (title, description, icon); which events each demo shows
DEMOS = {
    "window": (N_("Open & close a window"),
               N_("Opens a test window and closes it again once the animation has finished."),
               "window-new-symbolic"),
    "workspace": (N_("Switch workspace"),
                  N_("Switches to the next workspace and back again."),
                  "view-paged-symbolic"),
    "move": (N_("Move a window"),
             N_("Opens a test window, moves it left and back, then closes it."),
             "object-flip-horizontal-symbolic"),
    "overview": (N_("Open the overview"),
                 N_("Opens the overview and closes it again."),
                 "view-grid-symbolic"),
}
EVENT_DEMO = {"windows_in": "window", "windows_out": "window", "workspaces": "workspace",
              "windows_move": "move", "overview": "overview"}
PAUSE_MS = 900  # extra time to look at the result before the next step
TEST_WINDOW_SIZE = (560, 360)


class PreviewWindow(Adw.Window):
    _open: "PreviewWindow | None" = None

    @classmethod
    def show(cls, ctx: AppContext, effect: shaders.Effect, parent: Gtk.Window | None = None):
        if cls._open is not None:
            cls._open.close()
        win = cls(ctx, effect, parent)
        cls._open = win
        # load the preview config (with floating rules for these windows) before mapping
        ok, msg = win.session.start([(win.get_title(), *win.get_default_size()),
                                     (_("Animation test"), *TEST_WINDOW_SIZE)])
        win._start_result = (ok, msg)
        win.present()
        return win

    def __init__(self, ctx: AppContext, effect: shaders.Effect, parent: Gtk.Window | None):
        title = _("Preview: {name}").format(name=effect.title)
        is_anim = effect.kind == "animation"
        super().__init__(title=title, default_width=760 if is_anim else 900, default_height=640 if is_anim else 600)
        self.ctx, self.effect = ctx, effect
        self.parent_window = parent
        self.session = preview.PreviewSession(ctx.cfg, effect)
        self.window_id: str | None = None
        self._tries = 0
        self._demo_buttons: list[Gtk.Button] = []
        self.durations = effect.animation_durations()

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=esc(title), subtitle=esc(
            _("Rendered live by Umbriel · {kind}").format(kind=_(shaders.KIND_LABELS.get(effect.kind, effect.kind))))))
        tv.add_top_bar(header)
        self.banner = Adw.Banner()
        tv.add_top_bar(self.banner)
        tv.set_content(self._animation_content() if is_anim else self._sample_content())
        tv.add_bottom_bar(self._controls())
        self.set_content(tv)
        self.connect("close-request", self._on_close)
        self.connect("map", lambda *_: GLib.idle_add(self._start))

    # ----------------------------------------------------------------- content

    def _sample_content(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24,
                      margin_start=32, margin_end=32, valign=Gtk.Align.START)
        box.append(Gtk.Label(label=self.effect.title, xalign=0, css_classes=["title-1"]))
        box.append(Gtk.Label(label=SAMPLE_TEXT, xalign=0, wrap=True, css_classes=["body"]))
        swatches = Gtk.Box(spacing=12, homogeneous=True)
        for css in ("accent", "success", "warning", "error"):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"], height_request=90,
                           valign=Gtk.Align.START)
            card.append(Gtk.Label(label=css, css_classes=[css, "heading"], valign=Gtk.Align.CENTER, vexpand=True))
            swatches.append(card)
        box.append(swatches)
        lst = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for i, text in enumerate((_("First line"), _("Second line"), _("Third line"))):
            row = Adw.ActionRow(title=text, subtitle=SAMPLE_TEXT[: 40 + i * 20])
            row.add_suffix(Gtk.Switch(active=i % 2 == 0, valign=Gtk.Align.CENTER))
            lst.append(row)
        box.append(lst)
        return Gtk.ScrolledWindow(child=box, vexpand=True)

    def _animation_content(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        demos = list(dict.fromkeys(EVENT_DEMO[e] for e in self.session.animation_events() if e in EVENT_DEMO))
        group = Adw.PreferencesGroup(
            title=_("Play on your desktop"),
            description=_("While this preview is open, Umbriel uses this animation for the events below. "
                          "The buttons trigger them for real."),
        )
        for demo in demos:
            title, desc, icon = DEMOS[demo]
            events = [e for e in self.session.animation_events() if EVENT_DEMO.get(e) == demo]
            ms = max((self.durations.get(e, 250) for e in events), default=250)
            row = Adw.ActionRow(title=esc(_(title)), subtitle=esc(_(desc) + "\n" + _("{events} · {ms} ms").format(
                events=", ".join(events), ms=ms)))
            row.set_subtitle_lines(3)
            row.add_prefix(Gtk.Image(icon_name=icon, pixel_size=24))
            btn = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"])
            btn.set_child(Adw.ButtonContent(icon_name="media-playback-start-symbolic", label=_("Play")))
            btn.connect("clicked", lambda *_, d=demo: self._play(d))
            row.add_suffix(btn)
            row.set_activatable_widget(btn)
            self._demo_buttons.append(btn)
            group.add(row)
        if not demos:
            group.add(Adw.ActionRow(title=esc(_("This animation has no event that can be played from here."))))
        page.add(group)

        media = self.effect.animated_preview or self.effect.preview
        if media:
            rec = Adw.PreferencesGroup(
                title=_("Recording from the collection"),
                description=_("Rendered by the collection's headless Umbriel preview."),
            )
            pic = AnimatedPicture(media, content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, height_request=280)
            frame = Gtk.Frame(child=pic, css_classes=["card"])
            rec.add(frame)
            page.add(rec)
        return page

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
        if kind in ("border", "window", "screen", "cursor"):
            again = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Apply again"))
            again.connect("clicked", lambda *_: self._apply())
            bar.append(again)
        close = Gtk.Button(label=_("Close preview"))
        close.connect("clicked", lambda *_: self.close())
        bar.append(close)
        return bar

    # ----------------------------------------------------------------- lifecycle

    def _start(self):
        for b in self._demo_buttons:
            b.set_sensitive(False)
        ok, msg = getattr(self, "_start_result", (False, "not started"))
        if not ok:
            self._fail(_("Umbriel could not load the effect:") + "\n" + msg)
            return False
        if self.session.replaced:
            self.banner.set_title(_("A temporary copy of your configuration is active while the preview is open."))
            self.banner.set_revealed(True)
        if self.ctx.cfg.dirty_raw():
            self.status.set_label(_("Unsaved shader changes become visible after saving."))
        for b in self._demo_buttons:
            b.set_sensitive(True)
        GLib.timeout_add(300, self._find_window)
        return False

    def _find_window(self):
        info = preview.find_window(self.get_title())
        if info is None:
            self._tries += 1
            if self._tries > 20:
                self._fail(_("This window could not be found in Umbriel's window list."))
                return False
            return True
        self.window_id = info.get("id")
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
            self._report(True, "", _("Press “Play” to see the animation."))

    def _global(self, enabled: bool):
        ok, msg = self.session.set_global(enabled)
        hint = (_("The effect is shown on your screen until the preview closes.") if self.effect.kind == "screen"
                else _("Move the pointer to see the cursor effect."))
        self._report(ok, msg, hint if enabled else "")

    # ----------------------------------------------------------------- animation demos

    def _ms(self, *events: str) -> int:
        return max((self.durations.get(e, 250) for e in events), default=250)

    def _run(self, steps: list):
        """Run (delay_ms, action) steps one after another; buttons are disabled meanwhile."""
        for b in self._demo_buttons:
            b.set_sensitive(False)
        self.status.set_label(_("Playing…"))

        def step(i: int):
            if i >= len(steps):
                for b in self._demo_buttons:
                    b.set_sensitive(True)
                self.status.set_label(_("Done – press “Play” to watch again."))
                return
            delay, action = steps[i]

            def fire():
                action()
                step(i + 1)
                return False

            GLib.timeout_add(max(delay, 1), fire)

        step(0)

    def _test_window(self) -> Adw.Window:
        w = Adw.Window(title=_("Animation test"), default_width=TEST_WINDOW_SIZE[0],
                       default_height=TEST_WINDOW_SIZE[1])
        w.set_content(Adw.StatusPage(title=self.effect.title, description=_("Animation test"),
                                     icon_name="applications-graphics-symbolic"))
        return w

    def _play(self, demo: str):
        holder: dict = {}
        if demo == "window":
            open_ms, close_ms = self._ms("windows_in"), self._ms("windows_out")
            self._run([
                (0, lambda: holder.setdefault("w", self._test_window()).present()),
                (open_ms + PAUSE_MS, lambda: holder["w"].close()),
                (close_ms + 300, lambda: None),
            ])
        elif demo == "workspace":
            ms = self._ms("workspaces")
            self._run([
                (0, lambda: umbriel.msg("workspace-next")),
                (ms + PAUSE_MS, lambda: umbriel.msg("workspace-previous")),
                (ms + 300, lambda: None),
            ])
        elif demo == "move":
            ms = self._ms("windows_move")

            def move(dx):
                wid = preview.find_window_id(_("Animation test"))
                if wid:
                    umbriel.msg(f"window-move-by:{dx}/0/{wid}")

            self._run([
                (0, lambda: holder.setdefault("w", self._test_window()).present()),
                (900, lambda: move(-420)),
                (ms + PAUSE_MS, lambda: move(420)),
                (ms + PAUSE_MS, lambda: holder["w"].close()),
                (400, lambda: None),
            ])
        elif demo == "overview":
            self._run([
                (0, lambda: umbriel.msg("overview-toggle")),
                (self._ms("overview") + 1500, lambda: umbriel.msg("overview-toggle")),
                (400, lambda: None),
            ])

    # ----------------------------------------------------------------- feedback

    def _report(self, ok: bool, msg: str, hint: str):
        if ok:
            self.status.set_label(hint or _("Effect active."))
        else:
            self._fail(msg)

    def _fail(self, msg: str):
        self.status.set_label(msg)
        self.status.remove_css_class("dim-label")
        self.status.add_css_class("error")

    def _on_close(self, *_args):
        self.session.stop()
        if PreviewWindow._open is self:
            PreviewWindow._open = None
        return False
