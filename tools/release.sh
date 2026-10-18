#!/usr/bin/env bash
# Cut a release: tools/release.sh X.Y.Z [--push]
#
# Moves the "Unreleased" CHANGELOG section to X.Y.Z, sets __version__,
# commits "Release vX.Y.Z" and creates the annotated tag. With --push the
# commit and tag are pushed; GitHub Actions then publishes the release.
set -euo pipefail

version="${1:-}"
version="${version#v}"
push="${2:-}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 X.Y.Z [--push]" >&2
  exit 2
fi
cd "$(dirname "$0")/.."

[[ -z "$(git status --porcelain)" ]] || { echo "error: working tree not clean" >&2; exit 1; }
[[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] || { echo "error: release from main" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
  echo "error: tag v$version exists" >&2
  exit 1
fi

python3 - "$version" "$(date +%F)" <<'PY'
import re, sys
from pathlib import Path

version, date = sys.argv[1], sys.argv[2]
cl = Path("CHANGELOG.md")
text = cl.read_text()
head, sep, rest = text.partition("## [Unreleased]\n")
if not sep:
    sys.exit("error: CHANGELOG.md has no '## [Unreleased]' section")
body, nxt, tail = rest.partition("\n## [")
if not body.strip():
    sys.exit("error: the Unreleased section is empty – describe the changes first")
previous = re.match(r"([0-9.]+)\]", tail).group(1) if tail else None
text = f"{head}## [Unreleased]\n\n## [{version}] - {date}\n{body.rstrip()}\n\n" + (nxt.lstrip("\n") + tail if tail else "")
repo = "https://github.com/dMopp/umbrielmod"
text = re.sub(r"^\[Unreleased\]: .*$", f"[Unreleased]: {repo}/compare/v{version}...HEAD", text, flags=re.M)
link = f"[{version}]: {repo}/compare/v{previous}...v{version}" if previous else f"[{version}]: {repo}/releases/tag/v{version}"
text = re.sub(r"^(\[Unreleased\]: .*)$", r"\1\n" + link, text, count=1, flags=re.M)
cl.write_text(text)

init = Path("umbrielmod/__init__.py")
init.write_text(re.sub(r'^__version__ = ".*"$', f'__version__ = "{version}"', init.read_text(), flags=re.M))
PY

git add CHANGELOG.md umbrielmod/__init__.py
git commit -q -m "Release v$version"
git tag -a "v$version" -m "UmbrielMod $version"
echo "Created commit and tag v$version."
if [[ "$push" == "--push" ]]; then
  git push origin main "v$version"
else
  echo "Push with: git push origin main v$version"
fi
