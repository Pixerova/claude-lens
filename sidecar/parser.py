"""
parser.py — Parse Claude Code JSONL sessions and Cowork JSON sessions.
            Also sets up filesystem watchers for live updates.

Sources:
  Claude Code  → ~/.claude/projects/**/*.jsonl
  Cowork       → ~/Library/Application Support/Claude/claude-code-sessions/**/*.json

Each parsed session is summarised and upserted into the session_summaries table.
"""

import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

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
    / "claude-code-sessions"
)


# ── JSONL parser (Claude Code) ────────────────────────────────────────────────

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
      message     : { role, content }
                    content may contain usage: { input_tokens, output_tokens,
                    cache_creation_input_tokens, cache_read_input_tokens }
      model       : str (on assistant messages)
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
    session_id  = None
    timestamps  = []
    model       = "unknown"
    project     = None
    total_input = 0
    total_output = 0
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

        # Model is on assistant messages
        if evt.get("type") == "assistant" or evt.get("role") == "assistant":
            m = evt.get("model")
            if m and m != "unknown":
                model = m

        # Token usage lives inside message.usage on assistant events
        msg = evt.get("message", {})
        if isinstance(msg, dict):
            usage = msg.get("usage", {})
            if isinstance(usage, dict):
                total_input       += usage.get("input_tokens", 0)
                total_output      += usage.get("output_tokens", 0)
                total_cache_read  += usage.get("cache_read_input_tokens", 0)
                total_cache_write += usage.get("cache_creation_input_tokens", 0)

    if not session_id or not timestamps:
        # Fall back to filename as session_id
        session_id = session_id or jsonl_path.stem

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
        "session_id":   session_id,
        "source":       "code",
        "started_at":   started_at,
        "ended_at":     ended_at,
        "duration_sec": duration_sec,
        "model":        model,
        "project":      project,
        "cost_usd":     cost_usd,
    }


# ── JSON parser (Cowork) ──────────────────────────────────────────────────────

def parse_cowork_session(json_path: Path) -> Optional[dict]:
    """
    Parse a single Cowork session .json file.
    Cowork stores sessions as a JSON object (not JSONL).
    Field names may differ from Claude Code — we handle both known schemas.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("Cannot read Cowork session %s: %s", json_path, exc)
        return None

    if not isinstance(data, dict):
        return None

    session_id   = data.get("sessionId") or data.get("id") or json_path.stem
    started_at   = data.get("startedAt") or data.get("created_at") or data.get("timestamp")
    ended_at     = data.get("endedAt")   or data.get("updated_at") or started_at
    model        = data.get("model", "unknown")
    project      = data.get("project") or data.get("cwd") or data.get("title")
    if project and "/" in str(project):
        project = Path(project).name

    # Token usage
    usage = data.get("usage") or data.get("tokens") or {}
    input_tokens  = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read    = usage.get("cache_read_input_tokens", 0)
    cache_write   = usage.get("cache_creation_input_tokens", 0)

    if not started_at:
        log.debug("Cowork session %s missing timestamp, skipping", json_path.name)
        return None

    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        duration_sec = max(int((t1 - t0).total_seconds()), 0)
    except (ValueError, AttributeError):
        duration_sec = 0

    cost_usd = compute_cost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )

    return {
        "session_id":   session_id,
        "source":       "cowork",
        "started_at":   started_at,
        "ended_at":     ended_at,
        "duration_sec": duration_sec,
        "model":        model,
        "project":      project,
        "cost_usd":     cost_usd,
    }


# ── Batch scanner ─────────────────────────────────────────────────────────────

def scan_all_sessions(retention_days: int = 30) -> int:
    """
    Walk both source directories and upsert all session summaries.
    Called once on startup; returns count of sessions processed.
    """
    count = 0

    # Claude Code
    if CLAUDE_CODE_DIR.exists():
        for jsonl_file in CLAUDE_CODE_DIR.rglob("*.jsonl"):
            summary = parse_code_session(jsonl_file)
            if summary:
                upsert_session_summary(**summary)
                count += 1

    # Cowork
    if COWORK_DIR.exists():
        for json_file in COWORK_DIR.rglob("*.json"):
            summary = parse_cowork_session(json_file)
            if summary:
                upsert_session_summary(**summary)
                count += 1

    log.info("Startup scan complete: %d sessions processed", count)
    return count


def _process_file(path: Path) -> None:
    """Parse a single file and upsert, based on extension."""
    if path.suffix == ".jsonl":
        summary = parse_code_session(path)
    elif path.suffix == ".json":
        summary = parse_cowork_session(path)
    else:
        return
    if summary:
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
