#!/usr/bin/env bash
# Prepare a release: tools/release.sh X.Y.Z [--push]
#
# main only accepts pull requests, so this works on a branch: it moves the
# "Unreleased" CHANGELOG section to X.Y.Z, sets __version__ and commits
# "Release vX.Y.Z" on release-X.Y.Z. With --push the branch is pushed and the
# pull request is opened (with gh) or its title and text are printed. Merging
# it is the release: the Release workflow then tags vX.Y.Z on main and
# publishes the GitHub release.
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
git fetch -q origin main --tags
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo "error: main differs from origin/main – pull first" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
  echo "error: tag v$version exists" >&2
  exit 1
fi
branch="release-$version"

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

git switch -q -c "$branch"
git add CHANGELOG.md umbrielmod/__init__.py
git commit -q -m "Release v$version"
notes="$(awk -v v="$version" 'index($0, "## [" v "]") == 1 {f=1; next} /^## \[/ {f=0} f' CHANGELOG.md | sed -e '/./,$!d')"
git switch -q main
echo "Created $branch with commit \"Release v$version\"."

title="Release v$version"
body="Release UmbrielMod $version.

Merging this tags \`v$version\` on main and publishes the GitHub release with
these notes (any merge method works):

$notes"

if [[ "$push" != "--push" ]]; then
  echo "Push with: git push -u origin $branch"
  exit 0
fi
git push -q -u origin "$branch"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
else
  echo
  echo "Open the pull request: https://github.com/dMopp/umbrielmod/pull/new/$branch"
  echo
  echo "Title: $title"
  echo
  echo "$body"
fi
