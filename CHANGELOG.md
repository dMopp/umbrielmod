# Changelog

All notable changes to UmbrielMod are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) – while the version is `0.x`, minor
releases may change behaviour.

Pull requests add their entry under **Unreleased**; `tools/release.sh` turns
that section into the next version.

## [Unreleased]

## [0.5.0] - 2026-10-30

### Added

- Progress bar while downloading or updating the shader catalogue.

### Changed

- The NixOS instructions use `nix profile add`; `install` is a deprecated alias.

### Fixed

- Clicking *Download* twice no longer starts a second download of the catalogue.
- A slow connection no longer aborts the catalogue download after five minutes;
  only five minutes without any progress do.

## [0.4.0] - 2026-10-30

### Security

- Catalogue effects can no longer change anything but effects. An `effect.toml`
  with other tables (`keybinds`, `general.autostart`, …), or includes and shaders
  pointing outside the collection, is skipped; activation examples only apply
  `effects` and `animation`.
- Installing an effect no longer copies files from outside the collection through
  licence links or symlinks.
- The updater only accepts plain `vX.Y.Z` tags and never runs twice at the same time.

### Fixed

- Saving after a TOML syntax error no longer empties the file. A file that cannot
  be parsed is never written, and the raw editor shows its text so it can be fixed.
- Without a user configuration the first save keeps the defaults Umbriel was
  using (`$XDG_CONFIG_DIRS` or the packaged file) instead of replacing them, and
  no longer fails when `~/.config/umbriel` does not exist.
- Backups restore to the right file: files outside the config directory (`-c`)
  and names containing `__` went to the wrong path, and cleaning up old backups
  could delete those of another file.
- Saving reports read-only files (e.g. links into the Nix store), a missing
  `umbriel` and full disks instead of doing nothing. Writes are flushed to disk.
- Relative includes outside the config directory and symlink loops in it no
  longer break validation.
- Unreadable or non-UTF-8 files, malformed effects and unexpected output from
  `umbriel` no longer crash the start or the catalogue. Text is always UTF-8,
  whatever the locale, and empty `XDG_*` variables are ignored.
- A previous preview is switched back even when the compositor does not answer;
  *Update schema and descriptions* now also takes effect for `-g` style revisions.
- An interrupted first download of the shader catalogue no longer blocks later ones.
- Installer: checks everything the app needs (Python 3.12, pycairo, GTK 4.12,
  libadwaita 1.7), finds `uv` outside the session's `PATH`, keeps your own
  translations, works as root and with `doas`, verifies the lock file, and
  self-updates also work without `uv`.

## [0.3.1] - 2026-10-21

### Changed

- Releases go through a pull request: `tools/release.sh` prepares a
  `release-X.Y.Z` branch, and merging it tags and publishes the release.

### Fixed

- The (?) button of an output's `scale` opens the *Position and scale* section
  of the Umbriel docs instead of the settings table.

## [0.3.0] - 2026-10-21

### Added

- NixOS support: a flake with package, overlay and development shell; the
  installer points NixOS users to it.

### Changed

- Noctalia's Tabler icon font is looked up in `$XDG_DATA_DIRS` (Nix profiles)
  before `/usr/share`.

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

[Unreleased]: https://github.com/dMopp/umbrielmod/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/dMopp/umbrielmod/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dMopp/umbrielmod/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/dMopp/umbrielmod/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/dMopp/umbrielmod/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dMopp/umbrielmod/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dMopp/umbrielmod/releases/tag/v0.1.0
