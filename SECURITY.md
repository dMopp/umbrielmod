# Security Policy

## Supported versions

UmbrielMod is maintained by one person in their spare time. Security fixes are
made for the **latest release** only. Installations made by `install.sh` update
themselves to new releases automatically, so a fix reaches users with the next
release.

| Version                      | Supported |
| ---------------------------- | --------- |
| latest release (currently 0.2.x) | ✅ |
| older releases               | ❌ |
| `main` branch (`--branch main`) | best effort – fixed on `main` first |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report them privately through GitHub:
[**Report a vulnerability**](https://github.com/dMopp/umbrielmod/security/advisories/new)
(*Security* tab → *Report a vulnerability*).

Please include:

- the UmbrielMod version (*Menu → About*, or `git -C ~/.local/share/umbrielmod describe --tags`),
- your distribution and how UmbrielMod was installed (installer, `--branch main`, source checkout),
- steps to reproduce, and what an attacker gains,
- a proof of concept, if you have one.

### What happens next

- You get an acknowledgement within **7 days**.
- I assess the report and keep you updated in the advisory until it is resolved.
- If the report is accepted, the fix is released as a new version and a
  GitHub Security Advisory is published. You are credited unless you prefer not to be.
- If the report is declined, you get an explanation of why.

Please give me a reasonable amount of time to release a fix before you
disclose the issue publicly.

## Scope

UmbrielMod runs locally with your user's permissions. Reports are especially
welcome for:

- **Self-update and installer** – the updater runs the `install.sh` of the new
  version from the installation's git origin; anything that lets a third party
  get code executed through `install.sh` or the update mechanism.
- **Configuration handling** – writing, validating, backing up and restoring
  config files: path traversal, writes outside the intended files, symlink
  attacks, loss of configuration, insecure temporary files.
- **Shader catalogue and documentation updates** – handling of the cloned
  repositories and the files installed from them (e.g. paths in shader
  metadata escaping the target directory).
- **Command execution** – injection into the commands UmbrielMod runs
  (`umbriel`, `git`).

Out of scope:

- vulnerabilities in **Umbriel** itself → report them to
  [noctalia-dev/umbriel](https://github.com/noctalia-dev/umbriel),
- the content of third-party shaders in the
  [community shader collection](https://github.com/noctalia-dev/community-umbriel-shaders),
- vulnerabilities in GTK, libadwaita, PyGObject, Python or other system packages,
- attacks that require an attacker to already control your user account or your
  GitHub account/repository settings.
