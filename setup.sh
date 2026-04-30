#!/usr/bin/env bash
# setup.sh — Bootstrap the claude-lens development environment.
#
# Checks for required tools, installs frontend dependencies, creates the
# Python virtual environment, and verifies sidecar packages are importable.
#
# Safe to run more than once: skips steps already complete.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SIDECAR_DIR="$REPO_ROOT/sidecar"
VENV="$SIDECAR_DIR/.venv"

# ── Colours ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RESET='\033[0m'

step()  { echo -e "\n${CYAN}▶ $*${RESET}"; }
ok()    { echo -e "${GREEN}  ✓ $*${RESET}"; }
fail()  { echo -e "${RED}  ✗ $*${RESET}"; }

# ── Tool checks ───────────────────────────────────────────────────────────────

step "Checking required tools"

MISSING=0

# Rust / Cargo
if command -v rustc >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1; then
    ok "rustc $(rustc --version 2>/dev/null | awk '{print $2}')"
else
    fail "Rust toolchain not found."
    echo "  Install via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    MISSING=1
fi

# Node / npm
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    ok "node $(node --version)  npm $(npm --version)"
else
    fail "Node.js not found."
    echo "  Install via: brew install node   or   https://nodejs.org"
    MISSING=1
fi

# Python 3.11+
# Try the unversioned python3 first; if it's too old, fall back to the
# version-specific aliases that Homebrew installs (e.g. python3.11).
PYTHON=""
PY_VER=""

if command -v python3 >/dev/null 2>&1; then
    _ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [ "$(echo "$_ver" | cut -d. -f2)" -ge 11 ]; then
        PYTHON="python3"
        PY_VER="$_ver"
    fi
fi

if [ -z "$PYTHON" ]; then
    for _candidate in python3.13 python3.12 python3.11; do
        if command -v "$_candidate" >/dev/null 2>&1; then
            PYTHON="$_candidate"
            PY_VER="$("$_candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
            break
        fi
    done
fi

if [ -n "$PYTHON" ]; then
    ok "$PYTHON $PY_VER"
else
    fail "Python 3.11 or newer not found."
    echo "  Install via: brew install python@3.11"
    MISSING=1
fi

# Tauri CLI — accept either cargo plugin or npm shim
TAURI_OK=0
if cargo tauri --version >/dev/null 2>&1; then
    ok "tauri-cli (cargo plugin)"
    TAURI_OK=1
elif npx --no tauri --version >/dev/null 2>&1; then
    ok "tauri-cli (npm / npx)"
    TAURI_OK=1
fi
if [ "$TAURI_OK" -eq 0 ]; then
    fail "Tauri CLI not found."
    echo "  Install via: cargo install tauri-cli --version '^2'"
    echo "  Or via npm:  npm install -g @tauri-apps/cli"
    MISSING=1
fi

if [ "$MISSING" -ne 0 ]; then
    echo ""
    echo "Please install the missing tools above and re-run ./setup.sh"
    exit 1
fi

# ── Frontend dependencies ─────────────────────────────────────────────────────

step "Installing frontend dependencies (npm install)"
cd "$REPO_ROOT"
npm install
ok "node_modules ready"

# ── Python virtual environment ────────────────────────────────────────────────

step "Setting up Python virtual environment"

if [ -f "$VENV/bin/python" ]; then
    ok "Virtual environment already exists at sidecar/.venv — skipping creation"
else
    "$PYTHON" -m venv "$VENV"
    ok "Created $VENV"
fi

ok "Installing sidecar/requirements.txt"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SIDECAR_DIR/requirements.txt"
ok "Python dependencies installed"

# ── Sidecar import check ──────────────────────────────────────────────────────

step "Verifying sidecar Python dependencies"

if "$VENV/bin/python" -c "import fastapi, uvicorn, httpx, watchdog, pydantic" 2>/dev/null; then
    ok "All sidecar packages importable"
else
    fail "One or more sidecar packages failed to import — try: $VENV/bin/pip install -r sidecar/requirements.txt"
    exit 1
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}Setup complete.${RESET}"
echo ""
echo "  Dev:     npm run tauri dev"
echo "  Release: scripts/build_sidecar.sh && npm run tauri build"
echo "  Tests:   pytest sidecar/tests/  |  npm test"
