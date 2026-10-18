"""Outputs: drag-and-drop arrangement plus per-output settings."""

from __future__ import annotations

import math

from gi.repository import Adw, GLib, Gtk

from .. import umbriel
from ..context import AppContext
from ..widgets import esc, option_row
from .schema_page import config_path

SNAP = 40  # logical pixels


class Arrangement(Gtk.DrawingArea):
    """Outputs drawn as rectangles in logical coordinates; drag to move."""

    def __init__(self, on_moved):
        super().__init__(content_height=240, hexpand=True)
        self.on_moved = on_moved
        self.rects: dict[str, list[float]] = {}  # name -> [x, y, w, h]
        self.labels: dict[str, str] = {}
        self._drag: str | None = None
        self._origin = (0.0, 0.0)
        self._view = (1.0, 0.0, 0.0)
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.add_controller(drag)

    def set_outputs(self, rects: dict, labels: dict):
        self.rects = {k: list(v) for k, v in rects.items()}
        self.labels = labels
        self.queue_draw()

    def _bounds(self):
        xs = [r[0] for r in self.rects.values()] + [r[0] + r[2] for r in self.rects.values()]
        ys = [r[1] for r in self.rects.values()] + [r[1] + r[3] for r in self.rects.values()]
        return min(xs), min(ys), max(xs), max(ys)

    def _compute_view(self, w, h):
        if not self.rects:
            return 1.0, 0.0, 0.0
        x0, y0, x1, y1 = self._bounds()
        pad = 0.25
        bw, bh = (x1 - x0) * (1 + 2 * pad) or 1, (y1 - y0) * (1 + 2 * pad) or 1
        scale = min(w / bw, h / bh)
        ox = (w - (x1 - x0) * scale) / 2 - x0 * scale
        oy = (h - (y1 - y0) * scale) / 2 - y0 * scale
        return scale, ox, oy

    def _draw(self, _area, cr, w, h):
        if self._drag is None:
            self._view = self._compute_view(w, h)
        scale, ox, oy = self._view
        fg = self.get_color()
        for name, (x, y, rw, rh) in self.rects.items():
            sx, sy, sw, sh = ox + x * scale, oy + y * scale, rw * scale, rh * scale
            active = name == self._drag
            cr.set_source_rgba(0.21, 0.52, 0.89, 0.55 if active else 0.35)
            cr.rectangle(sx, sy, sw, sh)
            cr.fill_preserve()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.8)
            cr.set_line_width(2)
            cr.stroke()
            cr.select_font_face("Sans")
            cr.set_font_size(13)
            text = self.labels.get(name, name)
            ext = cr.text_extents(name)
            cr.move_to(sx + (sw - ext.width) / 2, sy + sh / 2)
            cr.show_text(name)
            cr.set_font_size(11)
            ext2 = cr.text_extents(text)
            cr.move_to(sx + (sw - ext2.width) / 2, sy + sh / 2 + 16)
            cr.show_text(text)

    def _hit(self, px, py):
        scale, ox, oy = self._view
        for name, (x, y, w, h) in reversed(list(self.rects.items())):
            if ox + x * scale <= px <= ox + (x + w) * scale and oy + y * scale <= py <= oy + (y + h) * scale:
                return name
        return None

    def _begin(self, _g, x, y):
        self._drag = self._hit(x, y)
        if self._drag:
            r = self.rects[self._drag]
            self._origin = (r[0], r[1])

    def _update(self, _g, dx, dy):
        if not self._drag:
            return
        scale = self._view[0]
        r = self.rects[self._drag]
        r[0] = self._origin[0] + dx / scale
        r[1] = self._origin[1] + dy / scale
        self._snap(self._drag)
        self.queue_draw()

    def _snap(self, name):
        r = self.rects[name]
        best_x, best_y = None, None
        for other, (x, y, w, h) in self.rects.items():
            if other == name:
                continue
            for cand in (x - r[2], x + w, x, x + w - r[2]):
                if abs(cand - r[0]) < SNAP and (best_x is None or abs(cand - r[0]) < abs(best_x - r[0])):
                    best_x = cand
            for cand in (y - r[3], y + h, y, y + h - r[3]):
                if abs(cand - r[1]) < SNAP and (best_y is None or abs(cand - r[1]) < abs(best_y - r[1])):
                    best_y = cand
        if best_x is not None:
            r[0] = best_x
        if best_y is not None:
            r[1] = best_y

    def _end(self, *_):
        name = self._drag
        self._drag = None
        if not name:
            return
        # normalise so the top-left output sits at 0,0
        x0, y0, *_ = self._bounds()
        for r in self.rects.values():
            r[0], r[1] = r[0] - x0, r[1] - y0
        self.queue_draw()
        self.on_moved({k: (round(v[0]), round(v[1])) for k, v in self.rects.items()})


class OutputsPage(Adw.PreferencesPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._groups: list = []
        self.refresh()

    def _config_key(self, out: umbriel.Output) -> str:
        """Name of the [output.X] table for a connected output."""
        outputs_cfg = self.ctx.cfg.main.get(("output",)) or {}
        for candidate in (out.name, out.config_name, out.description):
            if candidate and candidate in outputs_cfg:
                return candidate
        return out.name

    def refresh(self):
        for g in self._groups:
            self.remove(g)
        self._groups.clear()
        live = umbriel.outputs()
        tf = self.ctx.cfg.main

        arr_group = Adw.PreferencesGroup(
            title="Anordnung",
            description="Ziehen zum Verschieben; Kanten rasten ein. Positionen sind logische Pixel (nach Skalierung).",
        )
        self.arrangement = Arrangement(self._moved)
        frame = Gtk.Frame(child=self.arrangement)
        arr_group.add(frame)
        self._push(arr_group)

        rects, labels = {}, {}
        self._keys = {}
        for out in live:
            key = self._config_key(out)
            self._keys[out.name] = key
            pos = tf.get(("output", key, "position")) or list(out.position)
            scale = tf.get(("output", key, "scale")) or out.scale
            mode = out.current_mode
            mw, mh = (mode.width, mode.height) if mode else (1920, 1080)
            if out.transform in ("90", "270", "flipped-90", "flipped-270"):
                mw, mh = mh, mw
            rects[out.name] = (pos[0], pos[1], mw / scale, mh / scale)
            labels[out.name] = f"{math.floor(mw / scale)}×{math.floor(mh / scale)} @ {scale:g}"
        self.arrangement.set_outputs(rects, labels)
        if len(live) < 2:
            arr_group.set_description(arr_group.get_description() + " Nur ein Bildschirm angeschlossen.")

        leaves = [o for o in self.ctx.schema.leaves("output.<name>", stop_at_collections=False)]
        handled = set()
        for out in live:
            key = self._keys[out.name]
            handled.add(key)
            g = Adw.PreferencesGroup(title=esc(out.name), description=esc(out.description))
            g.add(self._mode_row(out, key))
            for opt in leaves:
                if opt.path.endswith((".mode",)):
                    continue
                g.add(option_row(self.ctx, opt, config_path("output.<name>", ("output", key), opt)))
            self._push(g)

        for key in (tf.get(("output",)) or {}):
            if key in handled:
                continue
            g = Adw.PreferencesGroup(title=esc(key), description="Nicht angeschlossen – Einstellungen bleiben erhalten.")
            for opt in leaves:
                g.add(option_row(self.ctx, opt, config_path("output.<name>", ("output", key), opt)))
            self._push(g)

    def _mode_row(self, out: umbriel.Output, key: str) -> Adw.ComboRow:
        tf = self.ctx.cfg.main
        path = ("output", key, "mode")
        current = tf.get(path)
        values = [None] + [m.config_string() for m in out.modes]
        labels = ["Automatisch (bevorzugter Modus)"] + [m.label() for m in out.modes]
        if current and current not in values:
            values.append(current)
            labels.append(f"{current} (aus Config)")
        row = Adw.ComboRow(title="Modus", model=Gtk.StringList.new(labels), use_markup=True)
        row.set_subtitle(esc(self.ctx.docs.describe("output.<name>.mode") or "Auflösung und Bildwiederholrate"))
        row.set_subtitle_lines(2)
        row.set_selected(values.index(current) if current in values else 0)

        def changed(*_):
            v = values[row.get_selected()]
            if v is None:
                if tf.has(path):
                    self.ctx.delete(tf, path)
            else:
                self.ctx.set(tf, path, v)

        row.connect("notify::selected", changed)
        return row

    def _moved(self, positions: dict):
        tf = self.ctx.cfg.main

        def do():
            for name, (x, y) in positions.items():
                tf.set(("output", self._keys.get(name, name), "position"), [x, y])

        self.ctx.edit(tf, do)
        self.ctx.toast("Positionen aktualisiert – noch nicht gespeichert")
        GLib.idle_add(lambda: self.refresh() and False)

    def _push(self, g):
        self.add(g)
        self._groups.append(g)
