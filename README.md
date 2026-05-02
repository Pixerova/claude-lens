# claude-lens

> macOS widget for Claude Pro — real-time usage gauges, session insights, and smart suggestions to stop leaving weekly capacity on the table.
Built with Claude Pro!

| Collapsed | Expanded | Suggestions |
|:---------:|:--------:|:-----------:|
| ![Collapsed view](docs/claude-lens_collapsed_view.png) | ![Expanded view](docs/claude-lens_expanded_view.png) | ![Suggestions](docs/claude-lens_suggestions.png) |

---

## What it is

claude-lens is a macOS menu bar app and floating overlay widget for Claude Pro subscribers. It shows your live plan limits (current session and weekly), breaks down usage by source (Claude Code vs Cowork), and surfaces AI-powered suggestions so you make the most of every reset window.

Most Claude usage monitors answer: *"How much have I spent?"* claude-lens answers: *"How much do I have left — and what could I do with it?"*

---

## Getting started

### Build to Run!

**1. Check prerequisites**

```bash
./setup.sh
```

This verifies you have Rust, Node.js, Python 3.11+, and Tauri CLI installed, then installs Node and Python dependencies. It will tell you exactly what to install if anything is missing.

**2. Build**

> **macOS permission (first time only):** The build script below runs an AppleScript against Finder to configure the DMG window layout. macOS will show an Automation permission dialog the first time — click OK. If you previously denied it, re-enable it in **System Settings → Privacy & Security → Automation** (your terminal app → Finder). Without this the build fails with a generic `error running bundle_dmg.sh` message. To see the underlying cause, run `RUST_LOG=tauri_bundler=debug npm run tauri build`.

```bash
scripts/build_sidecar.sh    # compile Python sidecar → native binary
npm run tauri build         # produce the .app / .dmg bundle
```

**3. Run**

```bash
open "src-tauri/target/release/bundle/macos/claude-lens.app"
```

Or open the `.dmg` from `src-tauri/target/release/bundle/dmg/` to install it like any Mac app.

---

For development (hot-reload, tests), see [DEVSETUP.md](DEVSETUP.md).

## What claude-lens shows

**Plan utilization**
- Current session % and weekly % with time until reset, pulled directly from the Anthropic OAuth API
- Visual warning states as limits approach (normal → amber at 80% → critical at 90%)
- Stale indicator when the API hasn't been reached recently

**7-day breakdown**
- Share of tracked usage by source — Claude Code vs Cowork — as a percentage
- Each source's estimated contribution to your weekly plan utilization
- Daily usage distribution over the last 7 days, normalized by source
- Top project by activity this week

**Session list**
- Sessions from the last 7 days with each session's share of your weekly plan
- Code sessions labeled by project folder; Cowork sessions labeled by conversation title

**What it intentionally does not show**
- Cost in USD — not meaningful on MAX plan; absolute dollar values are near-zero and misleading. Plan consumption is expressed as utilization percentages instead.
- Session duration — wall-clock elapsed time is not correlated with actual plan consumption and would encourage optimizing the wrong thing.

## How it works

claude-lens reads your live plan limits from the Anthropic OAuth API (via the token already stored in your macOS Keychain by Claude Code — no setup required). It parses local session files from Claude Code and Cowork to attribute that usage between sources. Everything stays on your machine.

The poll interval adapts dynamically: checking every couple minutes when you're near a limit, backing off to once an hour when usage is low. Outside of configured working hours the app enters a low-power sleep mode and polls every 30 minutes instead. If new Claude session activity is detected after end-of-day, the active window is automatically extended by one hour from the last event — so late working sessions stay live without any manual action.

## Configuration

claude-lens reads `~/.claude-lens/config.json` on startup. The file is optional — all keys have defaults. Any keys you provide are deep-merged over the defaults, so you only need to include what you want to change.

```json
{
  "hotkey": "Option+Space",
  "retentionDays": 30,
  "workingHours": {
    "start": "09:00",
    "end": "17:00"
  },
  "poll": {
    "thresholds": {
      "critical": { "above": 0.90, "intervalSec": 60 },
      "high":     { "above": 0.80, "intervalSec": 120 },
      "elevated": { "above": 0.60, "intervalSec": 300 },
      "normal":   { "above": 0.20, "intervalSec": 600 },
      "low":      { "above": 0.05, "intervalSec": 1800 },
      "minimal":  { "above": 0.00, "intervalSec": 3600 }
    }
  },
  "warnings": {
    "warningPercentage": 0.80,
    "criticalPercentage": 0.90
  }
}
```

| Key | What it controls |
|---|---|
| `hotkey` | Global shortcut to show/hide the widget |
| `retentionDays` | Days of session history to keep |
| `workingHours.start` / `workingHours.end` | Local 24-hour times defining your working day (e.g. `"09:00"` / `"17:00"`). Outside this window the poller drops to once every 30 minutes. If session file activity is detected after end-of-day, the window is automatically extended by one hour from the last event. Sleep mode is always active; change the times to adjust your window. |
| `poll.thresholds` | Adaptive API poll intervals — each tier fires when utilization is above the given fraction; the highest matching tier wins |
| `warnings.warningPercentage` / `warnings.criticalPercentage` | Utilization fraction (0–1) at which the widget transitions to amber / red |


### Add your own suggestions

On first launch the sidecar creates `~/.claude-lens/custom_suggestions.yaml` from a commented template. Add your cards there — the app loads it alongside the built-in suggestions on every restart without touching your edits.

Every custom entry must have its `id` and `category` prefixed with `custom_` (e.g. `id: custom_productivity001`, `category: custom_productivity`). This keeps your suggestions distinct from built-in ones and lets the UI show their source. Run the validator to check before restarting:

```bash
python sidecar/validate_suggestions.py          # checks ~/.claude-lens/custom_suggestions.yaml
python sidecar/validate_suggestions.py path/to/file.yaml   # or a specific file
```

To contribute a built-in suggestion instead, edit [`sidecar/data/suggestions.yaml`](sidecar/data/suggestions.yaml) — the schema and contributor notes are at the top of that file.

## Status

🚧 In active development

## Tech stack

- [Tauri v2](https://v2.tauri.app) — app shell
- React + TypeScript — frontend
- Python (FastAPI) — data sidecar
- Recharts + Tailwind CSS — UI

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for the full text.
