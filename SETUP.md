# Claude Lens — Local Development Setup

One-time bootstrap guide for running Claude Lens on your MacBook Pro.

---

## Prerequisites

### 1. Rust toolchain

Tauri requires Rust. Install via rustup:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

Verify:
```bash
rustc --version   # expect 1.77+
cargo --version
```

### 2. Node.js ≥ 20

If you're not already on Node 20+:

```bash
# via homebrew
brew install node

# or via nvm
nvm install 20 && nvm use 20
```

### 3. Python ≥ 3.11

macOS ships Python 3.x. Confirm:
```bash
python3 --version
```

If needed: `brew install python@3.11`

---

## Python sidecar setup

```bash
cd ~/Documents/GitHub2015/claude-lens/sidecar

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies (includes pytest for local development)
pip install -r requirements-dev.txt

# Run tests to confirm everything works
pytest tests/ -v
```

---

## Node / Tauri setup

```bash
cd ~/Documents/GitHub2015/claude-lens

# Install JS dependencies
npm install

# Install Tauri CLI
cargo install tauri-cli --version "^2.0"
```

---

## Running in development mode

**Terminal 1 — Python sidecar:**
```bash
cd ~/Documents/GitHub2015/claude-lens/sidecar
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

**Terminal 2 — Tauri dev:**
```bash
cd ~/Documents/GitHub2015/claude-lens
npm run tauri dev
```

The floating widget window will appear. It fetches usage from the sidecar at `http://127.0.0.1:8765`.

---

## Authentication

Claude Lens reads your OAuth token automatically from the macOS Keychain
(stored there by the Claude desktop app under `Claude Code-credentials`).

To verify authentication is working:
```bash
curl http://127.0.0.1:8765/auth/status
# expect: {"authenticated": true, ...}
```

If `authenticated` is false, make sure Claude Code or the Claude desktop app
has been used at least once on this machine so the token exists in the Keychain.

---

## Building for production

```bash
# Build the Python sidecar binary (via PyInstaller)
cd sidecar
pip install pyinstaller
pyinstaller --onefile --name sidecar main.py

# Copy the binary where Tauri expects it
cp dist/sidecar ../src-tauri/binaries/sidecar-aarch64-apple-darwin

# Build the Tauri .app
cd ..
npm run tauri build
```

The final `.app` will be in `src-tauri/target/release/bundle/macos/`.

---

## Project structure

```
claude-lens/
├── sidecar/                  # Python FastAPI sidecar
│   ├── main.py               # FastAPI app (port 8765)
│   ├── db.py                 # SQLite schema + queries
│   ├── keychain.py           # OAuth token from Keychain
│   ├── parser.py             # JSONL/JSON session parsers + watchdog
│   ├── poller.py             # Dynamic usage polling
│   ├── pricing.py            # Token cost computation
│   ├── requirements.txt
│   └── tests/                # pytest suite (141 tests)
├── src/                      # React + TypeScript frontend
│   ├── App.tsx               # Widget root (compact + expanded)
│   ├── hooks/
│   │   ├── useUsage.ts       # Live plan usage + dynamic polling
│   │   └── useSessions.ts    # Session history + chart data
│   ├── components/
│   │   ├── PlanBar.tsx       # Usage bar with colour thresholds
│   │   ├── SessionList.tsx   # Scrollable session rows
│   │   ├── StaleIndicator.tsx# Stale data badge
│   │   └── UsageChart.tsx    # Stacked bar chart (Recharts)
│   └── lib/
│       └── api.ts            # Typed sidecar client
├── src-tauri/                # Tauri shell (minimal Rust)
│   ├── src/lib.rs            # Window, tray icon, global shortcut
│   ├── tauri.conf.json       # Window: 340×420, transparent, alwaysOnTop
│   └── Cargo.toml
└── SETUP.md                  # This file
```

---

## Keyboard shortcut

**Option+Space** — toggle the widget on/off from anywhere.

Tray icon: left-click to toggle, right-click for Open / Quit menu.

---

## Data locations

| Path | Contents |
|------|----------|
| `~/.claudelens/claudelens.db` | SQLite: usage snapshots, session summaries |
| `~/.claudelens/state.json` | Ephemeral poll state + offline cache |
| `~/.claude/projects/**/*.jsonl` | Claude Code session logs (read-only) |
| `~/Library/Application Support/Claude/claude-code-sessions/` | Cowork session logs (read-only) |
