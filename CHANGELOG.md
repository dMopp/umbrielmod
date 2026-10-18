# Changelog

All notable changes to UmbrielMod are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) – while the version is `0.x`, minor
releases may change behaviour.

Pull requests add their entry under **Unreleased**; `tools/release.sh` turns
that section into the next version.

## [Unreleased]

### Changed

- CI runs for branches and pull requests, no longer again for release tags.

## [0.2.0] - 2026-10-18

### Added

- English and German interface. Translations are gettext `.po` files read at
  runtime; extra languages or fixes can be dropped into
  `~/.local/share/umbrielmod/locale/` ([guide](docs/TRANSLATING.md)).
- Language menu with live switching.
- Noctalia look: live palette from Noctalia's GTK stylesheet, Noctalia radii and
  spacing, Tabler icons from the Noctalia install.
- A round (?) button on every option, group and page that opens the most
  specific section of the Umbriel documentation.
- Self-update: installer-managed installations check for a new release on
  start (and every six hours), run its installer and offer a restart.
- Live preview window for effects, rendered by Umbriel itself: border and
  window effects on the preview window only, screen and cursor effects while it
  is open, animations played on demand with timing taken from the effect.
  Effects that are not installed are loaded through a temporary copy of the
  saved configuration.
- Animated GIF previews from the shader collection play in the app.
- Palette effects: the preset page shows the four theme colours the shader
  uses, and the live preview can compare theme colours with the original ones.
- Versioned releases with this changelog; installer and updater follow the
  latest release by default (`--branch main` for development builds).
- README screenshots, live-preview video and translation guide.

### Changed

- Shader detail pages have a back button; the live-preview button sits on the
  preview image and next to Install.
- The installer reuses a working Python environment instead of rebuilding it.

### Fixed

- Installer passes shellcheck 0.9 and newer.

## [0.1.0] - 2026-10-18

### Added

- First release: GTK4/libadwaita configuration editor for Umbriel.
- Settings pages generated from `umbriel config schema --json`, so every
  option of the installed Umbriel build is editable; descriptions extracted
  from Umbriel's documentation.
- Comment-preserving TOML editing, validation with `umbriel config validate`
  before every save, atomic writes and backups, undo/redo, raw editor.
- Outputs with drag-and-drop arrangement, keybind editor with conflict
  detection and key capture, rule editors for windows, layers, workspaces,
  scratchpads and devices.
- Community shader catalogue: install, activate, tune presets and GLSL
  constants.
- `curl … | bash` installer.

[Unreleased]: https://github.com/dMopp/umbrielmod/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dMopp/umbrielmod/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dMopp/umbrielmod/releases/tag/v0.1.0
