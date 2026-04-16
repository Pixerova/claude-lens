# Claude Lens

> macOS widget for Claude Pro — real-time usage gauges, session insights, and smart suggestions to stop leaving weekly capacity on the table.

---

## What it is

Claude Lens is a macOS menu bar app and floating overlay widget for Claude Pro subscribers. It shows your live plan limits (current session and weekly), breaks down usage by source (Claude Code, Cowork, browser chat), and surfaces AI-powered suggestions so you make the most of every reset window.

Most Claude usage monitors answer: *"How much have I spent?"* Claude Lens answers: *"How much do I have left — and what should I do with it?"*

## Features

- **Live plan limits** — current session % and weekly % with countdown to reset, pulled from the Anthropic OAuth API
- **Dual-surface UX** — ambient menu bar icon that reflects your usage level, plus a floating overlay for the full dashboard
- **Session breakdown** — usage by source (Claude Code / Cowork / other), duration, and estimated cost
- **Smart suggestions** — rule-based triggers + Claude-powered recommendations when your usage is low or a reset is approaching
- **Dynamic polling** — checks more frequently as you approach limits, backs off when usage is low
- **Fully local** — reads from your macOS Keychain and local session files; nothing leaves your machine

## Status

🚧 In development

## Tech stack

- [Tauri v2](https://v2.tauri.app) — app shell
- React + TypeScript — frontend
- Python (FastAPI) — data sidecar
- Recharts + Tailwind CSS — UI

## License

MIT
