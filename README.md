<div align="center">
  <img src="data/io.github.umbrielmod.svg" width="96" alt="">
  <h1>UmbrielMod</h1>

  **GTK4/libadwaita configuration editor for the [Umbriel](https://github.com/noctalia-dev/umbriel) Wayland compositor.**

  [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
  [![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white)](https://python.org)
  [![GTK4](https://img.shields.io/badge/GTK-4%20%2B%20libadwaita-4A90D9?logo=gnome&logoColor=white)](https://gtk.org)
</div>

Umbriel is configured with a single TOML file. UmbrielMod puts a native
interface on top of it — inspired by [NiriMod](https://github.com/srinivasr/nirimod) —
without taking the file away from you: comments, ordering and formatting survive
every edit.

> The interface is currently in German.

## Every option, straight from Umbriel

UmbrielMod does not hard-code a list of settings. At start-up it asks the
installed compositor for its schema (`umbriel config schema --json`) and builds
the pages from it, so **every option your Umbriel build accepts is editable** —
with the right control for its type, range, allowed values and default — and
options added in future Umbriel versions show up automatically.

Descriptions and documentation links come from Umbriel's own documentation
(`docs/user/*.md` in the Umbriel repository). A copy is bundled; *Menu → Update
schema/descriptions* fetches the docs for the exact revision you have installed.

## Features

- **Outputs** – drag-and-drop arrangement with edge snapping, modes detected via
  `umbriel outputs`, scale, VRR, HDR, SDR white level and every other output key.
- **Keybinds** – grouped by action category, search, conflict detection
  (modifier order and spelling are normalised, submaps respected), key capture
  that temporarily inhibits compositor shortcuts, action picker built from
  `umbriel msg --help` including argument hints.
- **Window rules, layer rules, workspaces, scratchpads, devices** – each entry
  shows only the keys it sets; add more from a searchable list, reorder,
  duplicate, or create a rule from a currently open window.
- **Effects & shaders** – browse the
  [community shader collection](https://github.com/noctalia-dev/community-umbriel-shaders)
  with previews, install effects (including companion overlays and licence
  files), apply their activation examples, and tune them:
  - only the preset keys Umbriel supports for that kind (`palette`; borders:
    `padding`, `speed`, `animated`, `overlay`, `light`; cursors: `radius`),
  - selection as default border/window/screen/cursor effect or per animation event,
  - top-level `#define`/`const` values in the GLSL source (the collection's
    documented way to fine-tune), with colour pickers for colour vectors and
    one-click restore of the original shader,
  - **live preview** through `umbriel msg effect-<slot>-set:<name>` without
    touching the config.
- **Raw editor** for any loaded file, **undo/redo**, and a backup browser.

## Configuration safety

- Before anything is written, the complete configuration — including all
  `include`d files, with your pending changes applied — is copied to a scratch
  directory and checked with `umbriel config validate`. Invalid configurations
  are not saved; Umbriel's diagnostics are shown instead.
- Files are replaced atomically; the previous version goes to
  `~/.local/state/umbrielmod/backups/` (50 per file).
- Values defined in included files (for example colours managed by Noctalia in
  `noctalia.toml`) are shown read-only with their source.
- External edits (scripts, your editor) are detected and reloaded.
- Umbriel watches its config, so saved changes apply immediately.

## Installation

```bash
curl -sSL https://raw.githubusercontent.com/dmopp/umbrielmod/main/install.sh | bash
```

The installer checks for Python 3, PyGObject, GTK 4, libadwaita and git (and
offers to install them with apt, pacman, dnf, zypper, emerge or xbps), creates
an isolated environment with [uv](https://docs.astral.sh/uv/) in
`~/.local/share/umbrielmod`, and adds `umbrielmod` to `~/.local/bin` plus a
desktop entry.

Run it again to update. Options: `--install` (non-interactive), `--uninstall`,
`--skip-deps`, `--branch <name>`.

### Requirements

- Umbriel on `PATH` (for the schema, validation and live preview)
- Python 3.12+, PyGObject, GTK 4, libadwaita ≥ 1.5
- git (for the shader catalogue)

### From source

```bash
git clone https://github.com/dmopp/umbrielmod
cd umbrielmod
uv venv --system-site-packages
uv sync
uv run umbrielmod            # or: uv run umbrielmod -c /path/to/config.toml
uv run pytest
```

Regenerate the bundled option descriptions from an Umbriel checkout:

```bash
uv run python -m umbrielmod.docs /path/to/umbriel -v
```

## Licence

MIT. Shaders installed from the community collection keep their own licences;
UmbrielMod copies each effect's licence file next to it.

*UmbrielMod is an independent project and not affiliated with the Umbriel or Noctalia teams.*
