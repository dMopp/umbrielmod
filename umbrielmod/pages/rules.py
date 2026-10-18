"""Window rules, with a shortcut to create a rule from an open window."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from .. import umbriel
from ..context import AppContext
from ..widgets import SuggestButton
from .schema_page import AoTGroup


def _regex(text: str) -> str:
    special = set(".^$*+?()[]{}|\\")
    return "^" + "".join(f"\\{c}" if c in special else c for c in text) + "$"


class WindowRulesPage(Adw.PreferencesPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._windows: list[dict] = []

        def items():
            self._windows = umbriel.windows()
            return [(w.get("app_id") or "?", w.get("title", "")) for w in self._windows]

        def pick(app_id: str):
            win = next((w for w in self._windows if w.get("app_id") == app_id), {})
            self.group.add_entry({"match": {"app_id": _regex(app_id)}})
            ctx.toast(f"Regel für {app_id} angelegt" + (f" ({win.get('title')})" if win.get("title") else ""))

        picker = SuggestButton(items, pick)
        picker.set_icon_name("")
        picker.set_child(Adw.ButtonContent(icon_name="find-location-symbolic", label="Aus offenem Fenster"))
        picker.set_tooltip_text("Neue Regel mit der App-ID eines geöffneten Fensters")
        intro = Adw.PreferencesGroup(
            description="Regeln werden der Reihe nach angewendet; spätere Regeln überschreiben frühere. "
                        "Jede Regel zeigt nur die gesetzten Schlüssel – weitere über „Hinzufügen“."
        )
        self.add(intro)
        self.group = AoTGroup(ctx, "window_rule", ("window_rule",), extra_header=picker)
        self.add(self.group)

    def refresh(self):
        self.group.refresh()
