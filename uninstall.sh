#!/usr/bin/env bash
# OpenCompany Uninstaller
#
# Usage: curl -fsSL https://raw.githubusercontent.com/zeenie-ai/OpenCompany/main/uninstall.sh | bash
#
# Removes the bun global install (the current channel) and, when npm happens
# to be present, any legacy npm install of the scoped package or the official
# pre-rebrand `machinaos` package. The unrelated unscoped npm package named
# `opencompany` is never touched. ~/.opencompany (workflows, credentials,
# downloaded runtimes) is left in place.

set -e

echo "Uninstalling OpenCompany..."
echo ""

remove_bun_global_package() {
  local package_name="$1"
  local display_name="$2"

  command -v bun &> /dev/null || return 0
  # `bun remove -g` is the only probe: `bun pm ls -g` aborts on a stray npm
  # lockfile in bun's global dir, and removing an absent package is harmless.
  if bun remove -g "$package_name" &> /dev/null; then
    echo "$display_name removed"
  else
    echo "$display_name not installed with bun (or removal failed; try: bun remove -g $package_name)"
  fi
}

# Legacy npm channel. Remove only OpenCompany's scoped package and the
# official pre-rebrand package.
remove_global_package() {
  local package_name="$1"
  local display_name="$2"

  command -v npm &> /dev/null || return 0
  if ! npm list -g --depth=0 "$package_name" &> /dev/null; then
    echo "$display_name not installed with npm"
    return 0
  fi

  if npm uninstall -g "$package_name" &> /dev/null; then
    :
  elif command -v sudo &> /dev/null; then
    echo "Retrying $display_name removal with sudo..."
    sudo npm uninstall -g "$package_name"
  else
    echo "Unable to remove $display_name. Try: sudo npm uninstall -g $package_name" >&2
    exit 1
  fi

  echo "$display_name removed"
}

remove_bun_global_package '@zeenie-ai/opencompany' '@zeenie-ai/opencompany'
remove_global_package '@zeenie-ai/opencompany' 'legacy npm install of @zeenie-ai/opencompany'
remove_global_package 'machinaos' 'legacy machinaos package'

echo ""
echo "Done!"
echo ""
