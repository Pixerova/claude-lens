"""
parser.py — Parse Claude Code JSONL sessions and Cowork JSONL sessions.
            Also sets up filesystem watchers for live updates.

Sources:
  Claude Code  → ~/.claude/projects/**/*.jsonl
  Cowork       → ~/Library/Application Support/Claude/local-agent-mode-sessions/**/*.jsonl

Both sources use the same JSONL format; Cowork sessions are tagged source="cowork"
after parsing. Each parsed session is summarised and upserted into the session_summaries table.
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from pricing import compute_cost
from db import upsert_session_summary

log = logging.getLogger(__name__)

# ── Source directories ────────────────────────────────────────────────────────

CLAUDE_CODE_DIR = Path.home() / ".claude" / "projects"
COWORK_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Claude"
    / "local-agent-mode-sessions"
)


# ── JSONL parser (Claude Code) ────────────────────────────────────────────────

def _extract_title(content) -> Optional[str]:
    """
    Pull plain text from a message content value (string or content-block array).
    Returns the first non-empty text truncated to 200 characters, or None.
    """
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = " ".join(parts).strip()
    else:
        return None
    return text[:200] if text else None


def parse_code_session(jsonl_path: Path) -> Optional[dict]:
    """
    Parse a single Claude Code .jsonl session file.
    Returns a dict of session fields, or None if the file is empty / unparseable.

    JSONL format: one JSON object per line. Each line has:
      type        : "user" | "assistant" | "tool_use" | "tool_result"
      timestamp   : ISO 8601
      sessionId   : str
      cwd         : str   (working directory → project)
      gitBranch   : str
      message     : { role, content, model (on assistant), usage (on assistant) }
                    usage: { input_tokens, output_tokens,
                             cache_creation_input_tokens, cache_read_input_tokens }
    """
    events = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        log.debug("Cannot read %s: %s", jsonl_path, exc)
        return None

    if not events:
        return None

    # ── Extract fields ──────────────────────────────────────────────────────
    session_id       = None
    timestamps       = []
    model            = "unknown"
    project          = None
    title            = None
    total_input      = 0
    total_output     = 0
    total_cache_read = 0
    total_cache_write = 0

    for evt in events:
        if not isinstance(evt, dict):
            continue

        ts = evt.get("timestamp")
        if ts:
            timestamps.append(ts)

        if not session_id:
            session_id = evt.get("sessionId")

        if not project:
            cwd = evt.get("cwd") or evt.get("workingDirectory")
            if cwd:
                project = Path(cwd).name   # use the directory leaf name

        msg = evt.get("message", {})
        if not isinstance(msg, dict):
            msg = {}

        # Title: first user-typed message only. Reject list content — tool-result
        # events also carry type="user" but have list content, not a typed string.
        if title is None and (evt.get("type") == "user" or msg.get("role") == "user"):
            content = msg.get("content")
            if isinstance(content, str):
                title = _extract_title(content)

        # Model: nested inside message dict on assistant events.
        # Skip "<synthetic>" — Claude Code's internal label for generated events
        # (tool summaries, context injections); they carry zero tokens and no real model.
        if evt.get("type") == "assistant" or msg.get("role") == "assistant":
            m = msg.get("model")
            if m and m not in ("unknown", "<synthetic>"):
                model = m

            # Token usage: only present on assistant events per the JSONL contract.
            # Nesting here prevents silent over-counting if future format versions
            # attach usage keys to non-assistant event types.
            usage = msg.get("usage", {})
            if isinstance(usage, dict):
                total_input       += usage.get("input_tokens", 0)
                total_output      += usage.get("output_tokens", 0)
                total_cache_read  += usage.get("cache_read_input_tokens", 0)
                total_cache_write += usage.get("cache_creation_input_tokens", 0)

    if not session_id:
        session_id = jsonl_path.stem

    if not timestamps:
        return None

    timestamps.sort()
    started_at = timestamps[0]
    ended_at   = timestamps[-1]

    # Duration in seconds
    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        duration_sec = max(int((t1 - t0).total_seconds()), 0)
    except ValueError:
        duration_sec = 0

    cost_usd = compute_cost(
        model=model,
        input_tokens=total_input,
        output_tokens=total_output,
        cache_read_tokens=total_cache_read,
        cache_write_tokens=total_cache_write,
    )

    return {
        "session_id":        session_id,
        "source":            "code",
        "started_at":        started_at,
        "ended_at":          ended_at,
        "duration_sec":      duration_sec,
        "model":             model,
        "project":           project,
        "cost_usd":          cost_usd,
        "title":             title,
        "input_tokens":      total_input,
        "output_tokens":     total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
    }


# ── Batch scanner ─────────────────────────────────────────────────────────────

def scan_all_sessions(retention_days: int = 30) -> int:
    """
    Walk both source directories and upsert all session summaries.
    Only processes files modified within retention_days days.
    Called once on startup; returns count of sessions processed.
    """
    cutoff = time.time() - retention_days * 86400
    code_count = 0
    code_skipped = 0
    cowork_count = 0
    cowork_skipped = 0

    # Claude Code
    if CLAUDE_CODE_DIR.exists():
        for jsonl_file in CLAUDE_CODE_DIR.rglob("*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                code_skipped += 1
                continue
            summary = parse_code_session(jsonl_file)
            if summary:
                upsert_session_summary(**summary)
                log.debug("Code Session: %s | project=%s model=%s", jsonl_file.name, summary.get("project"), summary.get("model"))
                code_count += 1
    else:
        log.info("Code Sessions directory not found (skipping): %s", CLAUDE_CODE_DIR)

    # Cowork — JSONL files nested inside local-agent-mode-sessions VMs,
    # same format as Claude Code sessions.
    if COWORK_DIR.exists():
        for jsonl_file in COWORK_DIR.rglob("*.jsonl"):
            if jsonl_file.name == "audit.jsonl":
                continue
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                cowork_skipped += 1
                continue
            summary = parse_code_session(jsonl_file)
            if summary:
                summary["source"] = "cowork"
                upsert_session_summary(**summary)
                log.debug("Cowork Session: %s | project=%s model=%s", jsonl_file.name, summary.get("project"), summary.get("model"))
                cowork_count += 1
    else:
        log.info("Cowork Sessions directory not found (skipping): %s", COWORK_DIR)

    log.info(
        "Startup scan complete: %d Code, %d Cowork sessions parsed; "
        "%d Code, %d Cowork files skipped (outside %d-day retention window)",
        code_count, cowork_count, code_skipped, cowork_skipped, retention_days,
    )
    return code_count + cowork_count


def _process_file(path: Path) -> None:
    """Parse a single file and upsert, based on extension and location."""
    if path.suffix != ".jsonl" or path.name == "audit.jsonl":
        return
    summary = parse_code_session(path)
    if summary:
        # Tag as cowork if it lives inside the Cowork sessions directory
        if COWORK_DIR in path.parents:
            summary["source"] = "cowork"
        upsert_session_summary(**summary)
        log.debug("Upserted session %s from %s", summary["session_id"], path.name)


# ── File watcher ──────────────────────────────────────────────────────────────

class _SessionFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            _process_file(Path(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            _process_file(Path(event.src_path))


def start_watchers() -> Observer:
    """
    Start watchdog observers on both source directories.
    Returns the Observer so the caller can stop it on shutdown.
    """
    observer = Observer()
    handler = _SessionFileHandler()

    watched = 0
    for directory in [CLAUDE_CODE_DIR, COWORK_DIR]:
        if directory.exists():
            observer.schedule(handler, str(directory), recursive=True)
            log.info("Watching %s", directory)
            watched += 1
        else:
            log.info("Directory not found (skipping watcher): %s", directory)

    if watched > 0:
        observer.start()
        log.info("File watchers started")
    else:
        log.warning("No source directories found — file watchers not started")

    return observer
