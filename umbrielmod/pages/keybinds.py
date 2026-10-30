"""Keybind table with search, conflict detection and an edit dialog."""

from __future__ import annotations

from collections import defaultdict

from gi.repository import Adw, Gdk, GLib, Gtk

from ..context import AppContext
from ..docs import DOCS_SITE, action_url, section_url
from ..i18n import N_, _
from ..umbriel import split_action
from ..widgets import doc_button, esc

MOD_ORDER = ("mod", "super", "ctrl", "alt", "shift")
MOD_ALIASES = {"control": "ctrl", "ctl": "ctrl", "logo": "super", "win": "super", "meta": "super"}
MOD_DISPLAY = {"mod": "Mod", "super": "Super", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
OPTION_DEFAULTS = {"repeat": True, "allow_when_locked": False, "allow_when_inhibited": False, "cooldown_ms": 0, "submap": ""}
OTHER = N_("Other")
# action groups as `umbriel msg --help` names them (listed for translation)
ACTION_GROUPS = (N_("Apps"), N_("Screencasting"), N_("Focus"), N_("Move & size"), N_("Windows"), N_("Scratchpad"), N_("Workspaces"), N_("Overview"), N_("System"))
MODIFIER_KEYVALS = {"Super_L", "Super_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                    "Meta_L", "Meta_R", "ISO_Level3_Shift", "Hyper_L", "Hyper_R"}


def split_combo(combo: str) -> tuple[list[str], str]:
    """("Mod+Shift+Q") -> (["mod", "shift"], "Q"); the last part is always the key."""
    parts = [p for p in combo.split("+") if p]
    if not parts:
        return [], ""
    mods = [MOD_ALIASES.get(p.lower(), p.lower()) for p in parts[:-1]]
    return mods, parts[-1]


def normalize_combo(combo: str) -> str:
    """Canonical form for conflict detection (modifier order/case-insensitive)."""
    mods, key = split_combo(combo)
    mods = sorted(set(mods), key=lambda m: (MOD_ORDER.index(m) if m in MOD_ORDER else 99, m))
    return "+".join(mods + [key.lower()])


def parse_bind(value) -> tuple[str, dict]:
    if isinstance(value, dict):
        opts = {k: v for k, v in value.items() if k != "action"}
        return str(value.get("action", "")), opts
    return str(value or ""), {}


def compose_bind(action: str, opts: dict):
    extra = {k: v for k, v in opts.items() if OPTION_DEFAULTS.get(k, object()) != v}
    if not extra:
        return action
    return {"action": action, **extra}


def find_conflicts(binds: dict) -> dict[str, list[str]]:
    seen: dict[tuple, list[str]] = defaultdict(list)
    for key, value in binds.items():
        _action, opts = parse_bind(value)
        seen[(normalize_combo(key), opts.get("submap", ""))].append(key)
    out = {}
    for keys in seen.values():
        if len(keys) > 1:
            for k in keys:
                out[k] = [o for o in keys if o != k]
    return out


def keycaps(combo: str) -> Gtk.Widget:
    box = Gtk.Box(spacing=3, valign=Gtk.Align.CENTER)
    mods, key = split_combo(combo)
    for part in [MOD_DISPLAY.get(m, m) for m in mods] + ([key] if key else []):
        lbl = Gtk.Label(label=part)
        lbl.add_css_class("keycap")
        box.append(lbl)
    return box


class KeybindsPage(Gtk.Box):
    def __init__(self, ctx: AppContext):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctx = ctx
        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search keys or actions…"), hexpand=True)
        self.search.connect("search-changed", lambda *_: self.refresh())
        bar.append(self.search)
        self.conflicts_only = Gtk.ToggleButton(icon_name="dialog-warning-symbolic", tooltip_text=_("Show conflicts only"))
        self.conflicts_only.connect("toggled", lambda *_: self.refresh())
        bar.append(self.conflicts_only)
        add = Gtk.Button(css_classes=["suggested-action"])
        add.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label=_("New")))
        add.connect("clicked", lambda *_: KeybindDialog(ctx, None, self.refresh).present(self))
        bar.append(add)
        bar.append(doc_button(ctx, f"{DOCS_SITE}/keybinds/", _("Keybinds")))
        self.append(bar)
        self.page = Adw.PreferencesPage(vexpand=True)
        self.append(self.page)
        self._groups: list = []
        self.refresh()

    def _binds(self) -> dict:
        return self.ctx.cfg.main.get(("keybinds",)) or {}

    def refresh(self):
        for g in self._groups:
            self.page.remove(g)
        self._groups.clear()
        binds = self._binds()
        conflicts = find_conflicts(binds)
        groups_of = {a.name: a.group for a in self.ctx.actions}
        desc_of = {a.name: a.description for a in self.ctx.actions}
        q = self.search.get_text().lower().strip()
        grouped: dict[str, list] = defaultdict(list)
        for key, value in binds.items():
            action, opts = parse_bind(value)
            name = split_action(action)[0]
            if q and q not in f"{key} {action} {desc_of.get(name, '')}".lower():
                continue
            if self.conflicts_only.get_active() and key not in conflicts:
                continue
            grouped[groups_of.get(name, OTHER)].append((key, action, opts))

        if conflicts:
            warn = Adw.PreferencesGroup()
            n = len(conflicts)
            row = Adw.ActionRow(title=esc(_("{n} key combinations conflict").format(n=n)),
                                subtitle=esc(_("Same key with the same modifiers (order and spelling do not matter).")))
            row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["warning"]))
            warn.add(row)
            self._push(warn)

        order = list(dict.fromkeys(a.group for a in self.ctx.actions)) + [OTHER]
        for group in order:
            items = grouped.get(group)
            if not items:
                continue
            g = Adw.PreferencesGroup(title=esc(_(group)))
            if group != OTHER:
                g.set_header_suffix(doc_button(self.ctx, action_url(group), group))
            for key, action, opts in items:
                g.add(self._row(key, action, opts, conflicts.get(key), desc_of))
            self._push(g)

        for f in self.ctx.cfg.includes():
            extra = f.get(("keybinds",)) or {}
            if extra:
                g = Adw.PreferencesGroup(title=esc(_("From {file}").format(file=f.path.name)),
                                         description=_("Read-only"))
                for key, value in extra.items():
                    action, _opts = parse_bind(value)
                    r = Adw.ActionRow(title=esc(action))
                    r.add_prefix(keycaps(key))
                    r.set_sensitive(False)
                    g.add(r)
                self._push(g)
        if not grouped:
            empty = Adw.PreferencesGroup()
            empty.add(Adw.ActionRow(title=_("No keybinds found")))
            self._push(empty)

    def _push(self, g):
        self.page.add(g)
        self._groups.append(g)

    def _row(self, key, action, opts, conflict, desc_of) -> Adw.ActionRow:
        name, arg = split_action(action)
        desc = desc_of.get(name, "")
        if name == "spawn":
            title = _("Run: {command}").format(command=arg)
        else:
            title = f"{desc} — {arg}" if desc and arg else desc or action
        flags = []
        if opts.get("repeat") is False:
            flags.append(_("no repeat"))
        if opts.get("allow_when_locked"):
            flags.append(_("also when locked"))
        if opts.get("allow_when_inhibited"):
            flags.append(_("despite inhibit"))
        if opts.get("cooldown_ms"):
            flags.append(_("cooldown {ms} ms").format(ms=opts["cooldown_ms"]))
        if opts.get("submap"):
            flags.append(_("submap {name}").format(name=opts["submap"]))
        sub = action + (f"  ·  {', '.join(flags)}" if flags else "")
        row = Adw.ActionRow(title=esc(title), subtitle=esc(sub), activatable=True)
        row.set_title_lines(1)
        caps = keycaps(key)
        caps.set_size_request(190, -1)
        row.add_prefix(caps)
        if conflict:
            icon = Gtk.Image(icon_name="dialog-warning-symbolic",
                             tooltip_text=_("Conflicts with: {keys}").format(keys=", ".join(conflict)))
            icon.add_css_class("error")
            row.add_suffix(icon)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_: KeybindDialog(self.ctx, key, self.refresh).present(self))
        return row


class KeybindDialog(Adw.Dialog):
    def __init__(self, ctx: AppContext, key: str | None, on_done):
        super().__init__(title=_("Edit keybind") if key else _("New keybind"),
                         content_width=560, content_height=640)
        self.ctx, self.key, self.on_done = ctx, key, on_done
        value = ctx.cfg.main.get(("keybinds", key)) if key else None
        action, opts = parse_bind(value)
        self.opts = {**OPTION_DEFAULTS, **opts}
        self.actions = list(ctx.actions)
        self._capturing = False

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: self.close())
        save = Gtk.Button(label=_("Apply"), css_classes=["suggested-action"])
        save.connect("clicked", lambda *_: self._save())
        header.pack_start(cancel)
        header.pack_end(save)
        tv.add_top_bar(header)
        page = Adw.PreferencesPage()
        tv.set_content(page)
        self.set_child(tv)

        # --- key
        g = Adw.PreferencesGroup(title=_("Key"),
                                 description=_("Same format as the config, e.g. Mod+Shift+Q, XF86AudioMute, Mod+WheelDown."))
        g.set_header_suffix(doc_button(ctx, section_url("keybinds", "Special keys"), _("Key")))
        self.combo = Adw.EntryRow(title=_("Key combination"), text=key or "")
        self.combo.connect("changed", lambda *_: self._check_conflict())
        self.record = Gtk.ToggleButton(icon_name="media-record-symbolic", valign=Gtk.Align.CENTER,
                                       tooltip_text=_("Record the next key combination"))
        self.record.add_css_class("flat")
        self.record.connect("toggled", self._toggle_capture)
        self.combo.add_suffix(self.record)
        g.add(self.combo)
        self.conflict_row = Adw.ActionRow(title="", css_classes=["error"])
        self.conflict_row.set_visible(False)
        g.add(self.conflict_row)
        page.add(g)

        keyctl = Gtk.EventControllerKey()
        keyctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keyctl.connect("key-pressed", self._on_key)
        keyctl.connect("key-released", self._on_key_released)
        self.add_controller(keyctl)

        # --- action
        g = Adw.PreferencesGroup(title=_("Action"))
        g.set_header_suffix(doc_button(ctx, f"{DOCS_SITE}/actions/", _("Action")))
        name, arg = split_action(action)
        if name and not any(a.name == name for a in self.actions):
            from ..umbriel import Action

            self.actions.append(Action(name, "<arg>" if arg else "", OTHER, _("unknown action")))
        labels = [f"{a.name}  —  {a.description}" for a in self.actions]
        self.action_row = Adw.ComboRow(title=_("Action"), model=Gtk.StringList.new(labels), enable_search=True)
        self.action_row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        idx = next((i for i, a in enumerate(self.actions) if a.name == name), 0)
        self.action_row.set_selected(idx)
        self.action_row.connect("notify::selected", lambda *_: self._sync_arg())
        g.add(self.action_row)
        self.arg_row = Adw.EntryRow(title=_("Argument"), text=arg, use_markup=True)
        g.add(self.arg_row)
        page.add(g)

        # --- options
        g = Adw.PreferencesGroup(title=_("Options"))
        self.repeat = Adw.SwitchRow(title=_("Repeat while held"), active=bool(self.opts["repeat"]))
        self.locked = Adw.SwitchRow(title=_("Also on the lock screen"), active=bool(self.opts["allow_when_locked"]))
        self.inhibited = Adw.SwitchRow(title=_("Also while shortcuts are inhibited"),
                                       active=bool(self.opts["allow_when_inhibited"]))
        self.cooldown = Adw.SpinRow.new_with_range(0, 3_600_000, 50)
        self.cooldown.set_title(_("Cooldown (ms)"))
        self.cooldown.set_value(float(self.opts["cooldown_ms"]))
        self.submap = Adw.EntryRow(title=_("Submap"), text=str(self.opts["submap"]))
        for w, heading in ((self.repeat, "Repeat"), (self.locked, "Allow when locked"),
                           (self.inhibited, "Keyboard shortcuts inhibition"), (self.cooldown, "Cooldown"),
                           (self.submap, "Submaps")):
            w.add_suffix(doc_button(ctx, section_url("keybinds", heading), heading))
            g.add(w)
        page.add(g)

        if key:
            g = Adw.PreferencesGroup()
            delete = Adw.ButtonRow(title=_("Delete keybind"))
            delete.add_css_class("destructive-action")
            delete.connect("activated", lambda *_: self._delete())
            g.add(delete)
            page.add(g)

        self._sync_arg()
        self._check_conflict()
        self.connect("closed", lambda *_: self._stop_capture())

    # ----------------------------------------------------------------- capture

    def _toggle_capture(self, btn):
        if btn.get_active():
            self._capturing = True
            self.combo.set_text("")
            self.combo.set_title(_("Press the key combination…"))
            surface = self.get_native().get_surface() if self.get_native() else None
            if isinstance(surface, Gdk.Toplevel):
                surface.inhibit_system_shortcuts(None)
        else:
            self._stop_capture()

    def _stop_capture(self):
        if not self._capturing:
            return
        self._capturing = False
        self.combo.set_title(_("Key combination"))
        self.record.set_active(False)
        surface = self.get_native().get_surface() if self.get_native() else None
        if isinstance(surface, Gdk.Toplevel):
            surface.restore_system_shortcuts()

    def _mods(self, state) -> list[str]:
        mods = []
        if state & Gdk.ModifierType.SUPER_MASK:
            mods.append("Mod")
        if state & Gdk.ModifierType.CONTROL_MASK:
            mods.append("Ctrl")
        if state & Gdk.ModifierType.ALT_MASK:
            mods.append("Alt")
        if state & Gdk.ModifierType.SHIFT_MASK:
            mods.append("Shift")
        return mods

    def _on_key(self, _ctl, keyval, _code, state):
        if not self._capturing:
            return False
        name = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or ""
        if name in MODIFIER_KEYVALS:
            self._lone_mod = name
            return True
        self._lone_mod = None
        if len(name) == 1:
            name = name.upper()
        else:
            name = name[:1].upper() + name[1:]
        self.combo.set_text("+".join(self._mods(state) + [name]))
        GLib.idle_add(lambda: self._stop_capture() and False)
        return True

    def _on_key_released(self, _ctl, keyval, _code, _state):
        if self._capturing and getattr(self, "_lone_mod", None) and Gdk.keyval_name(keyval) == self._lone_mod:
            if self._lone_mod.startswith("Super"):
                self.combo.set_text("Mod")
                GLib.idle_add(lambda: self._stop_capture() and False)
            self._lone_mod = None
        return False

    # ----------------------------------------------------------------- logic

    def _current_action(self):
        idx = self.action_row.get_selected()
        return self.actions[idx] if 0 <= idx < len(self.actions) else None

    def _sync_arg(self):
        a = self._current_action()
        takes = bool(a and a.takes_arg)
        self.arg_row.set_visible(takes)
        if a and takes:
            self.arg_row.set_title(esc(_("Argument {spec}").format(spec=a.arg)
                                       + (" " + _("(optional)") if not a.arg_required else "")))

    def _check_conflict(self):
        combo = self.combo.get_text().strip()
        binds = self.ctx.cfg.main.get(("keybinds",)) or {}
        norm = normalize_combo(combo) if combo else ""
        others = [k for k in binds if k != self.key and normalize_combo(k) == norm and norm]
        if others:
            action, _opts = parse_bind(binds[others[0]])
            self.conflict_row.set_title(esc(_("Already used: {key} → {action}").format(key=others[0], action=action)))
        self.conflict_row.set_visible(bool(others))

    def _save(self):
        combo = self.combo.get_text().strip()
        a = self._current_action()
        if not combo or a is None:
            self.ctx.toast(_("Enter a key and an action"))
            return
        arg = self.arg_row.get_text().strip() if a.takes_arg else ""
        if a.arg_required and not arg:
            self.ctx.toast(_("The action {action} needs an argument {spec}").format(action=a.name, spec=a.arg))
            return
        action = f"{a.name} {arg}" if arg else a.name
        opts = {
            "repeat": self.repeat.get_active(),
            "allow_when_locked": self.locked.get_active(),
            "allow_when_inhibited": self.inhibited.get_active(),
            "cooldown_ms": int(self.cooldown.get_value()),
            "submap": self.submap.get_text().strip(),
        }
        value = compose_bind(action, opts)
        tf = self.ctx.cfg.main
        binds = tf.get(("keybinds",)) or {}
        if combo != self.key and combo in binds:
            self.ctx.toast(_("{key} already exists – edit it there or delete it first").format(key=combo))
            return

        def do():
            if self.key and self.key in binds:
                tf.rename(("keybinds", self.key), combo, value)
            else:
                tf.set(("keybinds", combo), value)

        try:
            self.ctx.edit(tf, do)
        except KeyError as exc:
            self.ctx.toast(str(exc))
            return
        self.close()
        self.on_done()

    def _delete(self):
        self.ctx.delete(self.ctx.cfg.main, ("keybinds", self.key), prune=False)
        self.close()
        self.on_done()
