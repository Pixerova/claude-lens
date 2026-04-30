# claude-lens — Developer Setup

The **sidecar** is a local Python (FastAPI) process that reads Claude session files and polls the Anthropic OAuth API. The Tauri widget connects to it at `http://127.0.0.1:8765`.

---

## Prerequisites

Run the bootstrap script once. It verifies all required tools, installs Node dependencies, creates the Python virtual environment, and confirms the sidecar packages are importable:

```bash
./setup.sh
```

If any tool is missing, the script will tell you how to install it.

---

## Running in development

Two processes are needed — run each in its own terminal.

**Terminal 1 — Python sidecar:**

```bash
cd sidecar
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8765 --reload --reload-exclude 'tests/*'
```

Or via the npm shortcut from the repo root:

```bash
npm run sidecar
```

**Terminal 2 — Tauri widget:**

```bash
npm run tauri dev
```

The overlay window will appear. It fetches data from the sidecar at `http://127.0.0.1:8765`.

---

## Running tests

```bash
# Python sidecar
pytest sidecar/tests/ -v

# Frontend (TypeScript / React)
npm test
```

---

## Authentication

claude-lens reads your OAuth token automatically from the macOS Keychain (stored there by the Claude desktop app under `Claude Code-credentials`). No setup required.

To verify authentication is working:

```bash
curl http://127.0.0.1:8765/auth/status
# expect: {"authenticated": true, ...}
```

If `authenticated` is false, make sure Claude Code or the Claude desktop app has been used at least once on this machine so the token exists in the Keychain.

---

## Keyboard shortcut

**Option+Space** — toggle the widget on/off from anywhere.

Tray icon: left-click to toggle, right-click for Open / Quit menu.

---

## Data locations

| Path | Contents |
|------|----------|
| `~/.claude-lens/claudelens.db` | SQLite: usage snapshots, session summaries |
| `~/.claude-lens/state.json` | Ephemeral poll state + offline cache |
| `~/.claude/projects/**/*.jsonl` | Claude Code session logs (read-only) |
| `~/Library/Application Support/Claude/claude-code-sessions/` | Cowork session logs (read-only) |
