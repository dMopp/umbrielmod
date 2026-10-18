import re
from pathlib import Path

import pytest

from umbrielmod import i18n
from umbrielmod.docs import _anchor


@pytest.fixture(autouse=True)
def reset_language():
    yield
    i18n.load("en")


def test_parse_po_multiline_and_fuzzy():
    po = '''msgid ""
msgstr ""
"Language: de\\n"

msgid "Save"
msgstr "Speichern"

#, fuzzy
msgid "Old"
msgstr "Alt"

msgid "Two "
"lines"
msgstr "Zwei "
"Zeilen"
'''
    cat = i18n.parse_po(po)
    assert cat == {"Save": "Speichern", "Two lines": "Zwei Zeilen"}


def test_german_catalog_is_complete_and_placeholders_match():
    found = i18n._extract()
    for po in sorted(i18n.LOCALE_DIR.glob("*.po")):
        cat = i18n.parse_po(po.read_text())
        assert not [m for m in found if m not in cat], po.name
        for msgid, msgstr in cat.items():
            assert set(re.findall(r"\{\w+\}", msgid)) == set(re.findall(r"\{\w+\}", msgstr)), msgid


def test_load_and_fallback(monkeypatch):
    assert i18n.load("de_DE") == "de"
    assert i18n._("Save") == "Speichern"
    assert i18n._("not in catalog") == "not in catalog"
    assert i18n.load("xx") == "en"
    assert i18n._("Save") == "Save"


def test_external_catalog_overrides(tmp_path: Path, monkeypatch):
    (tmp_path / "de.po").write_text('msgid "Save"\nmsgstr "Sichern"\n')
    (tmp_path / "fr.po").write_text('msgid ""\nmsgstr ""\n"Language-Team: Français\\n"\n\nmsgid "Save"\nmsgstr "Enregistrer"\n')
    monkeypatch.setenv("UMBRIELMOD_LOCALE_DIR", str(tmp_path))
    i18n.load("de")
    assert i18n._("Save") == "Sichern"
    assert i18n._("Cancel") == "Abbrechen"  # rest still from the shipped catalogue
    assert i18n.available_languages()["fr"] == "Français"
    i18n.load("fr")
    assert i18n._("Save") == "Enregistrer"


def test_docs_slugs_match_site():
    assert _anchor("Move & size") == "move--size"
    assert _anchor("Variable refresh rate") == "variable-refresh-rate"
