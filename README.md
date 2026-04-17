# Claude Lens

> macOS widget for Claude Pro — real-time usage gauges, session insights, and smart suggestions to stop leaving weekly capacity on the table.

---

## What it is

Claude Lens is a macOS menu bar app and floating overlay widget for Claude Pro subscribers. It shows your live plan limits (current session and weekly), breaks down usage by source (Claude Code vs Cowork), and surfaces AI-powered suggestions so you make the most of every reset window.

Most Claude usage monitors answer: *"How much have I spent?"* Claude Lens answers: *"How much do I have left — and what should I do with it?"*

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

Claude Lens reads your live plan limits from the Anthropic OAuth API (via the token already stored in your macOS Keychain by Claude Code — no setup required). It parses local session files from Claude Code and Cowork to attribute that usage between sources. Everything stays on your machine.

The poll interval adapts dynamically: checking every minute when you're near a limit, backing off to once an hour when usage is low.

## Status

🚧 In active development

## Tech stack

- [Tauri v2](https://v2.tauri.app) — app shell
- React + TypeScript — frontend
- Python (FastAPI) — data sidecar
- Recharts + Tailwind CSS — UI

## License

MIT
