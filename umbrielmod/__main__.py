"""Entry point: `umbrielmod [-c config.toml]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import __version__, umbriel  # noqa: E402
from .config import Config, default_config_path  # noqa: E402
from .context import AppContext  # noqa: E402
from .docs import Docs  # noqa: E402
from .schema import Schema  # noqa: E402

APP_ID = "io.github.umbrielmod"

CSS = """
.keycap {
  font-family: monospace;
  font-size: 0.9em;
  padding: 1px 6px;
  border-radius: 5px;
  border: 1px solid alpha(currentColor, 0.25);
  box-shadow: inset 0 -2px alpha(currentColor, 0.15);
}
.effect-card { padding: 6px; }
.effect-card picture { border-radius: 8px; }
.kind-badge { font-size: 0.8em; padding: 0 6px; border-radius: 99px; background: alpha(@accent_bg_color, 0.2); }
"""


class App(Adw.Application):
    def __init__(self, config_path: Path):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.config_path = config_path

    def do_activate(self):
        Gtk.Window.set_default_icon_name(APP_ID)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        try:
            schema = Schema.load()
        except umbriel.UmbrielError as exc:
            self._fatal(f"Das Umbriel-Schema konnte nicht gelesen werden:\n{exc}\n\nIst `umbriel` installiert und im PATH?")
            return
        cfg = Config(self.config_path)
        if cfg.main.error:
            self._fatal(f"{cfg.main.path} ist kein gültiges TOML:\n{cfg.main.error}")
            return
        ctx = AppContext(cfg, schema, Docs.load(schema.revision))
        from .window import MainWindow

        MainWindow(self, ctx).present()

    def _fatal(self, message: str):
        win = Adw.ApplicationWindow(application=self, title="UmbrielMod", default_width=520, default_height=260)
        status = Adw.StatusPage(icon_name="dialog-error-symbolic", title="UmbrielMod kann nicht starten", description=message)
        win.set_content(status)
        win.present()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="umbrielmod", description="GTK4-Konfigurationseditor für Umbriel")
    parser.add_argument("-c", "--config", type=Path, default=default_config_path(), help="Pfad zur config.toml")
    parser.add_argument("--version", action="version", version=f"umbrielmod {__version__}")
    args = parser.parse_args(argv)
    if not umbriel.available():
        print("umbrielmod: `umbriel` wurde nicht im PATH gefunden", file=sys.stderr)
    return App(args.config).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
