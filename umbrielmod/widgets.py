"""Schema-driven preference rows.

``option_row()`` returns a libadwaita row for any schema option. Rows show the
default when a key is unset, write on change, and offer a reset button that
removes the key again so Umbriel's default applies.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from . import shaders  # noqa: E402
from .i18n import _  # noqa: E402
from .config import TomlFile, parse_literal, toml_literal  # noqa: E402
from .context import AppContext  # noqa: E402
from .schema import Option, humanize  # noqa: E402

_MISSING = object()
BUILTIN_CURVES = ("linear", "ease", "easeout", "snappy", "bounce", "elastic")
INT_LIMIT = 2_147_483_647


def esc(text: str) -> str:
    return GLib.markup_escape_text(str(text))


# --------------------------------------------------------------------------- small widgets


def doc_button(ctx: AppContext, url: str | None, what: str = "") -> Gtk.Button:
    """The round (?) button that opens the Umbriel documentation."""
    btn = Gtk.Button(label="?", valign=Gtk.Align.CENTER, css_classes=["doc-link"])
    if url:
        btn.set_tooltip_text(_("Open the Umbriel documentation") + (f" – {what}" if what else "") + f"\n{url}")
        btn.connect("clicked", lambda *_: ctx.open_uri(url))
    else:
        btn.add_css_class("missing")
        btn.set_sensitive(False)
    return btn


def option_doc_url(ctx: AppContext, opt: Option) -> str:
    return ctx.docs.url(opt.path) or ctx.docs.page_url(opt.path)


def icon_button(icon: str, tooltip: str, callback: Callable, *, flat: bool = True) -> Gtk.Button:
    btn = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    if flat:
        btn.add_css_class("flat")
    btn.connect("clicked", lambda *_: callback())
    return btn


class SuggestButton(Gtk.MenuButton):
    """A drop-down button offering values (with optional descriptions)."""

    def __init__(self, items: Callable[[], list[tuple[str, str]]], on_pick: Callable[[str], None]):
        super().__init__(icon_name="pan-down-symbolic", valign=Gtk.Align.CENTER, tooltip_text=_("Suggestions"))
        self.add_css_class("flat")
        self._items = items
        self._on_pick = on_pick
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._search = Gtk.SearchEntry(placeholder_text=_("Search…"))
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("navigation-sidebar")
        self._list.connect("row-activated", self._activated)
        scroller = Gtk.ScrolledWindow(min_content_height=60, max_content_height=360, propagate_natural_height=True,
                                      min_content_width=320, propagate_natural_width=True)
        scroller.set_child(self._list)
        box.append(self._search)
        box.append(scroller)
        pop.set_child(box)
        self.set_popover(pop)
        self._search.connect("search-changed", lambda *_: self._list.invalidate_filter())
        self._list.set_filter_func(self._filter)
        pop.connect("show", lambda *_: self._populate())

    def _populate(self):
        while (row := self._list.get_row_at_index(0)) is not None:
            self._list.remove(row)
        for value, desc in self._items():
            row = Gtk.ListBoxRow()
            row.value = value
            row.haystack = f"{value} {desc}".lower()
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=2, margin_bottom=2)
            lbl = Gtk.Label(label=value, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            vb.append(lbl)
            if desc:
                d = Gtk.Label(label=desc, xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=50)
                d.add_css_class("dim-label")
                d.add_css_class("caption")
                vb.append(d)
            row.set_child(vb)
            self._list.append(row)
        self._search.set_text("")
        self._search.grab_focus()

    def _filter(self, row) -> bool:
        q = self._search.get_text().lower().strip()
        return not q or all(part in row.haystack for part in q.split())

    def _activated(self, _lb, row):
        self.get_popover().popdown()
        self._on_pick(row.value)


def rgba_from_string(text: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    if not rgba.parse(text or "#00000000"):
        rgba.parse("#000000")
    return rgba


def rgba_to_string(rgba: Gdk.RGBA) -> str:
    def c(v: float) -> str:
        return f"{max(0, min(255, round(v * 255))):02X}"

    return f"#{c(rgba.red)}{c(rgba.green)}{c(rgba.blue)}{c(rgba.alpha)}"


# --------------------------------------------------------------------------- suggestions


def suggestions(ctx: AppContext, opt: Option) -> list[tuple[str, str]] | None:
    fmt = opt.format
    if fmt == "effect":
        kind, pools, off = shaders.kind_for_option(opt.path)
        names = shaders.suggestions_for(ctx.cfg, kind, pools=pools, off=off)
        kinds = {**shaders.preset_names(ctx.cfg), **shaders.pool_names(ctx.cfg)}
        return [(n, _("suppress") if n == "off" else kinds.get(n, "")) for n in names]
    if fmt == "curve":
        out = [(c, _("built-in")) for c in BUILTIN_CURVES]
        for f in ctx.cfg.files:
            out += [(n, _("Bézier")) for n in (f.get(("animation", "beziers")) or {})]
            out += [(n, _("Spring")) for n in (f.get(("animation", "springs")) or {})]
        out.append(("spring:1.0,800", _("Spring: damping, stiffness")))
        out.append(("0.05,0.9,0.1,1.0", _("Bézier curve")))
        return out
    if fmt == "action":
        return [(a.name + (":" if a.takes_arg else ""), a.description) for a in ctx.actions]
    if opt.values:
        return [(v, "") for v in opt.values]
    if fmt == "output_mode":
        from . import umbriel

        out = []
        for o in umbriel.outputs():
            out += [(m.config_string(), f"{o.name}: {m.label()}") for m in o.modes]
        return out
    return None


# --------------------------------------------------------------------------- option rows


class OptionBinding:
    """Where an option row reads and writes its value."""

    def __init__(self, ctx: AppContext, opt: Option, path: tuple, tf: TomlFile | None = None):
        self.ctx, self.opt, self.path = ctx, opt, path
        self.tf = tf or ctx.cfg.main
        self.foreign: TomlFile | None = None
        if self.tf is ctx.cfg.main and not self.tf.has(path):
            definers = [f for f in ctx.cfg.definers(path) if f is not self.tf]
            self.foreign = definers[-1] if definers else None

    @property
    def is_set(self) -> bool:
        return self.tf.has(self.path)

    def value(self, default=_MISSING):
        if self.tf.has(self.path):
            return self.tf.get(self.path)
        if self.foreign is not None:
            return self.foreign.get(self.path)
        if default is not _MISSING:
            return default
        return self.opt.default if self.opt.has_default else None

    def set(self, value) -> None:
        self.ctx.set(self.tf, self.path, value)

    def reset(self) -> None:
        self.ctx.delete(self.tf, self.path)


def _subtitle(ctx: AppContext, b: OptionBinding) -> str:
    desc = ctx.docs.describe(b.opt.path)
    parts = []
    if desc:
        parts.append(esc(desc))
    if b.foreign is not None:
        parts.append("<i>" + esc(_("Set in {file}").format(file=b.foreign.path.name)) + "</i>")
    elif not b.is_set:
        if b.opt.has_default and b.opt.default not in ("", [], None):
            parts.append("<small>" + esc(_("Default: {value}").format(value=_fmt(b.opt.default))) + "</small>")
        elif not b.opt.has_default and b.opt.type in ("int", "float", "bool"):
            parts.append("<small>" + esc(_("Not set – Umbriel decides")) + "</small>")
    return "\n".join(parts)


def _fmt(value) -> str:
    if isinstance(value, str):
        return value
    return toml_literal(value)


def _tooltip(ctx: AppContext, b: OptionBinding) -> str:
    lines = [f"<tt>{esc('.'.join(str(p) for p in b.path))}</tt>  ({esc(b.opt.type)})"]
    if b.opt.min is not None or b.opt.max is not None:
        lines.append(_("Range: {min} – {max}").format(min=b.opt.min, max=b.opt.max))
    if b.opt.has_default:
        lines.append(esc(_("Default: {value}").format(value=_fmt(b.opt.default))))
    info = ctx.docs.options.get(b.opt.path, {})
    if info.get("inherited"):
        lines.append("<i>" + esc(_("Description taken from {path}").format(path=info["inherited"])) + "</i>")
    return "\n".join(lines)


def _decorate(ctx: AppContext, row: Adw.PreferencesRow, b: OptionBinding, refresh: Callable[[], None]):
    """Add reset + docs buttons and common texts to a row."""
    row.set_tooltip_markup(_tooltip(ctx, b))
    if isinstance(row, Adw.ActionRow):
        sub = _subtitle(ctx, b)
        row.set_subtitle(sub)
        row.set_subtitle_lines(3)
        row.set_use_markup(True)
    reset = icon_button("edit-undo-symbolic", _("Reset to default (removes the key)"), lambda: (b.reset(), refresh()))
    reset.set_visible(b.is_set)
    docs = doc_button(ctx, option_doc_url(ctx, b.opt), b.opt.key)
    if isinstance(row, (Adw.ActionRow, Adw.ExpanderRow)):
        row.add_suffix(reset)
        row.add_suffix(docs)
    if b.foreign is not None:
        row.set_sensitive(False)
    return reset


def option_row(ctx: AppContext, opt: Option, path: tuple, tf: TomlFile | None = None,
               title: str | None = None) -> Gtk.Widget:
    """Build an editable row for ``opt`` stored at ``path``."""
    return _Rebuildable(ctx, opt, path, tf, title).row


class _Rebuildable:
    """Builds a row and swaps it for a fresh one after a reset."""

    def __init__(self, ctx, opt, path, tf, title):
        self.ctx, self.opt, self.path, self.tf, self.title = ctx, opt, path, tf, title
        self.row = self._build()

    def _build(self):
        b = OptionBinding(self.ctx, self.opt, self.path, self.tf)
        return _make_row(self.ctx, b, self.title or humanize(self.opt.key), self.rebuild)

    def rebuild(self):
        parent = self.row.get_parent()
        if not isinstance(parent, Gtk.ListBox):
            return
        idx = self.row.get_index()
        new = self._build()
        parent.remove(self.row)
        parent.insert(new, idx)
        self.row = new


def _make_row(ctx: AppContext, b: OptionBinding, title: str, rebuild: Callable[[], None]) -> Adw.PreferencesRow:
    opt = b.opt
    t = opt.type

    def refresh():
        GLib.idle_add(lambda: rebuild() and False)

    if t == "bool":
        row = Adw.SwitchRow(title=esc(title))
        row.set_active(bool(b.value()))
        reset = _decorate(ctx, row, b, refresh)

        def on_bool(*_):
            b.set(row.get_active())
            reset.set_visible(True)

        row.connect("notify::active", on_bool)
        return row

    if t in ("int", "float"):
        lo = opt.min if opt.min is not None else -1e6
        hi = opt.max if opt.max is not None else 1e6
        lo, hi = max(lo, -INT_LIMIT), min(hi, INT_LIMIT)
        if t == "int":
            step, digits = 1, 0
        else:
            span = hi - lo
            step, digits = (0.01, 3) if span <= 2 else (0.05, 2) if span <= 20 else (1, 1)
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(esc(title))
        row.set_digits(digits)
        val = b.value()
        row.set_value(float(val) if isinstance(val, (int, float)) else max(lo, min(hi, 0)))
        reset = _decorate(ctx, row, b, refresh)

        def on_num(*_):
            v = row.get_value()
            b.set(int(round(v)) if t == "int" else round(v, 6))
            reset.set_visible(True)

        row.connect("notify::value", on_num)
        return row

    if t == "enum":
        default = opt.default if opt.has_default else None
        first = _("Default ({value})").format(value=default) if default is not None else _("Not set")
        items = [first, *opt.values]
        row = Adw.ComboRow(title=esc(title), model=Gtk.StringList.new(items), use_markup=True)
        cur = b.tf.get(b.path) if b.is_set else (b.value() if b.foreign else None)
        row.set_selected(items.index(cur) if cur in items[1:] else 0)
        reset = _decorate(ctx, row, b, refresh)
        reset.set_visible(False)  # the "Default" entry replaces the reset button

        def on_enum(*_):
            idx = row.get_selected()
            if idx == 0:
                if b.is_set:
                    b.reset()
            else:
                b.set(items[idx])

        row.connect("notify::selected", on_enum)
        return row

    if t == "color":
        row = Adw.ActionRow(title=esc(title))
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True), valign=Gtk.Align.CENTER)
        val = b.value()
        btn.set_rgba(rgba_from_string(val if isinstance(val, str) else "#00000000"))
        hexlbl = Gtk.Label(label=val or "—", css_classes=["dim-label", "monospace"])
        row.add_suffix(hexlbl)
        row.add_suffix(btn)
        reset = _decorate(ctx, row, b, refresh)

        def on_color(*_):
            s = rgba_to_string(btn.get_rgba())
            hexlbl.set_label(s)
            b.set(s)
            reset.set_visible(True)

        btn.connect("notify::rgba", on_color)
        return row

    if t == "string_array":
        return _string_list_row(ctx, b, title, refresh)

    # strings and everything else go through an entry
    literal = t != "string"
    row = Adw.ActionRow(title=esc(title))
    entry = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=18)
    val = b.value()
    if b.is_set or b.foreign is not None:
        entry.set_text(_fmt(val) if not literal else toml_literal(val))
    elif opt.has_default and opt.default not in ("", None):
        entry.set_placeholder_text(_fmt(opt.default) if not literal else toml_literal(opt.default))
    if literal:
        entry.add_css_class("monospace")
        entry.set_tooltip_text(_("TOML value, e.g. \"text\", 1.5, [1, 2] or { a = 1 }"))
    row.add_suffix(entry)
    sugg = suggestions(ctx, opt)
    if sugg is not None:
        def pick(value: str):
            if literal:
                entry.set_text(toml_literal(value))
            else:
                entry.set_text(value)
            entry.grab_focus()
            entry.set_position(-1)

        row.add_suffix(SuggestButton(lambda: suggestions(ctx, opt) or [], pick))
    reset = _decorate(ctx, row, b, refresh)

    def on_text(*_):
        text = entry.get_text()
        if text == "":
            if b.is_set:
                b.reset()
                reset.set_visible(False)
            entry.remove_css_class("error")
            return
        if literal:
            try:
                value = parse_literal(text)
            except ValueError:
                entry.add_css_class("error")
                return
        else:
            value = text
        entry.remove_css_class("error")
        b.set(value)
        reset.set_visible(True)

    entry.connect("changed", on_text)
    return row


def _string_list_row(ctx: AppContext, b: OptionBinding, title: str, refresh) -> Adw.PreferencesRow:
    row = Adw.ExpanderRow(title=esc(title))
    values = list(b.value([]) or [])
    row.set_subtitle(esc(", ".join(values)) if values else (esc(ctx.docs.describe(b.opt.path)) or _("empty")))
    row.set_subtitle_lines(2)
    row.set_tooltip_markup(_tooltip(ctx, b))
    reset = icon_button("edit-undo-symbolic", _("Reset to default (removes the key)"), lambda: (b.reset(), refresh()))
    reset.set_visible(b.is_set)
    row.add_suffix(reset)
    row.add_suffix(doc_button(ctx, option_doc_url(ctx, b.opt), b.opt.key))
    if b.foreign is not None:
        row.set_sensitive(False)
    sugg = suggestions(ctx, b.opt)

    def commit():
        b.set([v for v in values])
        row.set_subtitle(esc(", ".join(values)) or _("empty"))
        reset.set_visible(True)

    def add_item_row(i: int):
        er = Adw.EntryRow(title=_("Entry {n}").format(n=i + 1))
        er.set_text(values[i])

        def changed(*_):
            values[i] = er.get_text()
            commit()

        er.connect("changed", changed)

        def remove():
            values.pop(i)
            commit()
            refresh()

        er.add_suffix(icon_button("list-remove-symbolic", _("Remove"), remove))
        row.add_row(er)

    for i in range(len(values)):
        add_item_row(i)

    add = Adw.ActionRow(title=_("Add entry"), activatable=True)
    add.add_prefix(Gtk.Image(icon_name="list-add-symbolic"))

    def add_item(value: str = ""):
        values.append(value)
        commit()
        refresh()

    add.connect("activated", lambda *_: add_item())
    if sugg is not None:
        add.add_suffix(SuggestButton(lambda: suggestions(ctx, b.opt) or [], add_item))
    row.add_row(add)
    return row


# --------------------------------------------------------------------------- helpers for groups


def zero_value(opt: Option):
    """A reasonable initial value when the user adds an unset option."""
    if opt.has_default:
        return opt.default
    return {
        "bool": True,
        "int": int(opt.min) if opt.min is not None and opt.min > 0 else 0,
        "float": float(opt.min) if opt.min is not None and opt.min > 0 else 1.0,
        "enum": opt.values[0] if opt.values else "",
        "color": "#FFFFFFFF",
        "string_array": [],
        "float_array": [],
        "int_array": [],
    }.get(opt.type, opt.values[0] if opt.values else "")


def add_option_button(ctx: AppContext, options: list[Option], on_pick: Callable[[Option], None],
                      label: str | None = None) -> Gtk.MenuButton:
    by_path = {o.path: o for o in options}

    def items():
        return [(o.path.split("[].", 1)[-1].split("<name>.", 1)[-1], ctx.docs.describe(o.path)) for o in options]

    def pick(display: str):
        for p, o in by_path.items():
            if p.endswith(display):
                on_pick(o)
                return

    btn = SuggestButton(items, pick)
    btn.set_icon_name("")
    btn.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label=label or _("Add option")))
    return btn
