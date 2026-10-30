#!/usr/bin/env bash
# UmbrielMod installer
#
#   curl -sSL https://raw.githubusercontent.com/dMopp/umbrielmod/main/install.sh | bash
#
# Options:
#   --install     non-interactive install / update
#   --uninstall   remove UmbrielMod (your Umbriel config is never touched)
#   --skip-deps   do not check or install system packages
#   --version X   install release X (e.g. 0.2.0; default: the latest release)
#   --branch X    follow branch X instead of releases (e.g. main for development builds)
set -euo pipefail

# Bash parses this whole group before running any of it: a truncated download
# cannot run half a script, and child processes cannot eat it from stdin.
{

REPO_URL="${UMBRIELMOD_REPO:-https://github.com/dMopp/umbrielmod.git}"
BRANCH=""
VERSION=""
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$PREFIX/umbrielmod"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$PREFIX/applications"
ICON_DIR="$PREFIX/icons/hicolor/scalable/apps"

MODE="interactive"
SKIP_DEPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) MODE="install" ;;
    --uninstall) MODE="uninstall" ;;
    --skip-deps) SKIP_DEPS=1 ;;
    --branch) BRANCH="$2"; shift ;;
    --version) VERSION="${2#v}"; shift ;;
    -h|--help) sed -n '2,13p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ -t 1 ]]; then
  B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'
else
  B=""; G=""; Y=""; R=""; N=""
fi
step()    { echo; echo "${B}==> $*${N}"; }
info()    { echo "    $*"; }
success() { echo "    ${G}✓${N} $*"; }
warn()    { echo "    ${Y}!${N} $*"; }
error()   { echo "    ${R}✗${N} $*" >&2; }
have()    { command -v "$1" >/dev/null 2>&1; }

# Desktop sessions often lack the directories uv is installed to.
export PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin"

# Reading answers works even when the script is piped into bash.
ask() {
  local prompt="$1" reply
  if [[ "$MODE" == "install" ]]; then return 0; fi
  if [[ -r /dev/tty ]]; then
    read -r -p "    $prompt [Y/n] " reply </dev/tty || reply=""
  else
    return 0
  fi
  [[ -z "$reply" || "$reply" =~ ^[YyJj] ]]
}

# ----------------------------------------------------------------------------- uninstall

uninstall() {
  step "Removing UmbrielMod"
  if [[ -d "$APP_DIR/locale" ]]; then # your own translations
    find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name locale -exec rm -rf {} +
    info "Kept your translations in $APP_DIR/locale"
  else
    rm -rf "$APP_DIR"
  fi
  rm -f "$BIN_DIR/umbrielmod" "$DESKTOP_DIR/io.github.umbrielmod.desktop" "$ICON_DIR/io.github.umbrielmod.svg"
  if have update-desktop-database; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
  fi
  success "Removed. Your Umbriel configuration and backups (~/.local/state/umbrielmod) were left untouched."
}

if [[ "$MODE" == "uninstall" ]]; then
  uninstall
  exit 0
fi

# ----------------------------------------------------------------------------- NixOS

# System packages and --system-site-packages venvs do not work on NixOS;
# the flake builds a wrapped package instead.
if [[ "$SKIP_DEPS" -eq 0 ]] && { [[ -e /etc/NIXOS ]] || grep -qs '^ID=nixos' /etc/os-release; }; then
  step "NixOS detected"
  info "Install UmbrielMod from its flake instead of this script:"
  info "  nix profile install github:dMopp/umbrielmod"
  info "or add it to your configuration (see the README, section NixOS)."
  info "Rerun with --skip-deps to use this installer anyway."
  exit 1
fi

# ----------------------------------------------------------------------------- dependencies

detect_pm() {
  for pm in apt-get pacman dnf zypper emerge xbps-install; do
    have "$pm" && { echo "$pm"; return; }
  done
  echo ""
}

as_root() {
  if [[ "$EUID" -eq 0 ]]; then "$@"
  elif have sudo; then sudo "$@"
  elif have doas; then doas "$@"
  else error "Neither sudo nor doas found. Install the packages as root, then rerun."; exit 1
  fi
}

install_packages() {
  local pm; pm="$(detect_pm)"
  case "$pm" in
    apt-get) as_root apt-get install -y python3 python3-venv python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 git curl ;;
    pacman) as_root pacman -S --needed --noconfirm python python-gobject python-cairo gtk4 libadwaita git curl ;;
    dnf) as_root dnf install -y python3 python3-gobject python3-cairo gtk4 libadwaita git curl ;;
    zypper) as_root zypper --non-interactive install python3 python3-gobject python3-gobject-cairo python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 git curl ;;
    emerge) as_root emerge --noreplace dev-lang/python dev-python/pygobject dev-python/pycairo gui-libs/gtk gui-libs/libadwaita dev-vcs/git net-misc/curl ;;
    xbps-install) as_root xbps-install -y python3 python3-gobject python3-cairo gtk4 libadwaita git curl ;;
    *) error "No supported package manager found. Install Python 3, PyGObject, GTK 4, libadwaita and git manually, then rerun with --skip-deps."; exit 1 ;;
  esac
}

check_python_gi() {
  python3 - <<'PY' >/dev/null 2>&1
import sys
assert sys.version_info >= (3, 12)
import cairo
import gi
gi.require_foreign("cairo")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, GdkPixbuf, Gtk
assert (Adw.MAJOR_VERSION, Adw.MINOR_VERSION) >= (1, 7)
assert (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 12)
PY
}

if [[ "$SKIP_DEPS" -eq 0 ]]; then
  step "Checking system packages"
  missing=0
  have python3 || { warn "python3 missing"; missing=1; }
  have git || { warn "git missing"; missing=1; }
  if have python3 && ! check_python_gi; then
    warn "Python ≥ 3.12 with PyGObject, pycairo, GTK ≥ 4.12 and libadwaita ≥ 1.7 not found"
    missing=1
  fi
  if [[ "$missing" -eq 1 ]]; then
    if ask "Install the missing packages with $(detect_pm) (needs sudo)?"; then
      install_packages
      check_python_gi || { error "Python ≥ 3.12, PyGObject, pycairo, GTK ≥ 4.12 or libadwaita ≥ 1.7 still missing. Your distribution may be too old."; exit 1; }
    else
      error "Cannot continue without these packages."; exit 1
    fi
  fi
  success "Python $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))') with GTK 4 and libadwaita"

  if have umbriel; then
    success "$(umbriel --version)"
  else
    warn "'umbriel' is not on PATH. UmbrielMod needs it to read the schema and validate configs."
  fi

  if ! have uv; then
    warn "'uv' (Python environment manager) is not installed."
    if ask "Install uv with the official installer from astral.sh?"; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
  fi
  if have uv; then
    success "$(uv --version)"
  else
    warn "Falling back to python3 -m venv"
  fi
fi

# ----------------------------------------------------------------------------- fetch

# Release channel (default): the newest vX.Y.Z tag. Branch channel: --branch NAME.
latest_release() {
  git ls-remote --tags --refs "$REPO_URL" 'v*' 2>/dev/null \
    | sed -n 's#.*refs/tags/v\([0-9][0-9.]*\)$#\1#p' | sort -V | tail -n 1
}

if [[ -n "$BRANCH" ]]; then
  CHANNEL="branch"
  REF="$BRANCH"
else
  CHANNEL="release"
  [[ -n "$VERSION" ]] || VERSION="$(latest_release)"
  if [[ -z "$VERSION" ]]; then
    warn "No release found – installing the main branch instead."
    CHANNEL="branch"; BRANCH="main"; REF="main"
  else
    REF="v$VERSION"
  fi
fi

step "Fetching UmbrielMod ($REF)"
if [[ -d "$APP_DIR/.git" ]]; then
  if [[ "$CHANNEL" == "release" ]]; then
    git -C "$APP_DIR" fetch --depth 1 --force origin tag "$REF"
    git -C "$APP_DIR" reset --hard "$REF"
  else
    git -C "$APP_DIR" fetch --depth 1 origin "$REF"
    git -C "$APP_DIR" reset --hard FETCH_HEAD
  fi
  success "Updated $APP_DIR"
else
  # Clone next to it: a failed download leaves what is there, and only your
  # own translations (see the README) survive from an earlier directory.
  mkdir -p "$(dirname "$APP_DIR")"
  rm -rf "$APP_DIR.new"
  git clone --depth 1 --branch "$REF" "$REPO_URL" "$APP_DIR.new"
  if [[ -d "$APP_DIR/locale" ]]; then mv "$APP_DIR/locale" "$APP_DIR.new/locale"; fi
  rm -rf "$APP_DIR"
  mv "$APP_DIR.new" "$APP_DIR"
  success "Cloned to $APP_DIR"
fi

# ----------------------------------------------------------------------------- environment

step "Preparing the Python environment"
cd "$APP_DIR"
# Reuse a working environment (updates run while UmbrielMod is open);
# rebuild it only when it is missing or broken.
if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  rm -rf .venv
  if have uv; then
    uv venv --quiet --system-site-packages --python "$(command -v python3)" .venv
  else
    python3 -m venv --system-site-packages .venv
  fi
fi
if have uv; then
  uv sync --quiet --no-dev --locked
else
  # A venv made by uv has no pip. Editable: the self-update needs the git checkout.
  .venv/bin/python -m pip --version >/dev/null 2>&1 || .venv/bin/python -m ensurepip --upgrade
  .venv/bin/python -m pip install --quiet -e .
fi
# from outside the checkout, or this would find the sources instead of the install
(cd / && "$APP_DIR/.venv/bin/python" -c "import umbrielmod, tomlkit") || { error "Environment check failed"; exit 1; }
success "Environment ready"

# ----------------------------------------------------------------------------- launcher

step "Installing launcher and desktop entry"
mkdir -p "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
{
  echo '#!/usr/bin/env bash'
  echo '# Generated by the UmbrielMod installer. The variables enable the self-update.'
  echo 'export UMBRIELMOD_MANAGED=1'
  printf 'export UMBRIELMOD_CHANNEL=%q\n' "$CHANNEL"
  printf 'export UMBRIELMOD_BRANCH=%q\n' "$BRANCH"
  printf 'export UMBRIELMOD_LAUNCHER=%q\n' "$BIN_DIR/umbrielmod"
  # shellcheck disable=SC2016 # "$@" belongs to the launcher
  printf 'exec %q -m umbrielmod "$@"\n' "$APP_DIR/.venv/bin/python"
} > "$BIN_DIR/umbrielmod"
chmod +x "$BIN_DIR/umbrielmod"
install -m 644 "$APP_DIR/data/io.github.umbrielmod.svg" "$ICON_DIR/io.github.umbrielmod.svg"
sed "s|^Exec=.*|Exec=\"$BIN_DIR/umbrielmod\"|" "$APP_DIR/data/io.github.umbrielmod.desktop" > "$DESKTOP_DIR/io.github.umbrielmod.desktop"
if have update-desktop-database; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if have gtk-update-icon-cache; then
  gtk-update-icon-cache -q "$PREFIX/icons/hicolor" >/dev/null 2>&1 || true
fi
success "Command: $BIN_DIR/umbrielmod"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH – add it to start 'umbrielmod' from a terminal." ;;
esac

step "Done"
info "Start UmbrielMod from your launcher or run: umbrielmod"
info "UmbrielMod updates itself on start (Menu → Update automatically);"
info "you can also re-run this installer. Remove with --uninstall."

}
