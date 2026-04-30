"""
main.py — FastAPI sidecar entry point for Claude Lens.

Starts on http://localhost:8765
Exposes data endpoints consumed by the Tauri frontend.

Startup sequence:
  1. Load config
  2. Init SQLite DB
  3. Scan existing sessions (background thread)
  4. Start file watchers
  5. Start dynamic usage poller
  6. Serve API
"""

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
import pricing
from keychain import is_authenticated, get_oauth_token
from poller import UsagePoller, load_state, DEFAULT_THRESHOLDS
from parser import scan_all_sessions, start_watchers, CLAUDE_CODE_DIR, COWORK_DIR
from activity_monitor import ActivityMonitor
from suggestions_loader import load_suggestions
from trigger_evaluator import evaluate_triggers, build_trigger_context
from suggestion_engine import get_eligible_suggestions

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path.home() / ".claudelens" / "config.json"

DEFAULT_CONFIG = {
    "hotkey": "Option+Space",
    "retentionDays": 30,
    "workingHours": {"start": "09:00", "end": "17:00"},
    "poll": {
        "thresholds": {
            "critical": {"above": 0.90, "intervalSec": 60},
            "high":     {"above": 0.80, "intervalSec": 120},
            "elevated": {"above": 0.60, "intervalSec": 300},
            "normal":   {"above": 0.20, "intervalSec": 600},
            "low":      {"above": 0.05, "intervalSec": 1800},
            "minimal":  {"above": 0.00, "intervalSec": 3600},
        }
    },
    "warnings": {"amberPct": 80, "redPct": 90},
    "suggestions": {
        "enabled": True,
        "maxVisible": 5,
        "triggers": {
            "low_utilization_eow": {
                "tiers": [
                    {"hoursUntilResetBelow": 72, "weeklyPctBelow": 0.70},
                    {"hoursUntilResetBelow": 48, "weeklyPctBelow": 0.50},
                ],
            },
            "post_reset": {
                "windowHours": 4,
                "dropThreshold": 0.30,
            },
        },
    },
    "notifications": {
        "limitWarnings": True,
        "dailySummary": True,
        "dailySummaryTime": "17:00",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, preserving nested keys not present in override."""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text())
            merged = _deep_merge(DEFAULT_CONFIG, user)
            return merged
        except Exception as exc:
            log.warning("Could not load config.json (%s), using defaults", exc)
    return DEFAULT_CONFIG


def _build_poll_thresholds(config: dict) -> list[tuple[float, int]]:
    """Convert config thresholds dict to the list-of-tuples format poller expects."""
    raw = config.get("poll", {}).get("thresholds", {})
    try:
        pairs = [(v["above"], v["intervalSec"]) for v in raw.values()]
    except (KeyError, TypeError):
        log.warning("Invalid poll thresholds in config.json; using defaults")
        return list(DEFAULT_THRESHOLDS)
    return sorted(pairs, reverse=True) if pairs else list(DEFAULT_THRESHOLDS)


# ── App state ─────────────────────────────────────────────────────────────────

_config: dict = {}
_poller: Optional[UsagePoller] = None
_poller_task: Optional[asyncio.Task] = None
_watcher = None

# Prior-snapshot tracking for post_reset trigger detection.
# _prev_latest holds (weekly_pct, recorded_at) from the most recent poll so
# that the NEXT poll can detect a significant drop.
_prior_weekly_pct: Optional[float] = None
_prior_recorded_at: Optional[str] = None
_prev_latest: Optional[tuple[float, str]] = None  # staging buffer

# Suggestions — loaded once at startup, available for all /suggestions requests.
_all_suggestions: list[dict] = []
_suggestions_yaml_error: Optional[str] = None  # surfaced in GET /suggestions


def _on_poller_update(snapshot) -> None:
    """Callback fired by UsagePoller after each successful poll.

    Advances the staging buffer so /suggestions can compare the current reading
    against the previous one for post_reset detection.
    """
    global _prior_weekly_pct, _prior_recorded_at, _prev_latest
    # Both reads (_prior_*) and writes (_prev_latest) happen on the asyncio event
    # loop — the poller's callback runs inside its async task, and get_suggestions()
    # runs on the same loop — so no lock is needed. If the poller moves to a thread,
    # protect these globals with asyncio.Lock.
    # Move the previously staged reading into "prior" (visible to trigger eval).
    if _prev_latest is not None:
        _prior_weekly_pct, _prior_recorded_at = _prev_latest
    # Stage the just-received reading for the next iteration.
    _prev_latest = (snapshot.weekly_pct, snapshot.recorded_at)


# ── Lifespan ──────────────────────────────────────────────────────────────────

class _SuppressOptions(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return '"OPTIONS ' not in record.getMessage()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _poller, _poller_task, _watcher, _all_suggestions, _suggestions_yaml_error

    # Suppress all OPTIONS preflight requests from the access log (intentionally
    # broad — every endpoint). Installed here so uvicorn's dictConfig during
    # startup doesn't clear the filter before it takes effect.
    logging.getLogger("uvicorn.access").addFilter(_SuppressOptions())

    # 1. Config
    _config = load_config()
    log.info("Config loaded (retentionDays=%d)", _config["retentionDays"])

    # 2. Pricing overrides
    pricing.set_pricing_override(_config.get("pricing", {}))

    # 3. DB
    db.init_db()
    log.info("Database ready at %s", db.DB_PATH)

    # 4. Retention prune
    pruned = db.prune_old_data(_config["retentionDays"])
    log.info("Pruned old data: %s", pruned)

    # 5. Startup session scan (background — don't block server start)
    def _scan():
        scan_all_sessions(_config["retentionDays"])
        anomaly = db.check_zero_cost_anomaly()
        if anomaly:
            log.error("Zero-cost anomaly: %s", anomaly)
    threading.Thread(target=_scan, daemon=True).start()

    # 6. File watchers
    _watcher = start_watchers()

    # 7. Load suggestions (non-fatal — logs warnings on bad entries)
    result = load_suggestions()
    if result is None:
        # YAML parse error — keep _all_suggestions as-is (empty at first launch,
        # or the previously loaded set on a future hot-reload).
        _suggestions_yaml_error = (
            "suggestions.yaml could not be parsed. Check the file for syntax errors."
        )
        log.error("Suggestions unavailable: %s", _suggestions_yaml_error)
    else:
        _all_suggestions = result
        _suggestions_yaml_error = None
        log.info("Suggestions engine: %d suggestions loaded", len(_all_suggestions))

    # 8. Usage poller — create_task requires a running event loop;
    #    this is safe here because lifespan runs inside FastAPI's async context.
    thresholds = _build_poll_thresholds(_config)
    _poller = UsagePoller(
        thresholds=thresholds,
        working_hours=_config.get("workingHours"),
        on_update=_on_poller_update,
    )
    _poller_task = asyncio.create_task(_poller.run())

    # 9. Activity monitor — same observer as the session file watcher, so no
    #    extra threads. Signals the poller to extend its active window when
    #    Claude session activity is detected outside working hours.
    _activity_monitor = ActivityMonitor(_poller)
    for _dir in [CLAUDE_CODE_DIR, COWORK_DIR]:
        if _dir.exists():
            _watcher.schedule(_activity_monitor, str(_dir), recursive=True)

    log.info("Claude Lens sidecar started on http://localhost:8765")
    yield

    # Shutdown
    if _poller:
        _poller.stop()
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
    if _watcher:
        _watcher.stop()
        _watcher.join()
    log.info("Claude Lens sidecar stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Claude Lens Sidecar", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ── Helper: snapshot → dict ───────────────────────────────────────────────────

def _snapshot_to_dict(snap, is_stale: bool = False) -> dict:
    """Convert a DB row or UsageSnapshot to a serialisable dict."""
    if hasattr(snap, "session_pct"):
        # UsageSnapshot dataclass
        return {
            "sessionPct":      snap.session_pct,
            "sessionResetsAt": snap.session_resets_at,
            "weeklyPct":       snap.weekly_pct,
            "weeklyResetsAt":  snap.weekly_resets_at,
            "recordedAt":      snap.recorded_at,
            "isStale":         snap.is_stale,
        }
    else:
        # sqlite3.Row
        return {
            "sessionPct":      snap["session_pct"],
            "sessionResetsAt": snap["session_resets"],
            "weeklyPct":       snap["weekly_pct"],
            "weeklyResetsAt":  snap["weekly_resets"],
            "recordedAt":      snap["recorded_at"],
            "isStale":         is_stale,
        }


def _staleness_seconds(recorded_at: str) -> int:
    try:
        t = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - t).total_seconds())
    except Exception:
        return -1


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Sidecar status, last poll time, DB stats, authentication state."""
    snap = _poller.current if _poller else None
    stats = db.get_db_stats()
    sleeping = _poller.is_sleeping if _poller else False
    active_until = _poller.active_until if _poller else None
    return {
        "status":           "ok",
        "authenticated":    is_authenticated(),
        "authError":        _poller.auth_error if _poller else False,
        "lastPollAt":       snap.recorded_at if snap else None,
        "pollIntervalSec":  _poller.interval_sec if _poller else None,
        "isStale":          snap.is_stale if snap else True,
        "stalenessSeconds": _staleness_seconds(snap.recorded_at) if snap else None,
        "isSleeping":       sleeping,
        "activeUntil":      active_until.isoformat() if active_until else None,
        "db": stats,
    }


@app.get("/usage/current")
async def usage_current():
    """
    Latest plan usage snapshot (live from poller, falls back to DB, then state.json).
    Always returns something — UI should check isStale.
    """
    # Prefer in-memory (most recent)
    if _poller and _poller.current:
        return _snapshot_to_dict(_poller.current)

    # Try DB
    row = db.get_latest_snapshot()
    if row:
        stale_sec = _staleness_seconds(row["recorded_at"])
        return _snapshot_to_dict(row, is_stale=stale_sec > 600)

    # Try state.json
    state, _ = load_state()
    if state:
        return _snapshot_to_dict(state)

    raise HTTPException(
        status_code=503,
        detail="No usage data available yet. Make sure Claude Code is installed and you are logged in.",
    )


@app.post("/usage/refresh")
async def usage_refresh():
    """Force an immediate poll outside the normal schedule."""
    if not _poller:
        raise HTTPException(status_code=503, detail="Poller not running")
    snap = await _poller.force_refresh()
    if not snap:
        if _poller.auth_error:
            raise HTTPException(status_code=401, detail="OAuth token rejected — re-authenticate Claude Code")
        raise HTTPException(status_code=502, detail="Failed to fetch usage from Anthropic API")
    return _snapshot_to_dict(snap)


@app.get("/usage/history")
def usage_history(days: int = Query(default=7, ge=1, le=90)):
    """
    Plan usage snapshots over the last N days, for the trend chart.
    Returns chronological list of {recordedAt, sessionPct, weeklyPct}.
    """
    rows = db.get_snapshot_history(days)
    return [
        {
            "recordedAt":  r["recorded_at"],
            "sessionPct":  r["session_pct"],
            "weeklyPct":   r["weekly_pct"],
        }
        for r in rows
    ]


@app.get("/sessions")
def sessions(limit: int = Query(default=20, ge=1, le=200)):
    """
    Recent session summaries, newest first.
    Each row includes pctOfWeek: fraction of this week's total tracked cost.
    """
    rows         = db.get_recent_sessions(limit)
    week_cost    = db.get_week_total_cost(days=7)

    def _pct(cost: float) -> float:
        # get_recent_sessions already filters to 7 days, so no row falls outside
        # the window — only need to guard against a zero weekly total.
        if week_cost <= 0:
            return 0.0
        return round(cost / week_cost, 4)

    return [
        {
            "sessionId":        r["session_id"],
            "source":           r["source"],
            "startedAt":        r["started_at"],
            "endedAt":          r["ended_at"],
            "durationSec":      r["duration_sec"],
            "model":            r["model"],
            "project":          r["project"],
            "costUsd":          r["cost_usd"],
            "title":            r["title"],
            "inputTokens":      r["input_tokens"],
            "outputTokens":     r["output_tokens"],
            "cacheReadTokens":  r["cache_read_tokens"],
            "cacheWriteTokens": r["cache_write_tokens"],
            "pctOfWeek":        _pct(r["cost_usd"]),
        }
        for r in rows
    ]


@app.get("/sessions/stats")
def sessions_stats(days: int = Query(default=7, ge=1, le=90)):
    """
    Aggregate stats for the stats cards:
    costToday, costThisWeek, totalDurationSec, sessionCount, mostActiveProject.
    """
    stats = db.get_session_stats(days)
    return {
        "costToday":         stats["cost_today"],
        "costThisWeek":      stats["cost_this_week"],
        "totalDurationSec":  stats["total_duration_sec"],
        "sessionCount":      stats["session_count"],
        "mostActiveProject": stats["most_active_project"],
    }


@app.get("/sessions/by-source")
def sessions_by_source(days: int = Query(default=7, ge=1, le=90)):
    """Aggregate session stats grouped by source (code / cowork)."""
    rows = db.get_sessions_by_source(days)
    return [
        {
            "source":           r["source"],
            "sessionCount":     r["session_count"],
            "totalDurationSec": r["total_duration_sec"],
            "totalCostUsd":     r["total_cost_usd"],
        }
        for r in rows
    ]


@app.get("/sessions/chart")
def sessions_chart(days: int = Query(default=7, ge=1, le=90)):
    """Daily cost per source for the stacked bar chart."""
    rows = db.get_sessions_for_chart(days)
    return [
        {
            "day":     r["day"],
            "source":  r["source"],
            "costUsd": r["cost_usd"],
        }
        for r in rows
    ]


@app.get("/config")
def get_config():
    """Return the active configuration (merged defaults + user overrides)."""
    # Don't expose pricing keys in case they contain sensitive overrides
    safe = {k: v for k, v in _config.items() if k != "pricing"}
    return safe


@app.get("/auth/status")
def auth_status():
    """Check whether the Claude OAuth token is present in Keychain."""
    authenticated = is_authenticated()
    return {
        "authenticated": authenticated,
        "message": (
            "Claude OAuth token found in Keychain."
            if authenticated
            else "No Claude OAuth token found. Please ensure Claude Code is installed and you are logged in."
        ),
    }


# ── Suggestions ───────────────────────────────────────────────────────────────

@app.get("/suggestions")
def get_suggestions():
    """
    Return the current eligible suggestion set with resolved prompts and trigger context.

    Response shape:
    {
      "suggestions": [
        {
          "id": "testing001",
          "category": "testing",
          "title": "...",
          "description": "...",
          "prompt": "...",          # {{project}} already resolved
          "trigger": "low_utilization_eow",
          "actions": ["copy_prompt", "open_cowork"]
        }
      ],
      "trigger_context": {
        "always": true,
        "low_utilization_eow": true,
        "post_reset": false,
        "weekly_pct": 0.28,
        "hours_until_reset": 31.0
      }
    }
    """
    if not _config.get("suggestions", {}).get("enabled", True):
        return {"suggestions": [], "trigger_context": {}}

    # Get current usage values (fall back gracefully if poller not ready).
    if _poller and _poller.current:
        weekly_pct = _poller.current.weekly_pct
        weekly_resets = _poller.current.weekly_resets_at
    else:
        row = db.get_latest_snapshot()
        weekly_pct = row["weekly_pct"] if row else 0.0
        weekly_resets = row["weekly_resets"] if row else None

    active_triggers = evaluate_triggers(
        weekly_pct=weekly_pct,
        weekly_resets=weekly_resets,
        prior_weekly_pct=_prior_weekly_pct,
        prior_recorded_at=_prior_recorded_at,
        config=_config,
    )
    trigger_context = build_trigger_context(weekly_pct, weekly_resets, active_triggers)

    with db._get_conn() as conn:
        eligible = get_eligible_suggestions(
            all_suggestions=_all_suggestions,
            active_triggers=active_triggers,
            conn=conn,
            config=_config,
        )

    return {
        "suggestions": [
            {
                "id":          s["id"],
                "category":    s.get("category", ""),
                "title":       s.get("title", ""),
                "description": s.get("description", ""),
                "prompt":      s.get("prompt", ""),
                "trigger":     s.get("trigger", ""),
                "actions":     s.get("actions", []),
            }
            for s in eligible
        ],
        "trigger_context": trigger_context,
        "yaml_error": _suggestions_yaml_error,
    }


def _require_known_suggestion(suggestion_id: str) -> None:
    known = {s["id"] for s in _all_suggestions}
    if suggestion_id not in known:
        raise HTTPException(status_code=404, detail=f"Unknown suggestion_id: {suggestion_id!r}")


class SuggestionShownBody(BaseModel):
    trigger: str = "rule_engine"


@app.post("/suggestions/{suggestion_id}/shown")
def suggestion_shown(suggestion_id: str, body: SuggestionShownBody = SuggestionShownBody()):
    """Record that a suggestion card was shown to the user.

    The shown_at timestamp written here is used by the cooldown filter to
    prevent the same suggestion from appearing too frequently.
    """
    _require_known_suggestion(suggestion_id)
    db.record_suggestion_shown(suggestion_id, trigger_rule=body.trigger)
    return {"status": "ok", "suggestion_id": suggestion_id}


@app.post("/suggestions/{suggestion_id}/acted_on")
def suggestion_acted_on(suggestion_id: str):
    """Record that the user acted on a suggestion (copied prompt, opened app, etc.)."""
    _require_known_suggestion(suggestion_id)
    db.record_suggestion_acted_on(suggestion_id)
    return {"status": "ok", "suggestion_id": suggestion_id}


@app.post("/suggestions/{suggestion_id}/dismissed")
def suggestion_dismissed(suggestion_id: str):
    """Record that the user dismissed a suggestion card."""
    _require_known_suggestion(suggestion_id)
    db.record_suggestion_dismissed(suggestion_id)
    return {"status": "ok", "suggestion_id": suggestion_id}


class SnoozeRequest(BaseModel):
    until: str  # ISO 8601 UTC, e.g. "2026-04-22T09:00:00Z"


@app.post("/suggestions/{suggestion_id}/snoozed")
def suggestion_snoozed(suggestion_id: str, body: SnoozeRequest):
    """Snooze a suggestion until a given UTC datetime.

    Body: { "until": "<ISO 8601 UTC>" }
    """
    _require_known_suggestion(suggestion_id)
    try:
        datetime.fromisoformat(body.until.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"'until' must be a valid ISO 8601 UTC timestamp; got {body.until!r}",
        )
    db.record_suggestion_snoozed(suggestion_id, body.until)
    return {"status": "ok", "suggestion_id": suggestion_id, "snoozed_until": body.until}

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)
