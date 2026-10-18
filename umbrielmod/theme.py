"""Noctalia look and feel.

* Colours: Noctalia generates a GTK 4 stylesheet from the active palette
  (``~/.config/gtk-4.0/noctalia.css``). We load it explicitly – so it also
  applies when ``gtk.css`` does not import it – and reload it whenever
  Noctalia rewrites it (wallpaper or palette change). Without Noctalia, a v4
  ``colors.json`` palette or libadwaita's defaults are used.
* Shapes: radii, spacing and control heights follow Noctalia's
  ``src/ui/style.h`` (radius 3/6/9/12, spacing 4/8/12/16, controls 38 px).
* Icons: Noctalia's Tabler icon font, loaded at runtime from the Noctalia
  installation; symbolic GTK icons are the fallback.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

TABLER_FONT = Path("/usr/share/noctalia/assets/fonts/noctalia-tabler.ttf")
TABLER_MAP = Path("/usr/share/noctalia/assets/fonts/tabler.json")
TABLER_FAMILY = "noctalia-tabler-icons"


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def noctalia_gtk_css() -> Path:
    return _config_home() / "gtk-4.0" / "noctalia.css"


def noctalia_v4_colors() -> Path:
    return _config_home() / "noctalia" / "colors.json"


# Noctalia style.h tokens
STRUCTURE_CSS = """
/* ---- Noctalia geometry (src/ui/style.h) ---- */
window, .background { font-size: 14px; }
.boxed-list, .card, list.boxed-list { border-radius: 12px; }
button, entry, spinbutton, dropdown > button, menubutton > button { border-radius: 9px; }
button:not(.flat):not(.circular):not(.pill), entry { min-height: 34px; }
button.pill { border-radius: 999px; }
popover > contents { border-radius: 12px; }
row.activatable:hover { background-color: alpha(@accent_bg_color, 0.08); }

/* sidebar: rounded items, active item filled with the primary colour */
.navigation-sidebar { padding: 6px 8px; }
.navigation-sidebar > row { border-radius: 9px; min-height: 38px; margin: 2px 0; padding: 0 6px; }
.navigation-sidebar > row:hover:not(:selected) { background-color: alpha(@accent_bg_color, 0.12); }
.navigation-sidebar > row:selected,
.navigation-sidebar > row:selected:hover {
  background-color: @accent_bg_color;
  color: @accent_fg_color;
}
.navigation-sidebar > row:selected .dim-label { color: @accent_fg_color; }

/* group headers in the accent colour, like Noctalia's section titles */
preferencesgroup > box > box.header > box.labels > label.heading {
  color: @accent_color;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.03em;
}

/* (?) documentation buttons */
button.doc-link {
  min-width: 22px; min-height: 22px; padding: 0;
  border-radius: 999px;
  border: 1px solid alpha(currentColor, 0.28);
  background: none;
  font-weight: 700; font-size: 12px;
  color: alpha(currentColor, 0.75);
}
button.doc-link:hover {
  background-color: @accent_bg_color;
  color: @accent_fg_color;
  border-color: @accent_bg_color;
}
button.doc-link.missing { opacity: 0.45; }

/* Tabler icon glyphs */
label.tabler { font-family: "noctalia-tabler-icons"; font-size: 18px; min-width: 20px; }
label.tabler.small { font-size: 16px; }

.keycap {
  font-family: monospace;
  font-size: 0.9em;
  padding: 1px 7px;
  border-radius: 6px;
  background-color: alpha(currentColor, 0.07);
  border: 1px solid alpha(currentColor, 0.22);
  box-shadow: inset 0 -2px alpha(currentColor, 0.12);
}
.effect-card { padding: 8px; border-radius: 12px; }
.effect-card picture { border-radius: 9px; }
flowboxchild:hover .effect-card { background-color: alpha(@accent_bg_color, 0.10); }
.kind-badge {
  font-size: 0.8em; font-weight: 600;
  padding: 1px 8px; border-radius: 999px;
  background-color: alpha(@accent_bg_color, 0.18);
  color: @accent_color;
}
"""


def _v4_palette_css(path: Path) -> str:
    """@define-color rules from a Noctalia v4 ``colors.json`` palette."""
    try:
        c = json.loads(path.read_text())
    except (OSError, ValueError):
        return ""
    pairs = {
        "accent_color": "mPrimary", "accent_bg_color": "mPrimary", "accent_fg_color": "mOnPrimary",
        "destructive_bg_color": "mError", "destructive_fg_color": "mOnError",
        "error_color": "mError", "window_bg_color": "mSurface", "window_fg_color": "mOnSurface",
        "view_bg_color": "mSurface", "view_fg_color": "mOnSurface",
        "headerbar_bg_color": "mSurface", "headerbar_fg_color": "mOnSurface",
        "sidebar_bg_color": "mSurfaceVariant", "sidebar_fg_color": "mOnSurface",
        "card_bg_color": "mSurfaceVariant", "card_fg_color": "mOnSurface",
        "popover_bg_color": "mSurfaceVariant", "popover_fg_color": "mOnSurface",
        "dialog_bg_color": "mSurfaceVariant", "dialog_fg_color": "mOnSurface",
    }
    return "\n".join(f"@define-color {k} {c[v]};" for k, v in pairs.items() if v in c)


def _is_dark(css: str) -> bool | None:
    import re

    m = re.search(r"@define-color\s+window_bg_color\s+#([0-9a-fA-F]{6})", css)
    if not m:
        return None
    r, g, b = (int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 0.5


class Theme:
    """Installs the Noctalia styling and keeps the palette live."""

    def __init__(self, display: Gdk.Display):
        self.display = display
        self.structure = Gtk.CssProvider()
        self.structure.load_from_string(STRUCTURE_CSS)
        Gtk.StyleContext.add_provider_for_display(display, self.structure, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.palette = Gtk.CssProvider()
        # just below user gtk.css so manual overrides still win
        Gtk.StyleContext.add_provider_for_display(display, self.palette, Gtk.STYLE_PROVIDER_PRIORITY_USER - 1)
        self.source = ""
        self._monitors: list[Gio.FileMonitor] = []
        self.load_palette()
        for path in (noctalia_gtk_css(), noctalia_v4_colors()):
            try:
                mon = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.NONE, None)
            except GLib.Error:
                continue
            mon.connect("changed", lambda *_: GLib.timeout_add(250, self._reload))
            self._monitors.append(mon)
        self.icons_available = load_tabler_font()

    def _reload(self):
        self.load_palette()
        return False

    def load_palette(self):
        css = ""
        if noctalia_gtk_css().is_file():
            css = noctalia_gtk_css().read_text()
            self.source = str(noctalia_gtk_css())
        elif noctalia_v4_colors().is_file():
            css = _v4_palette_css(noctalia_v4_colors())
            self.source = str(noctalia_v4_colors())
        else:
            self.source = ""
        self.palette.load_from_string(css)
        dark = _is_dark(css)
        if dark is not None:
            Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)


# --------------------------------------------------------------------------- tabler icons

_TABLER: dict[str, str] = {}

# GTK symbolic fallbacks for the Tabler names used in the app
FALLBACK_ICONS = {
    "device-desktop": "video-display-symbolic",
    "keyboard": "input-keyboard-symbolic",
    "command": "preferences-desktop-keyboard-shortcuts-symbolic",
    "palette": "preferences-desktop-appearance-symbolic",
    "layout-columns": "view-grid-symbolic",
    "layout-grid": "view-grid-symbolic",
    "stack-2": "view-paged-symbolic",
    "player-play": "media-playback-start-symbolic",
    "app-window": "window-new-symbolic",
    "layers-subtract": "view-list-symbolic",
    "sparkles": "applications-graphics-symbolic",
    "settings": "preferences-system-symbolic",
    "code": "text-x-generic-symbolic",
    "history": "document-open-recent-symbolic",
}


def load_tabler_font() -> bool:
    """Register Noctalia's Tabler icon font for this process."""
    if not (TABLER_FONT.is_file() and TABLER_MAP.is_file()):
        return False
    try:
        data = json.loads(TABLER_MAP.read_text())
        for name, info in data.items():
            cp = info.get("codepoint", "") if isinstance(info, dict) else ""
            if cp.startswith("U+"):
                _TABLER[name] = chr(int(cp[2:], 16))
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        return bool(fc.FcConfigAppFontAddFile(None, str(TABLER_FONT).encode()))
    except (OSError, ValueError, AttributeError):
        _TABLER.clear()
        return False


def icon(name: str, *, small: bool = False) -> Gtk.Widget:
    """A Tabler glyph when Noctalia's icon font is available, else a symbolic icon."""
    glyph = _TABLER.get(name)
    if glyph:
        lbl = Gtk.Label(label=glyph, css_classes=["tabler"] + (["small"] if small else []))
        return lbl
    return Gtk.Image(icon_name=FALLBACK_ICONS.get(name, "image-missing-symbolic"))
