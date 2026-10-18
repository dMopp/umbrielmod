"""Window rules, with a shortcut to create a rule from an open window."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from .. import umbriel
from ..context import AppContext
from ..i18n import _
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
            ctx.toast(_("Rule for {app} created").format(app=app_id) + (f" ({win.get('title')})" if win.get("title") else ""))

        picker = SuggestButton(items, pick)
        picker.set_icon_name("")
        picker.set_child(Adw.ButtonContent(icon_name="find-location-symbolic", label=_("From open window")))
        picker.set_tooltip_text(_("New rule matching the app ID of an open window"))
        intro = Adw.PreferencesGroup(
            description=_("Rules apply in order; later rules override earlier ones. "
                          "Each rule only lists the keys it sets – add more with “Add”.")
        )
        self.add(intro)
        self.group = AoTGroup(ctx, "window_rule", ("window_rule",), extra_header=picker)
        self.add(self.group)

    def refresh(self):
        self.group.refresh()
