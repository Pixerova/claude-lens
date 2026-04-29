#!/usr/bin/env bash
# setup.sh — Bootstrap the claude-lens development environment.
#
# Checks for required tools, installs frontend dependencies, creates the
# Python virtual environment, and runs a quick sidecar health check.
#
# Safe to run more than once: skips steps already complete.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SIDECAR_DIR="$REPO_ROOT/sidecar"
VENV="$SIDECAR_DIR/.venv"
SIDECAR_PORT=8765

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
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
    PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        ok "python3 $PY_VER"
    else
        fail "python3 $PY_VER found — 3.11 or newer is required."
        echo "  Install via: brew install python@3.11"
        MISSING=1
    fi
else
    fail "python3 not found."
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
    python3 -m venv "$VENV"
    ok "Created $VENV"
fi

ok "Installing sidecar/requirements.txt"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SIDECAR_DIR/requirements.txt"
ok "Python dependencies installed"

# ── Sidecar sanity check ──────────────────────────────────────────────────────

step "Running sidecar health check"

SIDECAR_PID=""

cleanup() {
    if [ -n "$SIDECAR_PID" ]; then
        kill "$SIDECAR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Start the sidecar in the background
cd "$SIDECAR_DIR"
SIDECAR_LOG="$(mktemp)"
"$VENV/bin/python" main.py >"$SIDECAR_LOG" 2>&1 &
SIDECAR_PID=$!
cd "$REPO_ROOT"

# Wait up to 10 seconds for /health to respond 200
HEALTH_OK=0
for i in $(seq 1 10); do
    sleep 1
    HTTP_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$SIDECAR_PORT/health" 2>/dev/null || echo 000)"
    if [ "$HTTP_STATUS" = "200" ]; then
        HEALTH_OK=1
        break
    fi
done

if [ "$HEALTH_OK" -eq 1 ]; then
    ok "Sidecar health check PASSED (GET /health → 200)"
    rm -f "$SIDECAR_LOG"
else
    fail "Sidecar health check FAILED — /health did not return 200 within 10 seconds"
    echo "  Sidecar output:"
    cat "$SIDECAR_LOG"
    rm -f "$SIDECAR_LOG"
    exit 1
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}Setup complete.${RESET}"
echo ""
echo "  Dev:     npm run tauri dev"
echo "  Release: scripts/build_sidecar.sh && npm run tauri build"
echo "  Tests:   pytest sidecar/tests/  |  npm test"
