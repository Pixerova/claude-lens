"""
db.py — SQLite database setup, schema, and core write helpers.

Database lives at ~/.claudelens/claudelens.db
Tables:
  - plan_usage_snapshots  : one row per OAuth API poll result
  - session_summaries     : one row per local Claude Code / Cowork session
  - suggestion_history    : log of suggestions shown to the user
"""

import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = Path.home() / ".claudelens"
DB_PATH  = DATA_DIR / "claudelens.db"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _schema_hash_path() -> Path:
    """Return the path to the persisted schema hash file.

    Defined as a function (not a module-level constant) so that tests can
    monkeypatch DATA_DIR and have this path follow automatically.
    """
    return DATA_DIR / "schema.hash"


def _schema_hash() -> str:
    """SHA-256 of the SCHEMA constant, truncated to 16 hex chars."""
    return hashlib.sha256(SCHEMA.encode()).hexdigest()[:16]


def get_connection() -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # allow concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _get_conn():
    """Context manager that guarantees conn.close() even on exception."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


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
    session_id         TEXT PRIMARY KEY,
    source             TEXT NOT NULL CHECK(source IN ('code', 'cowork')),
    started_at         TEXT NOT NULL,
    ended_at           TEXT NOT NULL,
    duration_sec       INTEGER NOT NULL,
    model              TEXT NOT NULL,
    project            TEXT,
    cost_usd           REAL NOT NULL,
    title              TEXT,
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    last_parsed        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestion_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    shown_at         TEXT NOT NULL,
    trigger_rule     TEXT NOT NULL,
    suggestion_text  TEXT NOT NULL,
    suggestion_id    TEXT,
    dismissed_at     TEXT,
    acted_on         INTEGER DEFAULT 0,
    snoozed_until    TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_time   ON plan_usage_snapshots(recorded_at);
CREATE INDEX IF NOT EXISTS idx_sessions_start   ON session_summaries(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_source  ON session_summaries(source);
"""


def _reset_if_schema_changed(conn: sqlite3.Connection) -> None:
    """Drop all tables and recreate if the schema has changed since last run.

    Compares a hash of the SCHEMA constant against the value persisted in
    ~/.claudelens/schema.hash.  On mismatch (or first run), all tables are
    dropped so init_db() can recreate them from the current SCHEMA.

    This replaces the ALTER TABLE migration approach during development.
    Before shipping to real users, swap this out for proper migrations.
    """
    current = _schema_hash()
    hash_path = _schema_hash_path()
    stored = hash_path.read_text().strip() if hash_path.exists() else None

    if stored == current:
        return  # schema unchanged — nothing to do

    if stored is not None:
        log.info(
            "Schema changed (stored=%s, current=%s) — dropping all tables",
            stored, current,
        )
    else:
        log.info("No schema hash found — initialising fresh database")

    # Drop all user tables (excludes SQLite internal tables).
    tables = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS [{table}]")
    conn.commit()

    # Persist the new hash so the next startup is a no-op.
    # Atomic write: write to a temp file then rename, so a crash between the
    # DROP TABLE commit and this write can never leave a partially-written hash.
    _ensure_data_dir()
    tmp = hash_path.with_suffix(".tmp")
    tmp.write_text(current + "\n")
    os.replace(tmp, hash_path)
    log.info("Schema hash updated to %s", current)


def init_db() -> None:
    """Initialise the database.

    On schema change: drops all tables and recreates from SCHEMA.
    On unchanged schema: a no-op (tables already exist).
    Safe to call on every startup.
    """
    with _get_conn() as conn:
        _reset_if_schema_changed(conn)
        conn.executescript(SCHEMA)


# ── Writers ──────────────────────────────────────────────────────────────────

def store_snapshot(
    session_pct: float,
    session_resets: str,
    weekly_pct: float,
    weekly_resets: str,
) -> None:
    """Persist a plan usage API response."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO plan_usage_snapshots
                    (recorded_at, session_pct, session_resets, weekly_pct, weekly_resets)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, session_pct, session_resets, weekly_pct, weekly_resets),
            )


def upsert_session_summary(
    session_id: str,
    source: str,
    started_at: str,
    ended_at: str,
    duration_sec: int,
    model: str,
    project: Optional[str],
    cost_usd: float,
    title: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """Insert or replace a session summary (re-parse overwrites previous record)."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO session_summaries
                    (session_id, source, started_at, ended_at, duration_sec,
                     model, project, cost_usd,
                     title, input_tokens, output_tokens,
                     cache_read_tokens, cache_write_tokens,
                     last_parsed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    ended_at           = excluded.ended_at,
                    duration_sec       = excluded.duration_sec,
                    model              = excluded.model,
                    project            = excluded.project,
                    cost_usd           = excluded.cost_usd,
                    title              = excluded.title,
                    input_tokens       = excluded.input_tokens,
                    output_tokens      = excluded.output_tokens,
                    cache_read_tokens  = excluded.cache_read_tokens,
                    cache_write_tokens = excluded.cache_write_tokens,
                    last_parsed        = excluded.last_parsed
                """,
                (session_id, source, started_at, ended_at, duration_sec,
                 model, project, cost_usd,
                 title, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens,
                 now),
            )



def dismiss_suggestion(suggestion_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        with conn:
            conn.execute(
                "UPDATE suggestion_history SET dismissed_at = ? WHERE id = ?",
                (now, suggestion_id),
            )


def mark_suggestion_acted(suggestion_id: int) -> None:
    with _get_conn() as conn:
        with conn:
            conn.execute(
                "UPDATE suggestion_history SET acted_on = 1 WHERE id = ?",
                (suggestion_id,),
            )


# ── Suggestion writers (keyed by suggestion_id text, not row id) ─────────────

def record_suggestion_shown(suggestion_id: str, trigger_rule: str = "rule_engine") -> None:
    """Insert a new shown_at row for the given suggestion_id.

    A new row is always inserted (not upserted) so every display event is logged.
    The cooldown filter uses MAX(shown_at) grouped by suggestion_id.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO suggestion_history
                    (shown_at, trigger_rule, suggestion_text, suggestion_id, acted_on)
                VALUES (?, ?, ?, ?, 0)
                """,
                (now, trigger_rule, suggestion_id, suggestion_id),
            )


def record_suggestion_acted_on(suggestion_id: str) -> None:
    """Mark the most recent shown row for this suggestion_id as acted_on."""
    with _get_conn() as conn:
        with conn:
            conn.execute(
                """
                UPDATE suggestion_history
                SET    acted_on = 1
                WHERE  id = (
                    SELECT id FROM suggestion_history
                    WHERE  suggestion_id = ?
                    ORDER  BY shown_at DESC LIMIT 1
                )
                """,
                (suggestion_id,),
            )


def record_suggestion_dismissed(suggestion_id: str) -> None:
    """Record dismissed_at on the most recent shown row for this suggestion_id."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        with conn:
            conn.execute(
                """
                UPDATE suggestion_history
                SET    dismissed_at = ?
                WHERE  id = (
                    SELECT id FROM suggestion_history
                    WHERE  suggestion_id = ?
                    ORDER  BY shown_at DESC LIMIT 1
                )
                """,
                (now, suggestion_id),
            )


def record_suggestion_snoozed(suggestion_id: str, snoozed_until: str) -> None:
    """Write snoozed_until on the most recent shown row for this suggestion_id.

    If no row exists yet, inserts a new one so the snooze is persisted.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        with conn:
            existing = conn.execute(
                "SELECT id FROM suggestion_history WHERE suggestion_id = ? "
                "ORDER BY shown_at DESC LIMIT 1",
                (suggestion_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE suggestion_history SET snoozed_until = ? WHERE id = ?",
                    (snoozed_until, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO suggestion_history
                        (shown_at, trigger_rule, suggestion_text, suggestion_id,
                         acted_on, snoozed_until)
                    VALUES (?, 'rule_engine', ?, ?, 0, ?)
                    """,
                    (now, suggestion_id, suggestion_id, snoozed_until),
                )


# ── Readers ──────────────────────────────────────────────────────────────────

def get_latest_snapshot() -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM plan_usage_snapshots ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()


def get_snapshot_history(days: int = 7) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM plan_usage_snapshots WHERE recorded_at > ? ORDER BY recorded_at ASC",
            (cutoff,),
        ).fetchall()


def get_recent_sessions(limit: int = 20, days: int = 7) -> list[sqlite3.Row]:
    """Return sessions that started within the last `days` days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM session_summaries WHERE started_at > ? ORDER BY started_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()


def get_sessions_by_source(days: int = 7) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        return conn.execute(
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


def get_sessions_for_chart(days: int = 7) -> list[sqlite3.Row]:
    """Daily cost per source for the trend bar chart."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        return conn.execute(
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


# ── Retention pruning ────────────────────────────────────────────────────────

def prune_old_data(retention_days: int = 30) -> dict:
    """Delete rows older than retention_days. Returns counts of deleted rows."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    suggestion_cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    with _get_conn() as conn:
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

    with _get_conn() as conn:
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
    with _get_conn() as conn:
        return float(conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM session_summaries WHERE started_at > ?",
            (cutoff,),
        ).fetchone()[0])


# ── Anomaly checks ───────────────────────────────────────────────────────────

def check_zero_cost_anomaly() -> Optional[str]:
    """
    Return an error string if sessions exist but every one has cost_usd = 0.
    This indicates model names are not matching the pricing table.
    Returns None when costs look healthy.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS total "
            "FROM session_summaries"
        ).fetchone()
    n, total = int(row["n"]), float(row["total"])
    # SQLite stores exact zero when pricing fails (no floating-point accumulation),
    # so exact equality is safe here — not a float comparison bug.
    if n > 0 and total < 1e-9:
        return (
            f"{n} session(s) in database but total cost_usd = 0.0 — "
            "model names may not be recognised by the pricing table"
        )
    return None


# ── Health info ───────────────────────────────────────────────────────────────

def get_db_stats() -> dict:
    with _get_conn() as conn:
        snap_count = conn.execute("SELECT COUNT(*) FROM plan_usage_snapshots").fetchone()[0]
        sess_count = conn.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]
        sugg_count = conn.execute("SELECT COUNT(*) FROM suggestion_history").fetchone()[0]
    db_size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "snapshot_count": snap_count,
        "session_count": sess_count,
        "suggestion_count": sugg_count,
        "db_size_bytes": db_size_bytes,
    }
