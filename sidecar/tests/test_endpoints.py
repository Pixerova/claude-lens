"""
test_endpoints.py — FastAPI endpoint integration tests.

Uses httpx.AsyncClient + ASGITransport to exercise the full routing layer
without spawning a subprocess.

ASGITransport does not fire ASGI lifespan events, so we configure the
module-level application state directly in _api_client instead of relying on
startup. This is simpler and faster: we set main._poller, main._config,
main._all_suggestions, and the prior-snapshot globals, then restore them on
exit.

DB isolation: the isolated_db fixture (from conftest.py) redirects SQLite to a
per-test tmp directory and calls db.init_db() before the test body runs.

DB seeding uses make_snapshot() / make_session() helpers from conftest.py.
"""

import contextlib
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import make_snapshot, make_session
import db

# All tests in this module are async — apply the marker at module level.
pytestmark = pytest.mark.asyncio


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _make_mock_poller(
    *,
    weekly_pct: float = 0.30,
    session_pct: float = 0.10,
    auth_error: bool = False,
    is_sleeping: bool = False,
    recorded_at: str | None = None,
) -> MagicMock:
    """Build a minimal UsagePoller mock with sensible defaults."""
    snap = MagicMock()
    snap.weekly_pct = weekly_pct
    snap.session_pct = session_pct
    snap.weekly_resets_at = "2099-01-01T00:00:00+00:00"
    snap.recorded_at = recorded_at or datetime.now(timezone.utc).isoformat()
    snap.is_stale = False

    p = MagicMock()
    p.current = snap
    p.interval_sec = 300
    p.auth_error = auth_error
    p.is_sleeping = is_sleeping
    p.active_until = None
    p.force_refresh = AsyncMock(return_value=snap)
    p.run = AsyncMock()
    p.stop = MagicMock()
    return p


# A minimal test suggestion with short cooldown so cooldown tests work.
_TEST_SUGGESTION = {
    "id": "test001",
    "category": "testing",
    "title": "Write missing tests",
    "description": "Claude will audit your test coverage.",
    "prompt": "Write tests for {{project}}.",
    "trigger": "always",
    "show_every_n_days": 1,
    "actions": ["copy_prompt"],
}


@contextlib.asynccontextmanager
async def _api_client(
    *,
    mock_poller: MagicMock | None = None,
    suggestions: list | None = None,
    auth_authenticated: bool = True,
):
    """Async context manager: yield (main_module, AsyncClient, mock_poller).

    ASGITransport does not trigger ASGI lifespan events, so we set the
    module-level globals directly and restore them on exit. This avoids
    starting file watchers, session scanners, or the real poller.
    """
    import main as m

    mp = mock_poller or _make_mock_poller()

    # Snapshot module state so we can restore it after the test.
    saved = {
        "_poller":           m._poller,
        "_config":           m._config,
        "_all_suggestions":  m._all_suggestions,
        "_suggestions_yaml_error": m._suggestions_yaml_error,
        "_prior_weekly_pct": m._prior_weekly_pct,
        "_prior_recorded_at": m._prior_recorded_at,
    }

    m._poller = mp
    m._config = m.DEFAULT_CONFIG.copy()
    m._all_suggestions = suggestions if suggestions is not None else []
    m._suggestions_yaml_error = None
    m._prior_weekly_pct = None
    m._prior_recorded_at = None

    transport = httpx.ASGITransport(app=m.app)
    try:
        with patch("main.is_authenticated", return_value=auth_authenticated):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield m, client, mp
    finally:
        for k, v in saved.items():
            setattr(m, k, v)


# ── Helper: seed sessions ─────────────────────────────────────────────────────

def _seed_sessions(rows: list[dict]) -> None:
    for kw in rows:
        db.upsert_session_summary(**kw)


# ══════════════════════════════════════════════════════════════════════════════
# GET /health
# ══════════════════════════════════════════════════════════════════════════════

async def test_health_returns_200(isolated_db):
    async with _api_client() as (_, client, __):
        resp = await client.get("/health")
    assert resp.status_code == 200


async def test_health_contains_required_fields(isolated_db):
    """Response must include authError (bool), lastPollAt, and a db sub-object
    with snapshot_count and session_count."""
    async with _api_client() as (_, client, __):
        resp = await client.get("/health")
    data = resp.json()

    assert isinstance(data.get("authError"), bool)
    # lastPollAt is a string (ISO) or null
    assert "lastPollAt" in data
    assert "db" in data
    assert "snapshot_count" in data["db"]
    assert "session_count" in data["db"]


# ══════════════════════════════════════════════════════════════════════════════
# GET /auth/status
# ══════════════════════════════════════════════════════════════════════════════

async def test_auth_status_true_when_token_present(isolated_db):
    async with _api_client(auth_authenticated=True) as (_, client, __):
        resp = await client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


async def test_auth_status_false_when_no_token(isolated_db):
    async with _api_client(auth_authenticated=False) as (_, client, __):
        resp = await client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


# ══════════════════════════════════════════════════════════════════════════════
# GET /usage/current
# ══════════════════════════════════════════════════════════════════════════════

async def test_usage_current_returns_snapshot_dict(isolated_db):
    """Returns a valid snapshot dict when the poller has a current value."""
    async with _api_client() as (_, client, __):
        resp = await client.get("/usage/current")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessionPct" in data
    assert "weeklyPct" in data
    assert "isStale" in data
    assert "recordedAt" in data


async def test_usage_current_is_stale_when_old_db_row(isolated_db):
    """isStale is True when the DB snapshot's recorded_at is >10 min ago
    and the poller has no current value (falls back to DB path)."""
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    with db._get_conn() as conn:
        with conn:
            conn.execute(
                "INSERT INTO plan_usage_snapshots "
                "(recorded_at, session_pct, session_resets, weekly_pct, weekly_resets) "
                "VALUES (?, 0.2, '2099-01-01T00:00:00+00:00', 0.3, '2099-01-01T00:00:00+00:00')",
                (old_ts,),
            )

    mp = _make_mock_poller()
    mp.current = None  # force DB fallback
    async with _api_client(mock_poller=mp) as (_, client, __):
        resp = await client.get("/usage/current")
    assert resp.status_code == 200
    assert resp.json()["isStale"] is True


async def test_usage_current_not_stale_when_recent_db_row(isolated_db):
    """isStale is False when the DB snapshot is fresh."""
    fresh_ts = datetime.now(timezone.utc).isoformat()
    with db._get_conn() as conn:
        with conn:
            conn.execute(
                "INSERT INTO plan_usage_snapshots "
                "(recorded_at, session_pct, session_resets, weekly_pct, weekly_resets) "
                "VALUES (?, 0.2, '2099-01-01T00:00:00+00:00', 0.3, '2099-01-01T00:00:00+00:00')",
                (fresh_ts,),
            )

    mp = _make_mock_poller()
    mp.current = None
    async with _api_client(mock_poller=mp) as (_, client, __):
        resp = await client.get("/usage/current")
    assert resp.status_code == 200
    assert resp.json()["isStale"] is False


async def test_usage_current_503_with_no_data(isolated_db):
    """Returns 503 when the DB is empty and the poller has no current value."""
    mp = _make_mock_poller()
    mp.current = None
    # Patch load_state so the state.json fallback also returns nothing.
    with patch("main.load_state", return_value=(None, 0)):
        async with _api_client(mock_poller=mp) as (_, client, __):
            resp = await client.get("/usage/current")
    assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# POST /usage/refresh
# ══════════════════════════════════════════════════════════════════════════════

async def test_usage_refresh_triggers_poll_and_returns_snapshot(isolated_db):
    """force_refresh is called once; its result's recordedAt is in the response."""
    async with _api_client() as (_, client, mp):
        resp = await client.post("/usage/refresh")
    assert resp.status_code == 200
    mp.force_refresh.assert_called_once()
    data = resp.json()
    assert "recordedAt" in data
    assert isinstance(data["recordedAt"], str)


# ══════════════════════════════════════════════════════════════════════════════
# GET /usage/history
# ══════════════════════════════════════════════════════════════════════════════

async def test_usage_history_returned_chronologically(isolated_db):
    """Snapshots within the window are returned oldest-first."""
    now = datetime.now(timezone.utc)
    times = [
        (now - timedelta(days=5)).isoformat(),
        (now - timedelta(days=3)).isoformat(),
        (now - timedelta(days=1)).isoformat(),
    ]
    with db._get_conn() as conn:
        with conn:
            for t in times:
                conn.execute(
                    "INSERT INTO plan_usage_snapshots "
                    "(recorded_at, session_pct, session_resets, weekly_pct, weekly_resets) "
                    "VALUES (?, 0.2, '2099-01-01T00:00:00+00:00', 0.3, '2099-01-01T00:00:00+00:00')",
                    (t,),
                )

    async with _api_client() as (_, client, __):
        resp = await client.get("/usage/history?days=7")
    recorded = [r["recordedAt"] for r in resp.json()]
    assert recorded == sorted(recorded)
    assert len(recorded) == 3


async def test_usage_history_excludes_snapshots_older_than_days(isolated_db):
    """Snapshots older than the requested window are not returned."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=3)).isoformat()
    old = (now - timedelta(days=10)).isoformat()
    with db._get_conn() as conn:
        with conn:
            for t in [recent, old]:
                conn.execute(
                    "INSERT INTO plan_usage_snapshots "
                    "(recorded_at, session_pct, session_resets, weekly_pct, weekly_resets) "
                    "VALUES (?, 0.2, '2099-01-01T00:00:00+00:00', 0.3, '2099-01-01T00:00:00+00:00')",
                    (t,),
                )

    async with _api_client() as (_, client, __):
        resp = await client.get("/usage/history?days=7")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["recordedAt"] == recent


# ══════════════════════════════════════════════════════════════════════════════
# GET /sessions
# ══════════════════════════════════════════════════════════════════════════════

async def test_sessions_returned_in_descending_order(isolated_db):
    """Sessions are returned newest-first."""
    _seed_sessions([
        make_session(session_id="old-sess", started_offset_hours=48, cost_usd=0.05),
        make_session(session_id="new-sess", started_offset_hours=1,  cost_usd=0.10),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions?limit=60")
    ids = [s["sessionId"] for s in resp.json()]
    assert ids.index("new-sess") < ids.index("old-sess")


async def test_sessions_pct_of_week_sums_to_at_most_100_pct(isolated_db):
    """pctOfWeek across all returned sessions sums to ≤ 1.0 (allowing float rounding)."""
    _seed_sessions([
        make_session(session_id="s1", started_offset_hours=1, cost_usd=0.10),
        make_session(session_id="s2", started_offset_hours=2, cost_usd=0.20),
        make_session(session_id="s3", started_offset_hours=3, cost_usd=0.05),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions?limit=60")
    total = sum(s["pctOfWeek"] for s in resp.json())
    assert total <= 1.0 + 1e-6


async def test_sessions_outside_7_day_window_have_pct_of_week_zero(isolated_db):
    """Sessions whose started_at is outside the 7-day window are excluded entirely
    (the DB query filters them, so they do not appear in the response)."""
    _seed_sessions([
        make_session(session_id="ancient", started_offset_hours=8 * 24, cost_usd=0.10),
        make_session(session_id="recent",  started_offset_hours=1,       cost_usd=0.05),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions?limit=60")
    ids = [s["sessionId"] for s in resp.json()]
    assert "recent" in ids
    assert "ancient" not in ids


async def test_sessions_respects_limit_parameter(isolated_db):
    """The limit parameter caps the number of sessions returned."""
    _seed_sessions([
        make_session(session_id=f"s{i}", started_offset_hours=i, cost_usd=0.01)
        for i in range(1, 6)  # 5 sessions
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions?limit=3")
    assert len(resp.json()) == 3


# ══════════════════════════════════════════════════════════════════════════════
# GET /sessions/stats
# ══════════════════════════════════════════════════════════════════════════════


async def test_sessions_stats_correct_values(isolated_db):
    """Aggregate stats reflect seeded data accurately."""
    _seed_sessions([
        make_session(session_id="big", started_offset_hours=1, cost_usd=0.50, project="big-project"),
        make_session(session_id="sm",  started_offset_hours=2, cost_usd=0.01, project="small-project"),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions/stats?days=7")
    data = resp.json()
    assert data["sessionCount"] == 2
    assert data["mostActiveProject"] == "big-project"
    assert abs(data["costThisWeek"] - 0.51) < 0.001


# ══════════════════════════════════════════════════════════════════════════════
# GET /sessions/by-source
# ══════════════════════════════════════════════════════════════════════════════

async def test_sessions_by_source_both_sources_present(isolated_db):
    """When both code and cowork sessions exist, both appear in the response."""
    _seed_sessions([
        make_session(session_id="c1", source="code",   started_offset_hours=1, cost_usd=0.10),
        make_session(session_id="w1", source="cowork", started_offset_hours=2, cost_usd=0.05),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions/by-source?days=7")
    assert resp.status_code == 200
    sources = {r["source"] for r in resp.json()}
    assert "code" in sources
    assert "cowork" in sources


async def test_sessions_by_source_cost_totals_are_correct(isolated_db):
    """Total costs across all source rows sum to the seeded total."""
    _seed_sessions([
        make_session(session_id="c1", source="code",   started_offset_hours=1, cost_usd=0.10),
        make_session(session_id="w1", source="cowork", started_offset_hours=2, cost_usd=0.05),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions/by-source?days=7")
    total = sum(r["totalCostUsd"] for r in resp.json())
    assert abs(total - 0.15) < 0.001


async def test_sessions_by_source_single_source_only_returns_that_source(isolated_db):
    """When only one source has sessions, only that source row is returned."""
    _seed_sessions([
        make_session(session_id="c1", source="code", started_offset_hours=1, cost_usd=0.10),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions/by-source?days=7")
    data = resp.json()
    sources = [r["source"] for r in data]
    assert "code" in sources
    assert len(data) == 1


# ══════════════════════════════════════════════════════════════════════════════
# GET /sessions/chart
# ══════════════════════════════════════════════════════════════════════════════

async def test_sessions_chart_returns_data_for_seeded_days(isolated_db):
    """Chart endpoint returns one row per day-source combination in the window."""
    # Seed code sessions on the last 7 different days
    for i in range(7):
        db.upsert_session_summary(**make_session(
            session_id=f"chart-{i}",
            started_offset_hours=i * 24 + 1,
            cost_usd=0.05,
            source="code",
        ))

    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions/chart?days=7")
    data = resp.json()
    days = {r["day"] for r in data}
    # With one session per day for 7 days, expect at least 6 distinct day values
    # (boundary conditions near midnight can shift a session into the 8th day back)
    assert len(days) >= 6


async def test_sessions_chart_rows_have_correct_schema(isolated_db):
    """Each chart row must have day, source, and costUsd fields."""
    _seed_sessions([
        make_session(session_id="ch-c", source="code",   cost_usd=0.08, started_offset_hours=1),
        make_session(session_id="ch-w", source="cowork", cost_usd=0.04, started_offset_hours=2),
    ])
    async with _api_client() as (_, client, __):
        resp = await client.get("/sessions/chart?days=7")
    data = resp.json()
    assert len(data) >= 1
    for row in data:
        assert "day" in row
        assert "source" in row
        assert "costUsd" in row
    sources = {r["source"] for r in data}
    assert "code" in sources
    assert "cowork" in sources


# ══════════════════════════════════════════════════════════════════════════════
# POST /suggestions/{id}/shown
# ══════════════════════════════════════════════════════════════════════════════

async def test_suggestion_shown_suppresses_within_cooldown(isolated_db):
    """After POST /shown, GET /suggestions no longer returns that suggestion
    within its cooldown window (show_every_n_days=1)."""
    sugg = dict(_TEST_SUGGESTION, show_every_n_days=1)
    async with _api_client(suggestions=[sugg]) as (m, client, _mp):
        # Nullify prior-snapshot globals so only 'always' trigger is active.
        m._prior_weekly_pct = None
        m._prior_recorded_at = None

        # Before shown: suggestion should be eligible.
        resp_before = await client.get("/suggestions")
        assert resp_before.status_code == 200
        ids_before = [s["id"] for s in resp_before.json()["suggestions"]]
        assert "test001" in ids_before, "Test suggestion must be eligible before /shown"

        # Mark as shown.
        shown_resp = await client.post("/suggestions/test001/shown")
        assert shown_resp.status_code == 200

        # After shown: must be suppressed by cooldown.
        resp_after = await client.get("/suggestions")
        ids_after = [s["id"] for s in resp_after.json()["suggestions"]]
        assert "test001" not in ids_after, "Suggestion must be in cooldown after /shown"


# ══════════════════════════════════════════════════════════════════════════════
# POST /suggestions/{id}/acted_on
# ══════════════════════════════════════════════════════════════════════════════

async def test_suggestion_acted_on_sets_flag_in_db(isolated_db):
    """POST /acted_on sets acted_on=1 on the most recent suggestion_history row."""
    sugg = dict(_TEST_SUGGESTION)
    async with _api_client(suggestions=[sugg]) as (_, client, __):
        # Insert a shown row so acted_on has a row to update.
        db.record_suggestion_shown("test001", trigger_rule="always")
        resp = await client.post("/suggestions/test001/acted_on")
    assert resp.status_code == 200

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT acted_on FROM suggestion_history "
            "WHERE suggestion_id='test001' ORDER BY shown_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["acted_on"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# POST /suggestions/{id}/dismissed
# ══════════════════════════════════════════════════════════════════════════════

async def test_suggestion_dismissed_sets_dismissed_at(isolated_db):
    """POST /dismissed records a non-null dismissed_at in suggestion_history."""
    sugg = dict(_TEST_SUGGESTION)
    async with _api_client(suggestions=[sugg]) as (_, client, __):
        db.record_suggestion_shown("test001", trigger_rule="always")
        resp = await client.post("/suggestions/test001/dismissed")
    assert resp.status_code == 200

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT dismissed_at FROM suggestion_history "
            "WHERE suggestion_id='test001' ORDER BY shown_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["dismissed_at"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# POST /suggestions/{id}/snoozed
# ══════════════════════════════════════════════════════════════════════════════

async def test_suggestion_snoozed_writes_timestamp(isolated_db):
    """POST /snoozed persists the provided until timestamp to suggestion_history."""
    until_iso = "2099-12-31T09:00:00Z"
    sugg = dict(_TEST_SUGGESTION)
    async with _api_client(suggestions=[sugg]) as (_, client, __):
        db.record_suggestion_shown("test001", trigger_rule="always")
        resp = await client.post(
            "/suggestions/test001/snoozed",
            json={"until": until_iso},
        )
    assert resp.status_code == 200

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT snoozed_until FROM suggestion_history "
            "WHERE suggestion_id='test001' ORDER BY shown_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["snoozed_until"] == until_iso


async def test_suggestion_snoozed_suppresses_in_get_suggestions(isolated_db):
    """A suggestion snoozed into the far future does not appear in GET /suggestions."""
    far_future = "2099-12-31T09:00:00Z"
    sugg = dict(_TEST_SUGGESTION)
    async with _api_client(suggestions=[sugg]) as (m, client, __):
        m._prior_weekly_pct = None
        m._prior_recorded_at = None

        # Snooze before any shown row exists — endpoint creates the row.
        snooze_resp = await client.post(
            "/suggestions/test001/snoozed",
            json={"until": far_future},
        )
        assert snooze_resp.status_code == 200

        resp = await client.get("/suggestions")
        ids = [s["id"] for s in resp.json()["suggestions"]]
        assert "test001" not in ids
