"""
db.py — SQLite database setup, schema, and core write helpers.

Database lives at ~/.claudelens/claudelens.db
Tables:
  - plan_usage_snapshots  : one row per OAuth API poll result
  - session_summaries     : one row per local Claude Code / Cowork session
  - suggestion_history    : log of suggestions shown to the user
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = Path.home() / ".claudelens"
DB_PATH  = DATA_DIR / "claudelens.db"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # allow concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_usage_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at      TEXT NOT NULL,
    session_pct      REAL NOT NULL,
    session_resets   TEXT NOT NULL,
    weekly_pct       REAL NOT NULL,
    weekly_resets    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id       TEXT PRIMARY KEY,
    source           TEXT NOT NULL CHECK(source IN ('code', 'cowork')),
    started_at       TEXT NOT NULL,
    ended_at         TEXT NOT NULL,
    duration_sec     INTEGER NOT NULL,
    model            TEXT NOT NULL,
    project          TEXT,
    cost_usd         REAL NOT NULL,
    last_parsed      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestion_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    shown_at         TEXT NOT NULL,
    trigger_rule     TEXT NOT NULL,
    suggestion_text  TEXT NOT NULL,
    dismissed_at     TEXT,
    acted_on         INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_snapshots_time   ON plan_usage_snapshots(recorded_at);
CREATE INDEX IF NOT EXISTS idx_sessions_start   ON session_summaries(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_source  ON session_summaries(source);
"""


def init_db() -> None:
    """Create tables and indexes if they don't exist. Safe to call on every startup."""
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()


# ── Writers ──────────────────────────────────────────────────────────────────

def store_snapshot(
    session_pct: float,
    session_resets: str,
    weekly_pct: float,
    weekly_resets: str,
) -> None:
    """Persist a plan usage API response."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO plan_usage_snapshots
                (recorded_at, session_pct, session_resets, weekly_pct, weekly_resets)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now, session_pct, session_resets, weekly_pct, weekly_resets),
        )
    conn.close()


def upsert_session_summary(
    session_id: str,
    source: str,
    started_at: str,
    ended_at: str,
    duration_sec: int,
    model: str,
    project: Optional[str],
    cost_usd: float,
) -> None:
    """Insert or replace a session summary (re-parse overwrites previous record)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO session_summaries
                (session_id, source, started_at, ended_at, duration_sec,
                 model, project, cost_usd, last_parsed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                ended_at     = excluded.ended_at,
                duration_sec = excluded.duration_sec,
                model        = excluded.model,
                project      = excluded.project,
                cost_usd     = excluded.cost_usd,
                last_parsed  = excluded.last_parsed
            """,
            (session_id, source, started_at, ended_at, duration_sec,
             model, project, cost_usd, now),
        )
    conn.close()


def store_suggestion(trigger_rule: str, suggestion_text: str) -> int:
    """Log a suggestion shown to the user. Returns the new row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO suggestion_history (shown_at, trigger_rule, suggestion_text)
            VALUES (?, ?, ?)
            """,
            (now, trigger_rule, suggestion_text),
        )
        row_id = cursor.lastrowid
    conn.close()
    return row_id


def dismiss_suggestion(suggestion_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE suggestion_history SET dismissed_at = ? WHERE id = ?",
            (now, suggestion_id),
        )
    conn.close()


def mark_suggestion_acted(suggestion_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE suggestion_history SET acted_on = 1 WHERE id = ?",
            (suggestion_id,),
        )
    conn.close()


# ── Readers ──────────────────────────────────────────────────────────────────

def get_latest_snapshot() -> Optional[sqlite3.Row]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM plan_usage_snapshots ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def get_snapshot_history(days: int = 7) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM plan_usage_snapshots WHERE recorded_at > ? ORDER BY recorded_at ASC",
        (cutoff,),
    ).fetchall()
    conn.close()
    return rows


def get_recent_sessions(limit: int = 20) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM session_summaries ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def get_sessions_by_source(days: int = 7) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT source,
               COUNT(*)        AS session_count,
               SUM(duration_sec) AS total_duration_sec,
               SUM(cost_usd)   AS total_cost_usd
        FROM session_summaries
        WHERE started_at > ?
        GROUP BY source
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return rows


def get_sessions_for_chart(days: int = 7) -> list[sqlite3.Row]:
    """Daily cost per source for the trend bar chart."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT DATE(started_at) AS day,
               source,
               SUM(cost_usd)   AS cost_usd
        FROM session_summaries
        WHERE started_at > ?
        GROUP BY day, source
        ORDER BY day ASC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return rows


# ── Retention pruning ────────────────────────────────────────────────────────

def prune_old_data(retention_days: int = 30) -> dict:
    """Delete rows older than retention_days. Returns counts of deleted rows."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    suggestion_cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    conn = get_connection()
    with conn:
        snap_del = conn.execute(
            "DELETE FROM plan_usage_snapshots WHERE recorded_at < ?", (cutoff,)
        ).rowcount
        sess_del = conn.execute(
            "DELETE FROM session_summaries WHERE started_at < ?", (cutoff,)
        ).rowcount
        sugg_del = conn.execute(
            "DELETE FROM suggestion_history WHERE shown_at < ?", (suggestion_cutoff,)
        ).rowcount
    conn.close()
    return {"snapshots": snap_del, "sessions": sess_del, "suggestions": sugg_del}


# ── Session stats ────────────────────────────────────────────────────────────

def get_session_stats(days: int = 7) -> dict:
    """
    Aggregate session stats for the stats cards:
      - cost_today        : sum of cost_usd for sessions starting today (UTC)
      - cost_this_week    : sum of cost_usd for sessions in the last `days` days
      - total_duration_sec: total session seconds in the last `days` days
      - session_count     : number of sessions in the last `days` days
      - most_active_project: project with highest total cost (None if no sessions)
    """
    today_cutoff = datetime.now(timezone.utc).date().isoformat()
    week_cutoff  = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    conn = get_connection()

    cost_today = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM session_summaries WHERE DATE(started_at) = ?",
        (today_cutoff,),
    ).fetchone()[0]

    week_row = conn.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0)      AS cost_week,
               COALESCE(SUM(duration_sec), 0)  AS dur_week,
               COUNT(*)                         AS count_week
        FROM session_summaries
        WHERE started_at > ?
        """,
        (week_cutoff,),
    ).fetchone()

    project_row = conn.execute(
        """
        SELECT project, SUM(cost_usd) AS total
        FROM session_summaries
        WHERE started_at > ? AND project IS NOT NULL AND project != ''
        GROUP BY project
        ORDER BY total DESC
        LIMIT 1
        """,
        (week_cutoff,),
    ).fetchone()

    conn.close()

    return {
        "cost_today":          float(cost_today),
        "cost_this_week":      float(week_row["cost_week"]),
        "total_duration_sec":  int(week_row["dur_week"]),
        "session_count":       int(week_row["count_week"]),
        "most_active_project": project_row["project"] if project_row else None,
    }


def get_week_total_cost(days: int = 7) -> float:
    """Total cost across all sessions in the last `days` days. Used for pct_of_week calc."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    total = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM session_summaries WHERE started_at > ?",
        (cutoff,),
    ).fetchone()[0]
    conn.close()
    return float(total)


# ── Health info ──────────────────────────────────────────────────────────────

def get_db_stats() -> dict:
    conn = get_connection()
    snap_count = conn.execute("SELECT COUNT(*) FROM plan_usage_snapshots").fetchone()[0]
    sess_count = conn.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]
    sugg_count = conn.execute("SELECT COUNT(*) FROM suggestion_history").fetchone()[0]
    db_size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    conn.close()
    return {
        "snapshot_count": snap_count,
        "session_count": sess_count,
        "suggestion_count": sugg_count,
        "db_size_bytes": db_size_bytes,
    }
