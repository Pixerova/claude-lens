# claude-lens

> macOS widget for Claude Pro — real-time usage gauges, session insights, and smart suggestions to stop leaving weekly capacity on the table.

---

## What it is

claude-lens is a macOS menu bar app and floating overlay widget for Claude Pro subscribers. It shows your live plan limits (current session and weekly), breaks down usage by source (Claude Code vs Cowork), and surfaces AI-powered suggestions so you make the most of every reset window.

Most Claude usage monitors answer: *"How much have I spent?"* claude-lens answers: *"How much do I have left — and what could I do with it?"*

## What it shows

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

claude-lens reads `~/.claudelens/config.json` on startup. The file is optional — all keys have defaults. Any keys you provide are deep-merged over the defaults, so you only need to include what you want to change.

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
  }
}
```

| Key | What it controls |
|---|---|
| `hotkey` | Global shortcut to show/hide the widget |
| `retentionDays` | Days of session history to keep |
| `workingHours.start` / `workingHours.end` | Local 24-hour times defining your working day (e.g. `"09:00"` / `"17:00"`). Outside this window the poller drops to once every 30 minutes. If session file activity is detected after end-of-day, the window is automatically extended by one hour from the last event. Omit the key entirely to disable sleep mode and always poll at the normal rate. |
| `poll.thresholds` | Adaptive API poll intervals — each tier fires when utilization is above the given fraction; the highest matching tier wins |
| `warnings.amberPct` / `warnings.redPct` | Utilization % at which the widget transitions to amber / red |


### Add your own suggestions

Suggestion cards are defined in [`sidecar/data/suggestions.yaml`](sidecar/data/suggestions.yaml). The schema and contributing instructions are documented at the top of that file. To add your own cards, follow the schema, run `python sidecar/validate_suggestions.py` locally to check them, then restart the sidecar.

## Status

🚧 In active development

## Tech stack

- [Tauri v2](https://v2.tauri.app) — app shell
- React + TypeScript — frontend
- Python (FastAPI) — data sidecar
- Recharts + Tailwind CSS — UI

## License

GNU GENERAL PUBLIC LICENSE Version 3
