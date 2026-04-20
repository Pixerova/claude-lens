"""
conftest.py — Shared pytest fixtures for Claude Lens M1 test suite.

Key fixture: `isolated_db` patches db.DB_PATH and db.DATA_DIR to a
temporary directory so every test gets a clean, empty database without
touching ~/.claudelens.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

# Ensure the sidecar package is importable from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── DB isolation ──────────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """
    Redirect the SQLite database to a temp directory.
    Returns the temp db path for assertions.
    """
    import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "claudelens.db")
    db.init_db()
    return tmp_path / "claudelens.db"


# ── State file isolation ──────────────────────────────────────────────────────

@pytest.fixture()
def isolated_state(tmp_path, monkeypatch):
    """Redirect state.json to a temp directory."""
    import poller
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(poller, "STATE_PATH", state_path)
    return state_path


# ── Sample data factories ─────────────────────────────────────────────────────

def make_snapshot(session_pct=0.21, weekly_pct=0.25, offset_minutes=0):
    """Return a dict of plan usage snapshot kwargs."""
    base = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return {
        "session_pct":    session_pct,
        "session_resets": (base + timedelta(hours=4)).isoformat(),
        "weekly_pct":     weekly_pct,
        "weekly_resets":  (base + timedelta(days=3)).isoformat(),
    }


def make_session(
    session_id="sess-001",
    source="code",
    started_offset_hours=1,
    duration_sec=2700,
    model="claude-sonnet-4-6",
    project="my-project",
    cost_usd=0.11,
):
    """Return a dict of session summary kwargs."""
    started = datetime.now(timezone.utc) - timedelta(hours=started_offset_hours)
    ended = started + timedelta(seconds=duration_sec)
    return {
        "session_id":   session_id,
        "source":       source,
        "started_at":   started.isoformat(),
        "ended_at":     ended.isoformat(),
        "duration_sec": duration_sec,
        "model":        model,
        "project":      project,
        "cost_usd":     cost_usd,
    }


# ── JSONL fixture helpers ─────────────────────────────────────────────────────

def write_jsonl(path: Path, events: list[dict]) -> Path:
    """Write a list of dicts as JSONL to path."""
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def make_code_events(
    session_id="test-session-abc",
    cwd="/Users/martha/projects/my-app",
    model="claude-sonnet-4-6",
    input_tokens=1000,
    output_tokens=500,
    cache_read=200,
    cache_write=100,
):
    """Build a minimal but realistic set of Claude Code JSONL events."""
    t0 = "2026-04-10T09:00:00+00:00"
    t1 = "2026-04-10T09:45:00+00:00"
    return [
        {
            "type": "user",
            "sessionId": session_id,
            "timestamp": t0,
            "cwd": cwd,
            "message": {"role": "user", "content": "Write me some tests"},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": t1,
            "cwd": cwd,
            "message": {
                "role": "assistant",
                "model": model,
                "content": "Here are your tests...",
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_write,
                },
            },
        },
    ]
