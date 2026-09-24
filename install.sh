#!/usr/bin/env bash
# OpenCompany Installer
# Usage: curl -fsSL https://opencompany.sh/install.sh | bash
#
# Served from opencompany.sh (not the GitHub raw URL) so installs are
# trackable. The release to install comes from https://opencompany.sh/version
# unless OPENCOMPANY_VERSION is set.
#
# This script installs OpenCompany and its dependencies:
# - bun (the JavaScript runtime and package manager; no Node.js, no npm)
# - Python 3.12+ (via brew/apt/dnf/pacman)
# - uv (Python package manager)
#
# Prefer the desktop app if you just want to use OpenCompany on a laptop; this
# path is for terminal and server use.

set -e

MIN_PYTHON_VERSION_MINOR=12
PKG_NAME="@zeenie-ai/opencompany"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error_exit() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# Banner
echo ""
echo -e "${CYAN}  OpenCompany${NC}"
echo ""
echo "Self-improving AI employees, running on your own computer"
echo ""

# Detect OS
detect_os() {
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macos"
  elif [[ -f /etc/debian_version ]]; then
    echo "debian"
  elif [[ -f /etc/redhat-release ]]; then
    echo "redhat"
  elif [[ -f /etc/arch-release ]]; then
    echo "arch"
  else
    echo "unknown"
  fi
}

OS=$(detect_os)

# bun installs to $BUN_INSTALL (default ~/.bun) and puts global bin shims in
# its bin dir. Where it stores the global package itself varies by platform
# and configuration, so nothing below depends on that: the `company` shim
# knows its own package root and `company provision` does the rest.
BUN_HOME="${BUN_INSTALL:-$HOME/.bun}"
BUN_BIN_DIR="$BUN_HOME/bin"

# A previous npm-based install (or the pre-rebrand `machinaos` package) leaves
# a `company` / `machina` shim on PATH that would shadow the bun one. Remove it
# when npm happens to be around; skip silently otherwise.
remove_legacy_npm_installs() {
  command -v npm &> /dev/null || return 0
  for pkg in "$PKG_NAME" machinaos; do
    if npm list -g --depth=0 "$pkg" &> /dev/null; then
      info "Removing legacy npm install of $pkg..."
      npm uninstall -g "$pkg" &> /dev/null || warn "Could not remove $pkg; run: npm uninstall -g $pkg"
    fi
  done
}

# =============================================================================
# Dependency Checks and Installation
# =============================================================================

check_bun() {
  hash -r 2>/dev/null || true
  if command -v bun &> /dev/null; then
    success "bun $(bun --version)"
    return 0
  fi
  return 1
}

install_bun() {
  info "Installing bun (JavaScript runtime and package manager)..."
  curl -fsSL https://bun.sh/install | bash
  export PATH="$BUN_BIN_DIR:$PATH"
  if ! check_bun; then
    error_exit "Failed to install bun. Install it manually from https://bun.sh and re-run."
  fi
}

check_python() {
  for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
      version=$($cmd --version 2>&1 | sed -n 's/.*Python \([0-9]*\.[0-9]*\).*/\1/p')
      major=$(echo "$version" | cut -d. -f1)
      minor=$(echo "$version" | cut -d. -f2)
      if [ "$major" -ge 3 ] && [ "$minor" -ge "$MIN_PYTHON_VERSION_MINOR" ]; then
        success "Python $version ($cmd)"
        PYTHON_CMD="$cmd"
        return 0
      fi
    fi
  done
  warn "Python 3.$MIN_PYTHON_VERSION_MINOR+ not found"
  return 1
}

install_python() {
  info "Installing Python 3.$MIN_PYTHON_VERSION_MINOR..."

  case "$OS" in
    macos)
      if command -v brew &> /dev/null; then
        brew install python@3.12
      else
        error_exit "Please install Homebrew first: https://brew.sh/"
      fi
      ;;
    debian)
      sudo apt-get update
      sudo apt-get install -y python3.12 python3.12-venv python3-pip
      ;;
    redhat)
      sudo dnf install -y python3.12
      ;;
    arch)
      sudo pacman -S --noconfirm python python-pip
      ;;
    *)
      error_exit "Please install Python 3.12+ manually from https://python.org/"
      ;;
  esac

  if ! check_python; then
    error_exit "Failed to install Python. Please install manually."
  fi
}

check_uv() {
  if command -v uv &> /dev/null; then
    version=$(uv --version | tr -d 'uv ')
    success "uv $version"
    return 0
  fi
  return 1
}

install_uv() {
  info "Installing uv (Python package manager)..."

  # Try pip first
  if [ -n "$PYTHON_CMD" ]; then
    if $PYTHON_CMD -m pip install uv 2>/dev/null; then
      export PATH="$HOME/.local/bin:$PATH"
      if check_uv; then return 0; fi
    fi
  fi

  # Fallback to official installer
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"

  if ! check_uv; then
    error_exit "Failed to install uv"
  fi
}

# bun finds its global "project" by walking up from $BUN_INSTALL/install/global
# until it meets a package.json. A stray package.json or package-lock.json in
# $HOME (an old `npm init` / `npm install` run in the home dir) therefore
# hijacks every global install: packages land in $HOME/node_modules and
# `bun add -g` dies with "InvalidNPMLockfile: failed to migrate lockfile"
# (docs-internal/errors.md #23). Giving the global dir its own manifest stops
# the walk-up before it reaches $HOME. Harmless on a clean machine: it is the
# same file bun would create there itself.
seed_bun_global_dir() {
  local global_dir="$BUN_HOME/install/global"
  mkdir -p "$global_dir"
  if [ ! -f "$global_dir/package.json" ]; then
    printf '{\n  "private": true\n}\n' > "$global_dir/package.json"
  fi
}

ensure_bun_on_path() {
  # The bun installer adds ~/.bun/bin to the shell profile; make sure the
  # `company` shim is reachable from new shells even when bun was already
  # present but its bin dir was not exported.
  case ":$PATH:" in
    *":$BUN_BIN_DIR:"*) ;;
    *)
      export PATH="$BUN_BIN_DIR:$PATH"
      if ! grep -q '\.bun/bin' "$HOME/.bashrc" 2>/dev/null; then
        echo '' >> "$HOME/.bashrc"
        echo '# bun global packages (OpenCompany installer)' >> "$HOME/.bashrc"
        echo 'export PATH="$HOME/.bun/bin:$PATH"' >> "$HOME/.bashrc"
      fi
      ;;
  esac
}

# =============================================================================
# Main Installation Flow
# =============================================================================

main() {
  echo ""
  info "Checking dependencies..."
  echo ""

  # Check and install dependencies
  check_bun || install_bun
  check_python || install_python
  check_uv || install_uv
  ensure_bun_on_path
  seed_bun_global_dir

  remove_legacy_npm_installs

  echo ""
  info "Installing OpenCompany..."
  echo ""

  # OPENCOMPANY_VERSION pins a release (the cli/terraform startup scripts set
  # it). Otherwise ask opencompany.sh which release is current; if that is
  # unreachable, fall back to the registry's latest tag.
  VERSION="${OPENCOMPANY_VERSION:-$(curl -fsSL --max-time 10 https://opencompany.sh/version 2>/dev/null | tr -d '[:space:]' || true)}"
  PKG="${PKG_NAME}${VERSION:+@$VERSION}"
  # Global install as the current user: bun's global root is user-owned, so
  # no sudo and no root-owned venvs (docs-internal/errors.md #16).
  bun add -g "$PKG" || error_exit "bun add -g $PKG failed."

  # bun runs no lifecycle scripts for a global package, so provision the Python
  # side now rather than on the first `company` command (which would do it too).
  # The shim is addressed through bun's own answer for the global bin dir.
  COMPANY="$(bun pm bin -g)/company"
  info "Provisioning the Python environment..."
  "$COMPANY" provision || error_exit "Provisioning failed. Re-run with: company provision"

  echo ""
  echo -e "${GREEN}============================================${NC}"
  echo -e "${GREEN}  OpenCompany installed successfully!${NC}"
  echo -e "${GREEN}============================================${NC}"
  echo ""
  echo "  Start OpenCompany:"
  echo "    company start"
  echo ""
  echo "  Optional: Enable JS-rendered web scraping:"
  echo "    playwright install chromium"
  echo ""
  echo "  Run diagnostics:"
  echo "    company doctor"
  echo ""
  echo "  New shells pick up the bun bin dir from your profile; in this one run:"
  echo "    export PATH=\"\$HOME/.bun/bin:\$PATH\""
  echo ""
}

# Run main
main
