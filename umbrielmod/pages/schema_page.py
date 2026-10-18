"""Generic pages generated from the schema."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from ..config import TomlFile
from ..context import AppContext
from ..schema import Option, humanize
from ..widgets import add_option_button, esc, icon_button, option_row, zero_value

SECTION_TITLES = {
    "general": "Allgemein",
    "environment": "Umgebungsvariablen",
    "events": "Ereignisse",
    "screencast": "Bildschirmfreigabe",
    "include": "Eingebundene Dateien",
    "drm": "DRM / Grafikkarten",
    "input": "Eingabe",
    "appearance": "Darstellung",
    "colors": "Farben",
    "layout": "Layout",
    "workspaces": "Arbeitsbereiche",
    "workspace": "Arbeitsbereich-Regeln",
    "overview": "Übersicht",
    "hot_corners": "Aktive Ecken",
    "scratchpad": "Scratchpads",
    "animation": "Animationen",
    "window_rule": "Fensterregeln",
    "layer_rule": "Layer-Regeln",
    "security_context_rule": "Sicherheitskontext-Regeln",
    "effects": "Effekte",
    "input.device": "Geräte-spezifische Einstellungen",
    "animation.beziers": "Bézier-Kurven",
    "animation.springs": "Federkurven",
    "effects.pool": "Effekt-Pools",
}


def section_title(schema_path: str) -> str:
    if schema_path in SECTION_TITLES:
        return SECTION_TITLES[schema_path]
    return " › ".join(humanize(p.removesuffix("[]")) for p in schema_path.split("."))


def config_path(schema_prefix: str, config_prefix: tuple, leaf: Option) -> tuple:
    rest = leaf.path[len(schema_prefix) + 1:] if schema_prefix else leaf.path
    return config_prefix + tuple(rest.split("."))


def clear_page(page: Adw.PreferencesPage, groups: list) -> None:
    for g in groups:
        page.remove(g)
    groups.clear()


# --------------------------------------------------------------------------- leaves


def leaf_groups(ctx: AppContext, schema_prefix: str, config_prefix: tuple, *,
                tf: TomlFile | None = None, title: str | None = None,
                skip: set[str] = frozenset()) -> list[Adw.PreferencesGroup]:
    """One group per (sub)table with all its plain options."""
    by_parent: dict[str, list[Option]] = {}
    for opt in ctx.schema.leaves(schema_prefix):
        if opt.path in skip or any(opt.path.startswith(s + ".") for s in skip):
            continue
        by_parent.setdefault(opt.path.rsplit(".", 1)[0], []).append(opt)
    groups = []
    for parent in sorted(by_parent, key=lambda p: (p != schema_prefix, p)):
        g = Adw.PreferencesGroup()
        if parent == schema_prefix:
            g.set_title(esc(title or section_title(parent)))
        else:
            rel = parent[len(schema_prefix) + 1:] if schema_prefix else parent
            g.set_title(esc(section_title(parent) if parent in SECTION_TITLES else
                            " › ".join(humanize(p) for p in rel.split("."))))
        table_desc = ctx.docs.tables.get(parent.replace("[]", ""))
        if table_desc:
            g.set_description(esc(table_desc))
        for opt in by_parent[parent]:
            g.add(option_row(ctx, opt, config_path(schema_prefix, config_prefix, opt), tf))
        groups.append(g)
    return groups


# --------------------------------------------------------------------------- maps


class MapGroup(Adw.PreferencesGroup):
    """Editor for a TOML map such as ``[animation.beziers]``."""

    def __init__(self, ctx: AppContext, schema_path: str, path: tuple, tf: TomlFile | None = None):
        super().__init__(title=esc(section_title(schema_path)))
        self.ctx, self.schema_path, self.path = ctx, schema_path, path
        self.tf = tf or ctx.cfg.main
        self.value_opt = ctx.schema.options.get(f"{schema_path}.<name>")
        self.fields = ctx.schema.leaves(f"{schema_path}.<name>", stop_at_collections=False)
        desc = ctx.docs.describe(schema_path) or ctx.docs.describe(f"{schema_path}.<name>")
        if desc:
            self.set_description(esc(desc))
        self.set_header_suffix(self._add_button())
        self._rows: list[Gtk.Widget] = []
        self.refresh()

    def _add_button(self) -> Gtk.MenuButton:
        pop = Gtk.Popover()
        box = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        entry = Gtk.Entry(placeholder_text="Name")
        ok = Gtk.Button(label="Anlegen", css_classes=["suggested-action"])
        box.append(entry)
        box.append(ok)
        pop.set_child(box)

        def create(*_):
            name = entry.get_text().strip()
            if not name:
                return
            pop.popdown()
            entry.set_text("")
            self._create(name)

        ok.connect("clicked", create)
        entry.connect("activate", create)
        btn = Gtk.MenuButton(popover=pop, valign=Gtk.Align.CENTER, css_classes=["flat"])
        btn.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label="Hinzufügen"))
        return btn

    def _create(self, name: str):
        path = self.path + (name,)

        def do():
            if self.value_opt is not None and not self.value_opt.is_container:
                self.tf.set(path, zero_value(self.value_opt))
            else:
                for f in self.fields:
                    if not f.has_default:
                        rel = f.path.split("<name>.", 1)[1].split(".")
                        self.tf.set(path + tuple(rel), zero_value(f))
                if not self.tf.has(path):
                    self.tf.set(path, {})

        self.ctx.edit(self.tf, do)
        self.refresh()

    def refresh(self):
        for r in self._rows:
            self.remove(r)
        self._rows.clear()
        entries = self.tf.get(self.path) or {}
        foreign = {}
        if self.tf is self.ctx.cfg.main:
            for f in self.ctx.cfg.includes():
                for k in f.get(self.path) or {}:
                    foreign.setdefault(k, f)
        for name in entries:
            self._add_row(self._entry_row(name))
        for name, f in foreign.items():
            if name in entries:
                continue
            row = Adw.ActionRow(title=esc(name), subtitle=f"Aus {esc(f.path.name)} (schreibgeschützt)")
            row.set_sensitive(False)
            self._add_row(row)
        if not entries and not foreign:
            self._add_row(Adw.ActionRow(title="Keine Einträge", css_classes=["dim-label"]))

    def _add_row(self, row):
        self.add(row)
        self._rows.append(row)

    def _entry_row(self, name: str) -> Gtk.Widget:
        path = self.path + (name,)
        if self.value_opt is not None and not self.value_opt.is_container and self.value_opt.type != "string_or_table":
            return option_row(self.ctx, self.value_opt, path, self.tf, title=name)
        exp = Adw.ExpanderRow(title=esc(name))
        val = self.tf.get(path)
        if isinstance(val, dict):
            exp.set_subtitle(esc(", ".join(f"{k}={v}" for k, v in val.items()))[:200])

        def delete():
            self.ctx.delete(self.tf, path, prune=False)
            self.refresh()

        exp.add_suffix(icon_button("user-trash-symbolic", "Eintrag löschen", delete))
        for f in self.fields:
            rel = f.path.split("<name>.", 1)[1].split(".")
            exp.add_row(option_row(self.ctx, f, path + tuple(rel), self.tf))
        return exp


# --------------------------------------------------------------------------- arrays of tables


def _short(value) -> str:
    if isinstance(value, list):
        return " | ".join(_short(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def entry_summary(schema_path: str, entry: dict) -> tuple[str, str]:
    """(title, subtitle) describing one [[x]] entry."""
    match = entry.get("match") if isinstance(entry.get("match"), dict) else {}
    if match:
        title = " · ".join(f"{k} = {_short(v)}" for k, v in match.items())
    elif "name" in entry:
        title = str(entry["name"])
    elif schema_path.startswith("window_rule"):
        title = "Alle Fenster"
    elif schema_path.startswith("layer_rule"):
        title = "Alle Layer"
    else:
        title = "Eintrag"
    rest = [f"{k} = {_short(v)}" for k, v in entry.items() if k not in ("match", "name") and not isinstance(v, dict)]
    rest += [f"{k} = {{…}}" for k, v in entry.items() if k != "match" and isinstance(v, dict)]
    return title, ", ".join(rest)


class AoTGroup(Adw.PreferencesGroup):
    """Editor for an array of tables such as ``[[window_rule]]``.

    Each entry only lists the keys it sets; further keys are added from a
    searchable list of every option the schema allows.
    """

    def __init__(self, ctx: AppContext, schema_path: str, path: tuple, *, extra_header: Gtk.Widget | None = None,
                 template: dict | None = None):
        super().__init__(title=esc(section_title(schema_path)))
        self.ctx, self.schema_path, self.path = ctx, schema_path, path
        self.tf = ctx.cfg.main
        self.template = template or {}
        self.fields = ctx.schema.leaves(f"{schema_path}[]", stop_at_collections=False)
        self.expanded: set[int] = set()
        desc = ctx.docs.pages.get(schema_path.replace("_", "-") + "s", {}).get("intro")
        if desc:
            self.set_description(esc(desc))
        header = Gtk.Box(spacing=6)
        if extra_header is not None:
            header.append(extra_header)
        add = Gtk.Button(css_classes=["flat"], valign=Gtk.Align.CENTER)
        add.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label="Neu"))
        add.connect("clicked", lambda *_: self.add_entry(dict(self.template)))
        header.append(add)
        self.set_header_suffix(header)
        self._rows: list[Gtk.Widget] = []
        self.refresh()

    def add_entry(self, value: dict):
        idx_box = []

        def do():
            idx_box.append(self.tf.append_table(self.path, {}))
            for k, v in value.items():
                self.tf.set(self.path + (idx_box[0], k), v)

        self.ctx.edit(self.tf, do)
        self.expanded.add(idx_box[0])
        self.refresh()

    def refresh(self):
        for r in self._rows:
            self.remove(r)
        self._rows.clear()
        entries = self.tf.get(self.path) or []
        for i, entry in enumerate(entries):
            self._add(self._entry_row(i, entry, len(entries)))
        for f in self.ctx.cfg.includes():
            for entry in f.get(self.path) or []:
                title, sub = entry_summary(self.schema_path, entry)
                row = Adw.ActionRow(title=esc(title), subtitle=esc(f"{sub}\n(aus {f.path.name}, schreibgeschützt)"))
                row.set_sensitive(False)
                self._add(row)
        if not entries:
            self._add(Adw.ActionRow(title="Noch keine Einträge", css_classes=["dim-label"]))

    def _add(self, row):
        self.add(row)
        self._rows.append(row)

    def _entry_row(self, i: int, entry: dict, count: int) -> Gtk.Widget:
        title, sub = entry_summary(self.schema_path, entry)
        exp = Adw.ExpanderRow(title=f"{i + 1}. {esc(title)}", subtitle=esc(sub[:240]))
        exp.set_subtitle_lines(2)
        exp.set_expanded(i in self.expanded)
        exp.connect("notify::expanded", lambda r, *_: (self.expanded.add(i) if r.get_expanded() else self.expanded.discard(i)))

        def move(delta: int):
            j = i + delta
            self.ctx.edit(self.tf, lambda: self.tf.move_table(self.path, i, j))
            if i in self.expanded:
                self.expanded.discard(i)
                self.expanded.add(j)
            self.refresh()

        def delete():
            self.ctx.edit(self.tf, lambda: self.tf.delete(self.path + (i,)))
            self.expanded = {j - (j > i) for j in self.expanded if j != i}
            self.refresh()

        def duplicate():
            self.add_entry(dict(entry))

        up = icon_button("go-up-symbolic", "Nach oben (frühere Regeln werden überschrieben)", lambda: move(-1))
        up.set_sensitive(i > 0)
        down = icon_button("go-down-symbolic", "Nach unten", lambda: move(1))
        down.set_sensitive(i < count - 1)
        for w in (up, down, icon_button("edit-copy-symbolic", "Duplizieren", duplicate),
                  icon_button("user-trash-symbolic", "Löschen", delete)):
            exp.add_suffix(w)

        set_fields, unset = [], []
        for f in self.fields:
            rel = tuple(f.path.split("[].", 1)[1].split("."))
            (set_fields if self.tf.has(self.path + (i,) + rel) else unset).append((f, rel))
        for f, rel in set_fields:
            title = " › ".join(humanize(p) for p in rel)
            exp.add_row(option_row(self.ctx, f, self.path + (i,) + rel, self.tf, title=title))

        def pick(opt: Option):
            rel = tuple(opt.path.split("[].", 1)[1].split("."))
            self.ctx.set(self.tf, self.path + (i,) + rel, zero_value(opt))
            self.expanded.add(i)
            GLib.idle_add(lambda: self.refresh() and False)

        add_row = Adw.ActionRow(title="Weitere Option…")
        add_row.add_suffix(add_option_button(self.ctx, [f for f, _ in unset], pick, label="Hinzufügen"))
        exp.add_row(add_row)
        return exp


# --------------------------------------------------------------------------- page


class SchemaPage(Adw.PreferencesPage):
    """All options of one or more top-level sections, generated from the schema."""

    def __init__(self, ctx: AppContext, sections: list[str], *, skip_collections: set[str] = frozenset(),
                 description: str = ""):
        super().__init__()
        self.ctx = ctx
        self.sections = sections
        self.skip = set(skip_collections)
        self.description = description
        self._groups: list = []
        self.refresh()

    def refresh(self):
        clear_page(self, self._groups)
        if self.description:
            intro = Adw.PreferencesGroup(description=esc(self.description))
            self._push(intro)
        for section in self.sections:
            opt = self.ctx.schema.options.get(section)
            if opt is not None and opt.type == "array_of_tables":
                self._push(AoTGroup(self.ctx, section, (section,)))
                continue
            if opt is not None and opt.type == "map":
                self._push(MapGroup(self.ctx, section, (section,)))
                continue
            for g in leaf_groups(self.ctx, section, (section,)):
                self._push(g)
            for coll in self.ctx.schema.collections(section):
                if coll.path in self.skip:
                    continue
                cpath = tuple(coll.path.split("."))
                if coll.type == "map":
                    self._push(MapGroup(self.ctx, coll.path, cpath))
                else:
                    self._push(AoTGroup(self.ctx, coll.path, cpath))

    def _push(self, group):
        self.add(group)
        self._groups.append(group)
