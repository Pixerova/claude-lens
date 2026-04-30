#!/usr/bin/env bash
# scripts/build_sidecar.sh — Compile the Python sidecar into a standalone binary.
#
# Uses PyInstaller to produce a single-file binary at the path Tauri expects:
#   src-tauri/binaries/claude-lens-sidecar-<target-triple>
#
# Run this:
#   - Before your first `npm run tauri build` on a new machine
#   - After any changes to sidecar/ Python code before a production build
#
# Dev mode (npm run tauri dev) does NOT need this — it uses the live Python process.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIDECAR_DIR="$REPO_ROOT/sidecar"
BINARIES_DIR="$REPO_ROOT/src-tauri/binaries"
VENV="$SIDECAR_DIR/.venv"

# ── Rust host triple ──────────────────────────────────────────────────────────

# Use the Rust host triple so the binary name matches what Tauri bundles.
# This may differ from `uname -m` (e.g. an x86_64 Rust toolchain under Rosetta).
if command -v rustc >/dev/null 2>&1; then
    RUSTC_BIN="rustc"
elif [ -x "${HOME}/.cargo/bin/rustc" ]; then
    RUSTC_BIN="${HOME}/.cargo/bin/rustc"
else
    echo "ERROR: rustc not found. Install the Rust toolchain first." >&2
    echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh" >&2
    exit 1
fi

TRIPLE="$("$RUSTC_BIN" -vV 2>/dev/null | awk '/^host:/ {print $2}')"
if [ -z "$TRIPLE" ]; then
    echo "ERROR: Could not determine Rust host triple from '$RUSTC_BIN'. The toolchain may be incomplete." >&2
    exit 1
fi

echo "Target triple: $TRIPLE"

# ── Venv check ────────────────────────────────────────────────────────────────

if [ ! -f "$VENV/bin/python" ]; then
    echo "ERROR: No virtual environment found at sidecar/.venv" >&2
    echo "  Run ./setup.sh first, or:" >&2
    echo "    python3 -m venv sidecar/.venv && sidecar/.venv/bin/pip install -r sidecar/requirements.txt" >&2
    exit 1
fi

# ── PyInstaller ───────────────────────────────────────────────────────────────

if ! "$VENV/bin/python" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller not found — installing..."
    "$VENV/bin/pip" install pyinstaller --quiet
    if ! "$VENV/bin/python" -c "import PyInstaller" 2>/dev/null; then
        echo "ERROR: PyInstaller installation failed." >&2
        echo "  Try manually: $VENV/bin/pip install pyinstaller" >&2
        exit 1
    fi
fi

# ── Compile ───────────────────────────────────────────────────────────────────

echo "Compiling sidecar/main.py → src-tauri/binaries/claude-lens-sidecar-$TRIPLE ..."

mkdir -p "$BINARIES_DIR"
cd "$SIDECAR_DIR"

if ! "$VENV/bin/pyinstaller" \
        --onefile \
        --name claude-lens-sidecar \
        --distpath dist \
        --clean \
        --noconfirm \
        main.py; then
    echo "" >&2
    echo "ERROR: PyInstaller compilation failed. See output above for details." >&2
    echo "  Common causes:" >&2
    echo "    - Missing imports: add them to sidecar/requirements.txt" >&2
    echo "    - Hidden imports: add --hidden-import flags to this script" >&2
    exit 1
fi

# ── Copy to Tauri binaries dir ────────────────────────────────────────────────

DEST="$BINARIES_DIR/claude-lens-sidecar-$TRIPLE"
cp "dist/claude-lens-sidecar" "$DEST"

echo ""
echo "Binary written to: src-tauri/binaries/claude-lens-sidecar-$TRIPLE"
echo ""
echo "You can now run: npm run tauri build"
