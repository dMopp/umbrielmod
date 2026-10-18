#!/usr/bin/env bash
# UmbrielMod installer
#
#   curl -sSL https://raw.githubusercontent.com/dMopp/umbrielmod/main/install.sh | bash
#
# Options:
#   --install     non-interactive install / update
#   --uninstall   remove UmbrielMod (your Umbriel config is never touched)
#   --skip-deps   do not check or install system packages
#   --branch X    install a different branch (default: main)
set -euo pipefail

REPO_URL="${UMBRIELMOD_REPO:-https://github.com/dMopp/umbrielmod.git}"
BRANCH="main"
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
    -h|--help) sed -n '2,12p' "$0" 2>/dev/null || true; exit 0 ;;
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
  rm -rf "$APP_DIR"
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

# ----------------------------------------------------------------------------- dependencies

detect_pm() {
  for pm in apt-get pacman dnf zypper emerge xbps-install; do
    have "$pm" && { echo "$pm"; return; }
  done
  echo ""
}

install_packages() {
  local pm; pm="$(detect_pm)"
  case "$pm" in
    apt-get) sudo apt-get install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 git curl ;;
    pacman) sudo pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita git curl ;;
    dnf) sudo dnf install -y python3 python3-gobject gtk4 libadwaita git curl ;;
    zypper) sudo zypper install -y python3 python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 git curl ;;
    emerge) sudo emerge --noreplace dev-lang/python dev-python/pygobject gui-libs/gtk gui-libs/libadwaita dev-vcs/git net-misc/curl ;;
    xbps-install) sudo xbps-install -y python3 python3-gobject gtk4 libadwaita git curl ;;
    *) error "No supported package manager found. Install Python 3, PyGObject, GTK 4, libadwaita and git manually, then rerun with --skip-deps."; exit 1 ;;
  esac
}

check_python_gi() {
  python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
assert (Adw.MAJOR_VERSION, Adw.MINOR_VERSION) >= (1, 5)
PY
}

if [[ "$SKIP_DEPS" -eq 0 ]]; then
  step "Checking system packages"
  missing=0
  have python3 || { warn "python3 missing"; missing=1; }
  have git || { warn "git missing"; missing=1; }
  if have python3 && ! check_python_gi; then
    warn "PyGObject with GTK 4 and libadwaita ≥ 1.5 not found"
    missing=1
  fi
  if [[ "$missing" -eq 1 ]]; then
    if ask "Install the missing packages with $(detect_pm) (needs sudo)?"; then
      install_packages
      check_python_gi || { error "GTK 4 / libadwaita still not importable from python3."; exit 1; }
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

step "Fetching UmbrielMod ($BRANCH)"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$APP_DIR" reset --hard FETCH_HEAD
  success "Updated $APP_DIR"
else
  rm -rf "$APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
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
  uv sync --quiet --no-dev
else
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet .
fi
.venv/bin/python -c "import umbrielmod, tomlkit" || { error "Environment check failed"; exit 1; }
success "Environment ready"

# ----------------------------------------------------------------------------- launcher

step "Installing launcher and desktop entry"
mkdir -p "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
cat > "$BIN_DIR/umbrielmod" <<EOF
#!/usr/bin/env bash
# Generated by the UmbrielMod installer. The variables enable the self-update.
export UMBRIELMOD_MANAGED=1
export UMBRIELMOD_BRANCH="$BRANCH"
export UMBRIELMOD_LAUNCHER="$BIN_DIR/umbrielmod"
exec "$APP_DIR/.venv/bin/python" -m umbrielmod "\$@"
EOF
chmod +x "$BIN_DIR/umbrielmod"
install -m 644 "$APP_DIR/data/io.github.umbrielmod.svg" "$ICON_DIR/io.github.umbrielmod.svg"
sed "s|^Exec=.*|Exec=$BIN_DIR/umbrielmod|" "$APP_DIR/data/io.github.umbrielmod.desktop" > "$DESKTOP_DIR/io.github.umbrielmod.desktop"
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
