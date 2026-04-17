#!/usr/bin/env bash
# Compiles the Python sidecar into a standalone binary for production builds.
#
# Run this:
#   - Before your first `cargo tauri build` on a new machine
#   - After any changes to sidecar/ Python code before a production build
#
# Dev mode (cargo tauri dev) does NOT need this — it uses the live Python process.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIDECAR_DIR="$REPO_ROOT/sidecar"
BINARIES_DIR="$REPO_ROOT/src-tauri/binaries"

# Detect target triple
ARCH="$(uname -m)"
case "$ARCH" in
  arm64)  TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *)      echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

echo "Building sidecar for $TRIPLE..."

cd "$SIDECAR_DIR"

# Ensure venv exists
if [ ! -f ".venv/bin/python" ]; then
  echo "No .venv found — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# Install PyInstaller if needed
if ! .venv/bin/python -c "import PyInstaller" 2>/dev/null; then
  echo "Installing PyInstaller..."
  .venv/bin/pip install pyinstaller --quiet
fi

# Compile
.venv/bin/pyinstaller --onefile --name sidecar --distpath dist --clean --noconfirm main.py

# Copy to where Tauri expects it
DEST="$BINARIES_DIR/sidecar-$TRIPLE"
cp dist/sidecar "$DEST"
echo "Binary written to src-tauri/binaries/sidecar-$TRIPLE"
echo "Done. You can now run: cargo tauri build"
