"""
suggestion_engine.py — Suggestions selection engine.

Selection algorithm: filter → sort → resolve → return top N.

Pipeline (SPEC §12.5):
  1. Filter to suggestions whose trigger is in active_triggers.
  2. Filter out suggestions within their show_every_n_days cooldown.
  3. Filter out snoozed suggestions.
  4. Sort: trigger-specific first (low_utilization_eow, post_reset), then always;
     within each group, LRU (NULL shown_at first, then oldest shown_at).
  5. Take top N (config.suggestions.maxVisible, default 5).
  6. Resolve {{project}} in each prompt.
  7. Return full dicts with resolved prompt.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

# Sort priority: lower = appears first in results.
_TRIGGER_PRIORITY = {
    "low_utilization_eow": 0,
    "post_reset":          0,
    "always":              1,
}


# ── Project resolution ────────────────────────────────────────────────────────

def get_active_project(conn: sqlite3.Connection) -> str:
    """Return the most recently ended Claude Code session's project name (last 7 days).

    Only considers source='code' sessions — Cowork sessions do not have a
    meaningful project directory associated with them.

    Returns empty string if no project is found — prompts degrade gracefully.
    """
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=7)).isoformat()
    try:
        row = conn.execute(
            """
            SELECT project
            FROM   session_summaries
            WHERE  ended_at >= ?
              AND  source = 'code'
              AND  project IS NOT NULL
              AND  project != ''
            ORDER  BY ended_at DESC
            LIMIT  1
            """,
            (cutoff,),
        ).fetchone()
        return row["project"] if row else ""
    except sqlite3.Error as exc:
        log.warning("Failed to query active project: %s", exc)
        return ""


def resolve_prompt(prompt: str, project: Optional[str]) -> str:
    """Replace {{project}} with the active project name (or '' if unknown)."""
    return prompt.replace("{{project}}", project or "")


# ── History queries ───────────────────────────────────────────────────────────

def _load_history(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return latest shown_at and snoozed_until per suggestion_id.

    Returns:
        {"testing001": {"shown_at": "...", "snoozed_until": "..."}, ...}
    """
    history: dict[str, dict] = {}
    try:
        rows = conn.execute(
            """
            SELECT   suggestion_id,
                     MAX(shown_at)       AS last_shown_at,
                     MAX(snoozed_until)  AS snoozed_until
            FROM     suggestion_history
            WHERE    suggestion_id IS NOT NULL
            GROUP BY suggestion_id
            """
        ).fetchall()
        for row in rows:
            history[row["suggestion_id"]] = {
                "shown_at":      row["last_shown_at"],
                "snoozed_until": row["snoozed_until"],
            }
    except sqlite3.Error as exc:
        log.warning("Failed to load suggestion history: %s", exc)
    return history


# ── Filters ───────────────────────────────────────────────────────────────────

def _in_cooldown(suggestion: dict, history: dict[str, dict]) -> bool:
    rec = history.get(suggestion["id"])
    if not rec or not rec.get("shown_at"):
        return False
    try:
        last_shown = datetime.fromisoformat(rec["shown_at"].replace("Z", "+00:00"))
        next_ok = last_shown + timedelta(days=int(suggestion["show_every_n_days"]))
        return datetime.now(tz=timezone.utc) < next_ok
    except (ValueError, TypeError):
        return False


def _is_snoozed(suggestion: dict, history: dict[str, dict]) -> bool:
    rec = history.get(suggestion["id"])
    if not rec or not rec.get("snoozed_until"):
        return False
    try:
        until = datetime.fromisoformat(rec["snoozed_until"].replace("Z", "+00:00"))
        return datetime.now(tz=timezone.utc) < until
    except (ValueError, TypeError):
        return False


# ── Sort key ──────────────────────────────────────────────────────────────────

def _sort_key(suggestion: dict, history: dict[str, dict]) -> tuple:
    """(trigger_priority, last_shown_epoch) — lower sorts first."""
    priority = _TRIGGER_PRIORITY.get(suggestion.get("trigger", "always"), 99)
    rec = history.get(suggestion["id"])
    shown_at = rec.get("shown_at") if rec else None
    if shown_at is None:
        epoch = 0.0  # never shown → highest priority within group
    else:
        try:
            epoch = datetime.fromisoformat(shown_at.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            epoch = 0.0
    return (priority, epoch)


# ── Main selection API ────────────────────────────────────────────────────────

def get_eligible_suggestions(
    all_suggestions: list[dict],
    active_triggers: set[str],
    conn: sqlite3.Connection,
    config: Any,
    _project_override: Optional[str] = None,  # for tests only
) -> list[dict]:
    """Select, filter, sort, and resolve suggestions ready for display.

    Args:
        all_suggestions:   Full list from suggestions_loader.load_suggestions().
        active_triggers:   Set from trigger_evaluator.evaluate_triggers().
        conn:              Open SQLite connection (row_factory=sqlite3.Row expected).
        config:            Loaded config dict.
        _project_override: Bypass DB project lookup (tests only).

    Returns:
        Up to maxVisible dicts, each with 'prompt' already resolved.
    """
    project = (
        _project_override
        if _project_override is not None
        else get_active_project(conn)
    )

    try:
        max_visible = int(config["suggestions"]["maxVisible"])
    except (KeyError, TypeError, ValueError):
        max_visible = 5

    history = _load_history(conn)

    # 1. Trigger filter
    by_trigger = [s for s in all_suggestions if s.get("trigger") in active_triggers]
    # 2. Cooldown filter
    after_cooldown = [s for s in by_trigger if not _in_cooldown(s, history)]
    # 3. Snooze filter
    after_snooze = [s for s in after_cooldown if not _is_snoozed(s, history)]
    # 4. Sort
    sorted_list = sorted(after_snooze, key=lambda s: _sort_key(s, history))
    # 5. Cap
    selected = sorted_list[:max_visible]

    # 6 & 7. Resolve and return
    resolved = []
    for s in selected:
        copy = dict(s)
        copy["prompt"] = resolve_prompt(copy.get("prompt", ""), project)
        resolved.append(copy)

    log.debug(
        "Suggestions: %d total → %d trigger → %d cooldown → %d snooze → %d selected",
        len(all_suggestions), len(by_trigger), len(after_cooldown),
        len(after_snooze), len(resolved),
    )
    return resolved
