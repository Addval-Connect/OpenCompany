# OpenCompany Installer for Windows
# Usage: iwr -useb https://raw.githubusercontent.com/zeenie-ai/OpenCompany/main/install.ps1 | iex
#
# This script installs OpenCompany and its dependencies:
# - bun (the JavaScript runtime and package manager; no Node.js, no npm)
# - Python 3.12+ (via winget/choco)
# - uv (Python package manager)
#
# Prefer the desktop app if you just want to use OpenCompany on a laptop; this
# path is for terminal use.

$ErrorActionPreference = "Stop"

$MIN_PYTHON_VERSION = "3.12"
$PKG_NAME = "@zeenie-ai/opencompany"

# Colors
function Write-Color {
    param([string]$Text, [string]$Color = "White")
    Write-Host $Text -ForegroundColor $Color
}

function Info { Write-Color "[INFO] $args" "Cyan" }
function Success { Write-Color "[OK] $args" "Green" }
function Warn { Write-Color "[WARN] $args" "Yellow" }
function Error-Exit { Write-Color "[ERROR] $args" "Red"; exit 1 }

# Banner
Write-Host ""
Write-Color "  OpenCompany" "Cyan"
Write-Host ""
Write-Host "Open-source workflow automation with AI agents"
Write-Host ""

# Check if command exists
function Has-Command {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# Get package manager
function Get-PackageManager {
    if (Has-Command "winget") { return "winget" }
    if (Has-Command "choco") { return "choco" }
    return $null
}

# Refresh PATH from registry
function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# bun installs to $env:BUN_INSTALL (default ~\.bun) and puts global bin shims
# in its bin dir. Where it stores the global package itself varies, so nothing
# below depends on that: the `company` shim knows its own package root and
# `company provision` does the rest.
$BUN_HOME = if ($env:BUN_INSTALL) { $env:BUN_INSTALL } else { Join-Path $env:USERPROFILE ".bun" }
$BUN_BIN_DIR = Join-Path $BUN_HOME "bin"

# =============================================================================
# Dependency Checks and Installation
# =============================================================================

function Check-Bun {
    if (Has-Command "bun") {
        Success "bun $(bun --version)"
        return $true
    }
    return $false
}

function Install-Bun {
    Info "Installing bun (JavaScript runtime and package manager)..."
    Invoke-RestMethod https://bun.sh/install.ps1 | Invoke-Expression
    $env:Path = "$BUN_BIN_DIR;$env:Path"
    Refresh-Path
    $env:Path = "$BUN_BIN_DIR;$env:Path"
    if (-not (Check-Bun)) {
        Error-Exit "Failed to install bun. Install it manually from https://bun.sh and restart PowerShell."
    }
}

function Check-Python {
    foreach ($cmd in @("python", "python3")) {
        if (Has-Command $cmd) {
            $versionOutput = & $cmd --version 2>&1
            if ($versionOutput -match "Python (\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -ge 3 -and $minor -ge 12) {
                    Success "Python $major.$minor ($cmd)"
                    $script:PYTHON_CMD = $cmd
                    return $true
                }
            }
        }
    }
    Warn "Python $MIN_PYTHON_VERSION+ not found"
    return $false
}

function Install-Python {
    Info "Installing Python $MIN_PYTHON_VERSION..."
    $pm = Get-PackageManager

    switch ($pm) {
        "winget" {
            winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        }
        "choco" {
            choco install python312 -y
        }
        default {
            Error-Exit "Please install winget or chocolatey, or install Python manually from https://python.org/"
        }
    }

    Refresh-Path

    if (-not (Check-Python)) {
        Error-Exit "Failed to install Python. Please install manually and restart PowerShell."
    }
}

function Check-Uv {
    if (Has-Command "uv") {
        $version = (uv --version) -replace "uv ", ""
        Success "uv $version"
        return $true
    }
    return $false
}

function Install-Uv {
    Info "Installing uv (Python package manager)..."

    # Try pip first
    if ($script:PYTHON_CMD) {
        try {
            & $script:PYTHON_CMD -m pip install uv 2>&1 | Out-Null
            Refresh-Path
            if (Check-Uv) { return }
        } catch {}
    }

    # Fallback to official installer
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"

    if (-not (Check-Uv)) {
        Error-Exit "Failed to install uv"
    }
}

# A previous npm-based install (or the pre-rebrand `machinaos` package) leaves
# a `company` / `machina` shim on PATH that would shadow the bun one. Remove it
# when npm happens to be around; skip silently otherwise.
function Remove-LegacyNpmInstalls {
    if (-not (Has-Command "npm")) { return }
    foreach ($pkg in @($PKG_NAME, "machinaos")) {
        npm list -g --depth=0 $pkg *> $null
        if ($LASTEXITCODE -eq 0) {
            Info "Removing legacy npm install of $pkg..."
            npm uninstall -g $pkg *> $null
            if ($LASTEXITCODE -ne 0) { Warn "Could not remove $pkg; run: npm uninstall -g $pkg" }
        }
    }
}

# =============================================================================
# Main Installation Flow
# =============================================================================

function Main {
    Write-Host ""
    Info "Checking dependencies..."
    Write-Host ""

    # Check and install dependencies
    if (-not (Check-Bun)) { Install-Bun }
    if (-not (Check-Python)) { Install-Python }
    if (-not (Check-Uv)) { Install-Uv }

    Remove-LegacyNpmInstalls

    Write-Host ""
    Info "Installing OpenCompany..."
    Write-Host ""

    # bun finds its global "project" by walking up from $BUN_INSTALL\install\global
    # until it meets a package.json. A stray package.json or package-lock.json in
    # the user profile (an old npm mishap) therefore hijacks global installs and
    # `bun add -g` fails with "InvalidNPMLockfile" (docs-internal/errors.md #23).
    # Giving the global dir its own manifest stops the walk-up.
    $globalDir = Join-Path $BUN_HOME "install\global"
    New-Item -ItemType Directory -Force -Path $globalDir | Out-Null
    $globalManifest = Join-Path $globalDir "package.json"
    if (-not (Test-Path $globalManifest)) {
        Set-Content -Path $globalManifest -Value '{ "private": true }' -Encoding utf8
    }

    # Global install as the current user (bun's global root is user-owned).
    bun add -g $PKG_NAME
    if ($LASTEXITCODE -ne 0) {
        Error-Exit "bun add -g $PKG_NAME failed."
    }

    # bun runs no lifecycle scripts for a global package, so provision the
    # Python side now rather than on the first `company` command. The shim is
    # addressed through bun's own answer for the global bin dir.
    $company = Join-Path (bun pm bin -g) "company.exe"
    Info "Provisioning the Python environment..."
    & $company provision
    if ($LASTEXITCODE -ne 0) {
        Error-Exit "Provisioning failed. Re-run with: company provision"
    }

    Write-Host ""
    Write-Color "============================================" "Green"
    Write-Color "  OpenCompany installed successfully!" "Green"
    Write-Color "============================================" "Green"
    Write-Host ""
    Write-Host "  Start OpenCompany:"
    Write-Host "    company start"
    Write-Host ""
    Write-Host "  Run diagnostics:"
    Write-Host "    company doctor"
    Write-Host ""
    Write-Host "  If 'company' is not found, open a new PowerShell window (bun's bin dir"
    Write-Host "  was added to your PATH)."
    Write-Host ""
}

# Run main
Main
