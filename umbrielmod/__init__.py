"""UmbrielMod – GTK4/libadwaita configuration editor for the Umbriel compositor."""

__version__ = "0.4.0"

try:  # set GI versions before any submodule imports gi.repository
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkPixbuf", "2.0")
except (ImportError, ValueError):  # backend-only use (tests, docs generator)
    pass
