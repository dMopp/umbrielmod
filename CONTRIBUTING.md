# Contributing

Thanks for helping! Bug reports, translations and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/dMopp/umbrielmod
cd umbrielmod
uv venv --system-site-packages     # PyGObject/GTK come from the system
uv sync
uv run umbrielmod -c /path/to/a/copy/of/config.toml
uv run pytest
```

Use a copy of your configuration while developing – saving writes to the file
you pass with `-c`. Source checkouts never update themselves.

The installer is checked with `shellcheck` in CI (Ubuntu's 0.9 and newer):

```bash
uvx --from shellcheck-py shellcheck install.sh tools/release.sh
```

## Pull requests

- Target the `main` branch. `main` is the development branch; users get
  tagged releases.
- Add a line to the **Unreleased** section of [CHANGELOG.md](CHANGELOG.md)
  (`Added`, `Changed`, `Fixed` or `Removed`).
- Keep the schema-driven approach: options come from
  `umbriel config schema --json`, so prefer improving generic widgets over
  hard-coding single options.
- Interface strings are English and wrapped in `_()`; see
  [docs/TRANSLATING.md](docs/TRANSLATING.md#for-maintainers). Run
  `uv run python -m umbrielmod.i18n extract` and `update` when you add strings;
  German translations are welcome but not required.
- `uv run pytest` must pass.

## Releases (maintainers)

Versions follow [Semantic Versioning](https://semver.org/). To release:

```bash
tools/release.sh 0.3.0 --push
```

The script moves the Unreleased changelog entries to `0.3.0`, sets
`__version__`, commits `Release v0.3.0`, tags `v0.3.0` and pushes. The
*Release* workflow then publishes the GitHub release with the changelog
section as notes. Installed copies pick up the new release on their next start.
