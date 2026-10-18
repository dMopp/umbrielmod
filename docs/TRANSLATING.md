# Translating UmbrielMod

UmbrielMod uses standard gettext `.po` files. They are read directly at
runtime – there is no compile step – so you only need a text editor (or a PO
editor such as [Poedit](https://poedit.net/), Lokalize or Gtranslator) and a
running UmbrielMod to check the result.

## 1. Start a new language

The template with every translatable string is
[`umbrielmod/locale/umbrielmod.pot`](../umbrielmod/locale/umbrielmod.pot).
Copy it to a file named after the language code
([ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes), optionally
with a region such as `pt_BR`):

```bash
mkdir -p ~/.local/share/umbrielmod/locale
cp ~/.local/share/umbrielmod/umbrielmod/locale/umbrielmod.pot \
   ~/.local/share/umbrielmod/locale/fr.po
```

(`~/.local/share/umbrielmod/` is where the installer puts UmbrielMod; with a
source checkout use `umbrielmod/locale/umbrielmod.pot` from the repository.)

Edit the header at the top of the new file:

```po
"Language-Team: Français\n"
"Language: fr\n"
```

`Language-Team` is the name shown in *Menu → Language*.

## 2. Translate

Every entry has the English text in `msgid`; write the translation into
`msgstr`:

```po
#: umbrielmod/window.py:155
msgid "Save"
msgstr "Enregistrer"
```

Rules:

- **Keep placeholders unchanged.** `{name}`, `{file}`, `{n}` … are replaced at
  runtime. They may move within the sentence but must keep their exact spelling:

  ```po
  msgid "Uninstall {name}?"
  msgstr "Désinstaller {name} ?"
  ```

- **Leave `msgstr ""` empty** for strings you do not want to translate yet –
  the English text is used instead.
- Long strings may span several lines; GNU gettext joins them:

  ```po
  msgid "Rules apply in order; later rules override earlier ones. "
  "Each rule only lists the keys it sets – add more with “Add”."
  msgstr "Les règles s'appliquent dans l'ordre ; …"
  ```

- Entries marked `#, fuzzy` are ignored, as in gettext.
- `translator-credits` is shown in the About dialog – put your name there.

### Option descriptions from the Umbriel documentation

After the interface strings the file contains option descriptions taken from
Umbriel's own documentation. Their references start with `umbriel-docs:`, e.g.

```po
#: umbriel-docs:layout.gap
msgid "Gap between windows in logical pixels."
msgstr ""
```

Translating them is optional; untranslated ones are shown in English.

## 3. Try it

UmbrielMod picks up `.po` files from these folders, later ones overriding
earlier ones entry by entry:

1. `umbrielmod/locale/` – languages shipped with UmbrielMod
2. `~/.local/share/umbrielmod/locale/` – your own files
3. every folder listed in `$UMBRIELMOD_LOCALE_DIR` (`:`-separated)

Start UmbrielMod in your language without changing any setting:

```bash
umbrielmod --lang fr
# or: UMBRIELMOD_LANG=fr umbrielmod
```

or choose it under *Menu → Language*, which switches immediately and is
remembered. Save the `.po` file and switch the language again (or restart) to
see changes.

Check placeholders and coverage from a source checkout:

```bash
uv run python -m umbrielmod.i18n stats
uv run pytest tests/test_i18n.py    # placeholders must match in every shipped .po
```

### Fixing a single string

Because local files override the shipped ones entry by entry, a file with just
one entry is enough to change one translation:

```po
# ~/.local/share/umbrielmod/locale/de.po
msgid "Discard"
msgstr "Änderungen verwerfen"
```

## 4. Share it

Open a pull request that adds your file as `umbrielmod/locale/<code>.po` –
or attach it to an issue. Thank you!

## For maintainers

After changing strings in the code, refresh the template and merge the new
strings into every shipped catalogue (existing translations are kept,
removed strings end up as `#~` obsolete entries):

```bash
uv run python -m umbrielmod.i18n extract   # umbrielmod/locale/umbrielmod.pot
uv run python -m umbrielmod.i18n update    # merge into every umbrielmod/locale/*.po
uv run python -m umbrielmod.i18n stats
```

Strings are marked in the code with `_("…")`, or `N_("…")` for text that is
defined at import time and translated when shown. Use named placeholders with
`.format()` – never f-strings inside `_()`:

```python
_("{n} effects · {revision}").format(n=len(effects), revision=rev)
```
