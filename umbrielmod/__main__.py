"""Entry point: `umbrielmod [-c config.toml]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import __version__, i18n, settings, umbriel  # noqa: E402
from .i18n import _  # noqa: E402
from .config import Config, default_config_path  # noqa: E402
from .context import AppContext  # noqa: E402
from .docs import Docs  # noqa: E402
from .schema import Schema  # noqa: E402

APP_ID = "io.github.umbrielmod"

class App(Adw.Application):
    def __init__(self, config_path: Path):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.config_path = config_path

    def do_activate(self):
        if i18n.current_language() == i18n.SOURCE_LANG and not getattr(self, "_lang_set", False):
            i18n.load(settings.get("language") or None)
        Gtk.Window.set_default_icon_name(APP_ID)
        from .theme import Theme

        self.theme = Theme(Gdk.Display.get_default())
        try:
            schema = Schema.load()
        except umbriel.UmbrielError as exc:
            self._fatal(_("Could not read the Umbriel schema:\n{error}\n\nIs `umbriel` installed and on PATH?").format(error=exc))
            return
        cfg = Config(self.config_path)
        if cfg.main.error:
            self._fatal(_("{file} is not valid TOML:\n{error}").format(file=cfg.main.path, error=cfg.main.error))
            return
        ctx = AppContext(cfg, schema, Docs.load(schema.revision))
        from .window import MainWindow

        MainWindow(self, ctx).present()

    def _fatal(self, message: str):
        win = Adw.ApplicationWindow(application=self, title="UmbrielMod", default_width=520, default_height=260)
        status = Adw.StatusPage(icon_name="dialog-error-symbolic", title=_("UmbrielMod cannot start"), description=message)
        win.set_content(status)
        win.present()


def main(argv: list[str] | None = None) -> int:
    i18n.load(settings.get("language") or None)
    parser = argparse.ArgumentParser(prog="umbrielmod", description=_("GTK4 configuration editor for Umbriel"))
    parser.add_argument("-c", "--config", type=Path, default=default_config_path(), help=_("path to config.toml"))
    parser.add_argument("--lang", help=_("interface language, e.g. en or de"))
    parser.add_argument("--version", action="version", version=f"umbrielmod {__version__}")
    args = parser.parse_args(argv)
    if args.lang:
        i18n.load(args.lang)
    app = App(args.config)
    app._lang_set = bool(args.lang)
    if not umbriel.available():
        print(_("umbrielmod: `umbriel` was not found on PATH"), file=sys.stderr)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
