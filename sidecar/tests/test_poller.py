"""
test_poller.py — Tests for poller.py: interval logic, state file, snapshot model.

Network calls and Keychain access are always mocked — no real HTTP or
macOS Keychain required.
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import poller
from poller import (
    UsageSnapshot,
    RateLimitedError,
    AuthError,
    compute_interval,
    load_state,
    save_state,
    DEFAULT_THRESHOLDS,
)


# ── compute_interval ──────────────────────────────────────────────────────────

class TestComputeInterval:
    """The interval is driven by session_pct only."""

    @pytest.mark.parametrize("session,weekly,expected", [
        (0.95, 0.10, 30),    # session critical → 30s
        (0.10, 0.92, 1800),  # weekly high but session low → session wins
        (0.85, 0.10, 60),    # high             → 60s
        (0.65, 0.10, 120),   # elevated         → 120s
        (0.30, 0.25, 300),   # normal           → 300s
        (0.08, 0.07, 1800),  # low              → 1800s
        (0.03, 0.02, 3600),  # minimal          → 3600s
        (0.00, 0.00, 3600),  # zero usage       → 3600s
    ])
    def test_correct_interval_for_utilisation(self, session, weekly, expected):
        assert compute_interval(session, weekly) == expected

    def test_weekly_does_not_drive_interval(self):
        # High weekly, low session — interval should reflect session only
        assert compute_interval(0.05, 0.91) == 1800
        assert compute_interval(0.91, 0.05) == 30

    def test_custom_thresholds_are_respected(self):
        custom = [(0.50, 10), (0.00, 999)]
        assert compute_interval(0.60, 0.00, custom) == 10
        assert compute_interval(0.30, 0.00, custom) == 999

    def test_exactly_at_threshold_boundary(self):
        # 0.90 exactly should hit the "critical" tier
        assert compute_interval(0.90, 0.00) == 30
        # Just below 0.90 should hit "high"
        assert compute_interval(0.899, 0.00) == 60


# ── State file (load_state / save_state) ─────────────────────────────────────

class TestStateFile:
    def _make_snapshot(self, session_pct=0.21, weekly_pct=0.25) -> UsageSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        return UsageSnapshot(
            session_pct=session_pct,
            session_resets_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            weekly_pct=weekly_pct,
            weekly_resets_at=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            recorded_at=now,
            is_stale=False,
        )

    def test_load_state_returns_none_when_no_file(self, isolated_state):
        snapshot, interval = load_state()
        assert snapshot is None
        assert interval == 0

    def test_save_and_load_round_trips(self, isolated_state):
        snap = self._make_snapshot(session_pct=0.42, weekly_pct=0.77)
        save_state(snap, interval_sec=120)
        loaded, interval = load_state()

        assert loaded is not None
        assert abs(loaded.session_pct - 0.42) < 1e-6
        assert abs(loaded.weekly_pct  - 0.77) < 1e-6
        assert loaded.is_stale is True   # loaded from disk → always stale
        assert interval == 120

    def test_save_writes_interval(self, isolated_state):
        snap = self._make_snapshot()
        save_state(snap, interval_sec=300)
        data = json.loads(isolated_state.read_text())
        assert data["currentIntervalSec"] == 300

    def test_save_writes_last_poll_at(self, isolated_state):
        snap = self._make_snapshot()
        save_state(snap, interval_sec=60)
        data = json.loads(isolated_state.read_text())
        assert "lastPollAt" in data
        assert data["lastPollAt"] == snap.recorded_at

    def test_load_state_with_malformed_file_returns_none(self, isolated_state):
        isolated_state.write_text("not valid json {{{{")
        snapshot, interval = load_state()
        assert snapshot is None
        assert interval == 0

    def test_load_state_with_empty_file_returns_none(self, isolated_state):
        isolated_state.write_text("")
        snapshot, interval = load_state()
        assert snapshot is None
        assert interval == 0

    def test_save_creates_parent_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "deep" / "dir" / "state.json"
        monkeypatch.setattr(poller, "STATE_PATH", nested)
        snap = self._make_snapshot()
        save_state(snap, interval_sec=300)
        assert nested.exists()


# ── UsageSnapshot dataclass ───────────────────────────────────────────────────

class TestUsageSnapshot:
    def test_default_is_stale_false(self):
        snap = UsageSnapshot(
            session_pct=0.1,
            session_resets_at="2026-04-10T17:00:00Z",
            weekly_pct=0.2,
            weekly_resets_at="2026-04-15T08:00:00Z",
            recorded_at="2026-04-10T13:00:00Z",
        )
        assert snap.is_stale is False

    def test_can_mark_stale(self):
        snap = UsageSnapshot(
            session_pct=0.5, session_resets_at="", weekly_pct=0.5,
            weekly_resets_at="", recorded_at="", is_stale=True
        )
        assert snap.is_stale is True


# ── UsagePoller (unit-level, mocked I/O) ─────────────────────────────────────

class TestUsagePoller:
    def _make_snapshot(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        return UsageSnapshot(
            session_pct=0.30,
            session_resets_at=(datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
            weekly_pct=0.40,
            weekly_resets_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            recorded_at=now,
        )

    def test_initial_current_is_none_when_no_state(self, isolated_state, isolated_db):
        p = poller.UsagePoller()
        assert p.current is None

    def test_initial_current_loaded_from_state(self, isolated_state, isolated_db):
        snap = self._make_snapshot()
        save_state(snap, interval_sec=300)
        p = poller.UsagePoller()
        assert p.current is not None
        assert abs(p.current.session_pct - 0.30) < 1e-6

    @pytest.mark.asyncio
    async def test_force_refresh_returns_snapshot(self, isolated_state, isolated_db):
        snap = self._make_snapshot()
        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", new_callable=AsyncMock, return_value=snap), \
             patch("poller.store_snapshot"), \
             patch("poller.save_state"):
            p = poller.UsagePoller()
            result = await p.force_refresh()
        assert result is not None
        assert abs(result.session_pct - 0.30) < 1e-6

    @pytest.mark.asyncio
    async def test_force_refresh_returns_none_when_no_token(self, isolated_state, isolated_db):
        with patch("poller.get_oauth_token", return_value=None):
            p = poller.UsagePoller()
            result = await p.force_refresh()
        assert result is None

    @pytest.mark.asyncio
    async def test_force_refresh_returns_none_on_api_failure(self, isolated_state, isolated_db):
        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", new_callable=AsyncMock, return_value=None):
            p = poller.UsagePoller()
            result = await p.force_refresh()
        assert result is None

    def test_on_update_callback_is_called(self, isolated_state, isolated_db):
        """Verify the callback mechanism wires up correctly (sync check)."""
        received = []
        p = poller.UsagePoller(on_update=lambda s: received.append(s))
        snap = self._make_snapshot()
        # Simulate what the run loop does after a successful fetch
        p._current = snap
        if p._on_update:
            p._on_update(snap)
        assert len(received) == 1
        assert received[0].session_pct == 0.30


# ── fetch_usage (mocked HTTP) ─────────────────────────────────────────────────

class TestFetchUsage:
    @pytest.mark.asyncio
    async def test_successful_response_parsed_correctly(self):
        mock_response = MagicMock()
        # API returns utilization as 0–100 (e.g. 21 = 21%)
        mock_response.json.return_value = {
            "five_hour": {"utilization": 21, "resets_at": "2026-04-10T17:00:00Z"},
            "seven_day": {"utilization": 25, "resets_at": "2026-04-15T08:00:00Z"},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("poller.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            snap = await poller.fetch_usage("fake-token")

        assert snap is not None
        assert abs(snap.session_pct - 0.21) < 1e-6   # 21 / 100
        assert abs(snap.weekly_pct - 0.25) < 1e-6    # 25 / 100
        assert snap.session_resets_at == "2026-04-10T17:00:00Z"
        assert snap.is_stale is False

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        import httpx
        with patch("poller.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(side_effect=httpx.RequestError("timeout"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            snap = await poller.fetch_usage("fake-token")
        assert snap is None

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited_error(self):
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "120"}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )

        with patch("poller.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RateLimitedError) as exc_info:
                await poller.fetch_usage("fake-token")
        assert exc_info.value.retry_after == 120

    @pytest.mark.asyncio
    async def test_429_uses_default_retry_after_when_header_missing(self):
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )

        with patch("poller.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RateLimitedError) as exc_info:
                await poller.fetch_usage("fake-token")
        assert exc_info.value.retry_after == poller.RATE_LIMIT_BACKOFF_MAX_SEC

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self):
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )

        with patch("poller.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(AuthError):
                await poller.fetch_usage("fake-token")


# ── AuthError flag on UsagePoller ─────────────────────────────────────────────

class TestAuthErrorFlag:
    def _make_snapshot(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        return UsageSnapshot(
            session_pct=0.30,
            session_resets_at=(datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
            weekly_pct=0.40,
            weekly_resets_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            recorded_at=now,
        )

    def test_auth_error_false_by_default(self, isolated_state, isolated_db):
        p = poller.UsagePoller()
        assert p.auth_error is False

    @pytest.mark.asyncio
    async def test_force_refresh_sets_auth_error_on_401(self, isolated_state, isolated_db):
        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", new_callable=AsyncMock, side_effect=AuthError()):
            p = poller.UsagePoller()
            result = await p.force_refresh()
        assert result is None
        assert p.auth_error is True

    @pytest.mark.asyncio
    async def test_force_refresh_clears_auth_error_on_success(self, isolated_state, isolated_db):
        snap = self._make_snapshot()
        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", new_callable=AsyncMock, side_effect=AuthError()):
            p = poller.UsagePoller()
            await p.force_refresh()
        assert p.auth_error is True

        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", new_callable=AsyncMock, return_value=snap), \
             patch("poller.store_snapshot"), \
             patch("poller.save_state"):
            result = await p.force_refresh()
        assert result is not None
        assert p.auth_error is False
