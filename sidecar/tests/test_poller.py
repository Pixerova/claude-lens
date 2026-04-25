"""
test_poller.py — Tests for poller.py: interval logic, state file, snapshot model.

Network calls and Keychain access are always mocked — no real HTTP or
macOS Keychain required.
"""

import json
from datetime import datetime, timezone, timedelta, time as dtime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import poller
from conftest import make_usage_snapshot
from poller import (
    UsageSnapshot,
    RateLimitedError,
    AuthError,
    compute_interval,
    _effective_interval,
    _is_in_working_hours,
    _parse_hhmm,
    load_state,
    save_state,
    DEFAULT_THRESHOLDS,
    RATE_LIMIT_BACKOFF_MIN_SEC,
    SLEEP_INTERVAL_SEC,
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


# ── _effective_interval ───────────────────────────────────────────────────────

class TestEffectiveInterval:
    """At 100% session, sleep until reset; otherwise delegate to compute_interval."""

    def test_at_100pct_returns_secs_until_reset(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=3700)
        snap = UsageSnapshot(
            session_pct=1.0,
            session_resets_at=future.isoformat(),
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        interval = _effective_interval(snap)
        # Should be close to 3700, not the 30s critical-tier interval
        assert interval > 3600
        assert interval <= 3700

    def test_above_100pct_also_sleeps_until_reset(self):
        # The API could theoretically return slightly over 100 due to rounding
        future = datetime.now(timezone.utc) + timedelta(seconds=1800)
        snap = UsageSnapshot(
            session_pct=1.01,
            session_resets_at=future.isoformat(),
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        interval = _effective_interval(snap)
        assert interval > 1700
        assert interval <= 1800

    def test_at_100pct_with_past_reset_falls_back(self):
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        snap = UsageSnapshot(
            session_pct=1.0,
            session_resets_at=past.isoformat(),
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        # Reset already passed — fall back to normal interval for 100% (30s tier)
        assert _effective_interval(snap) == 30

    def test_at_100pct_with_missing_reset_falls_back(self):
        snap = UsageSnapshot(
            session_pct=1.0,
            session_resets_at="",
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        assert _effective_interval(snap) == 30

    def test_at_100pct_with_malformed_reset_falls_back(self):
        snap = UsageSnapshot(
            session_pct=1.0,
            session_resets_at="not-a-date",
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        assert _effective_interval(snap) == 30

    def test_below_100pct_delegates_to_compute_interval(self):
        snap = UsageSnapshot(
            session_pct=0.95,
            session_resets_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        assert _effective_interval(snap) == compute_interval(0.95, 0.10)

    def test_z_suffix_iso_string_parsed_correctly(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=500)
        # Simulate the Z-suffix format the API actually returns
        resets_at_z = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        snap = UsageSnapshot(
            session_pct=1.0,
            session_resets_at=resets_at_z,
            weekly_pct=0.10,
            weekly_resets_at="",
            recorded_at="",
        )
        interval = _effective_interval(snap)
        assert 0 < interval <= 500


# ── State file (load_state / save_state) ─────────────────────────────────────

class TestStateFile:

    def test_load_state_returns_none_when_no_file(self, isolated_state):
        snapshot, interval = load_state()
        assert snapshot is None
        assert interval == 0

    def test_save_and_load_round_trips(self, isolated_state):
        snap = make_usage_snapshot(session_pct=0.42, weekly_pct=0.77)
        save_state(snap, interval_sec=120)
        loaded, interval = load_state()

        assert loaded is not None
        assert abs(loaded.session_pct - 0.42) < 1e-6
        assert abs(loaded.weekly_pct  - 0.77) < 1e-6
        assert loaded.is_stale is True   # loaded from disk → always stale
        assert interval == 120

    def test_save_writes_interval(self, isolated_state):
        snap = make_usage_snapshot()
        save_state(snap, interval_sec=300)
        data = json.loads(isolated_state.read_text())
        assert data["currentIntervalSec"] == 300

    def test_save_writes_last_poll_at(self, isolated_state):
        snap = make_usage_snapshot()
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
        snap = make_usage_snapshot()
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

    def test_initial_current_is_none_when_no_state(self, isolated_state, isolated_db):
        p = poller.UsagePoller()
        assert p.current is None

    def test_initial_current_loaded_from_state(self, isolated_state, isolated_db):
        snap = make_usage_snapshot()
        save_state(snap, interval_sec=300)
        p = poller.UsagePoller()
        assert p.current is not None
        assert abs(p.current.session_pct - 0.30) < 1e-6

    @pytest.mark.asyncio
    async def test_force_refresh_returns_snapshot(self, isolated_state, isolated_db):
        snap = make_usage_snapshot()
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
        snap = make_usage_snapshot()
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
    async def test_429_with_zero_retry_after_enforces_minimum(self):
        """Retry-After: 0 must not result in an immediate retry."""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "0"}
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
        # fetch_usage raises with retry_after=0; the run loop enforces the floor
        assert exc_info.value.retry_after == 0

    @pytest.mark.asyncio
    async def test_run_loop_enforces_minimum_backoff_on_zero_retry_after(
        self, isolated_state, isolated_db
    ):
        """Run loop must wait at least RATE_LIMIT_BACKOFF_MIN_SEC even if Retry-After is 0."""
        snap = make_usage_snapshot()
        p = poller.UsagePoller()
        p._current = snap

        sleep_args = []
        call_count = 0

        async def fake_fetch(token):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitedError(retry_after=0)
            p.stop()
            return snap

        async def fake_sleep(secs):
            sleep_args.append(secs)

        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", side_effect=fake_fetch), \
             patch("poller.store_snapshot"), \
             patch("poller.save_state"), \
             patch("asyncio.sleep", side_effect=fake_sleep):
            await p.run()

        # First sleep must be the enforced minimum, not 0
        assert sleep_args[0] >= RATE_LIMIT_BACKOFF_MIN_SEC

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
        snap = make_usage_snapshot()
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

    @pytest.mark.asyncio
    async def test_run_loop_auth_error_sets_and_clears_flag(self, isolated_state, isolated_db):
        snap = make_usage_snapshot()
        p = poller.UsagePoller()
        p._current = snap  # give the poller a current snapshot so staleness can be checked

        states_before_success = []
        call_count = 0

        async def fake_fetch(token):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise AuthError()
            # Capture flag state just before the success clears it
            states_before_success.append(p.auth_error)
            p.stop()
            return snap

        with patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", side_effect=fake_fetch), \
             patch("poller.store_snapshot"), \
             patch("poller.save_state"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await p.run()

        assert states_before_success == [True], "auth_error should be True between 401 and next success"
        assert p.auth_error is False, "auth_error should clear after a successful poll"


# ── Working hours / sleep mode ────────────────────────────────────────────────

class TestParseHhmm:
    def test_parses_valid_string(self):
        assert _parse_hhmm("09:00") == dtime(9, 0)
        assert _parse_hhmm("17:30") == dtime(17, 30)

    def test_raises_on_bad_format(self):
        with pytest.raises((ValueError, TypeError)):
            _parse_hhmm("9am")


class TestIsInWorkingHours:
    """_is_in_working_hours accepts injectable _now_local/_now_utc for testing."""

    START = dtime(9, 0)
    END   = dtime(17, 0)

    # A fixed "now" UTC value used throughout — well in the past so active_until
    # comparisons are deterministic.
    NOW_UTC = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)

    FAR_FUTURE = datetime(2026, 4, 24, 23, 0, 0, tzinfo=timezone.utc)
    EXPIRED    = datetime(2026, 4, 24, 14, 0, 0, tzinfo=timezone.utc)  # before NOW_UTC

    def _local(self, hour, minute=0) -> datetime:
        return datetime(2026, 4, 24, hour, minute, 0)

    def test_inside_core_window_is_awake(self):
        assert _is_in_working_hours(
            self.START, self.END, self.EXPIRED,
            _now_local=self._local(12), _now_utc=self.NOW_UTC,
        ) is True

    def test_at_start_boundary_is_awake(self):
        assert _is_in_working_hours(
            self.START, self.END, self.EXPIRED,
            _now_local=self._local(9, 0), _now_utc=self.NOW_UTC,
        ) is True

    def test_at_end_boundary_is_awake(self):
        assert _is_in_working_hours(
            self.START, self.END, self.EXPIRED,
            _now_local=self._local(17, 0), _now_utc=self.NOW_UTC,
        ) is True

    def test_before_start_is_sleeping_regardless_of_extension(self):
        # active_until in the future should NOT override pre-start sleep
        assert _is_in_working_hours(
            self.START, self.END, self.FAR_FUTURE,
            _now_local=self._local(7), _now_utc=self.NOW_UTC,
        ) is False

    def test_after_end_no_extension_is_sleeping(self):
        assert _is_in_working_hours(
            self.START, self.END, self.EXPIRED,
            _now_local=self._local(18), _now_utc=self.NOW_UTC,
        ) is False

    def test_after_end_with_active_extension_is_awake(self):
        assert _is_in_working_hours(
            self.START, self.END, self.FAR_FUTURE,
            _now_local=self._local(18), _now_utc=self.NOW_UTC,
        ) is True

    def test_extension_expired_after_end_is_sleeping(self):
        # active_until is in the past relative to _now_utc
        assert _is_in_working_hours(
            self.START, self.END, self.EXPIRED,
            _now_local=self._local(18), _now_utc=self.NOW_UTC,
        ) is False


class TestUsagePollerWorkingHours:

    def test_is_sleeping_false_when_not_configured(self, isolated_state, isolated_db):
        p = poller.UsagePoller()
        assert p.is_sleeping is False

    def test_active_until_is_none_without_working_hours(self, isolated_state, isolated_db):
        p = poller.UsagePoller()
        assert p.active_until is None

    def test_active_until_exposed_when_configured(self, isolated_state, isolated_db):
        p = poller.UsagePoller(working_hours={"start": "09:00", "end": "17:00"})
        assert p.active_until is not None

    def test_extend_active_window_bumps_active_until(self, isolated_state, isolated_db):
        p = poller.UsagePoller(working_hours={"start": "09:00", "end": "17:00"})
        before = p.active_until
        p.extend_active_window()
        assert p.active_until > before

    def test_extend_does_not_reduce_active_until(self, isolated_state, isolated_db):
        p = poller.UsagePoller(working_hours={"start": "09:00", "end": "17:00"})
        far_future = datetime.now(timezone.utc) + timedelta(hours=5)
        with p._wh_lock:
            p._active_until = far_future
        p.extend_active_window()  # now+1h < far_future — should not shrink
        assert p.active_until == far_future

    def test_invalid_working_hours_disables_sleep(self, isolated_state, isolated_db):
        p = poller.UsagePoller(working_hours={"start": "bad", "end": "data"})
        assert p.is_sleeping is False
        assert p.active_until is None

    @pytest.mark.asyncio
    async def test_run_loop_uses_sleep_interval_when_sleeping(self, isolated_state, isolated_db):
        snap = make_usage_snapshot(session_pct=0.50)
        sleep_args = []

        async def fake_fetch(token):
            p.stop()
            return snap

        async def fake_sleep(secs):
            sleep_args.append(secs)

        p = poller.UsagePoller(working_hours={"start": "09:00", "end": "17:00"})
        # Force the poller into sleeping state by patching _is_in_working_hours
        with patch("poller._is_in_working_hours", return_value=False), \
             patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", side_effect=fake_fetch), \
             patch("poller.store_snapshot"), \
             patch("poller.save_state"), \
             patch("asyncio.sleep", side_effect=fake_sleep):
            await p.run()

        assert sleep_args == [SLEEP_INTERVAL_SEC]

    @pytest.mark.asyncio
    async def test_run_loop_uses_normal_interval_during_working_hours(self, isolated_state, isolated_db):
        snap = make_usage_snapshot(session_pct=0.50)
        sleep_args = []

        async def fake_fetch(token):
            p.stop()
            return snap

        async def fake_sleep(secs):
            sleep_args.append(secs)

        p = poller.UsagePoller(working_hours={"start": "09:00", "end": "17:00"})
        # Force awake state
        with patch("poller._is_in_working_hours", return_value=True), \
             patch("poller.get_oauth_token", return_value="sk-ant-oat01-fake"), \
             patch("poller.fetch_usage", side_effect=fake_fetch), \
             patch("poller.store_snapshot"), \
             patch("poller.save_state"), \
             patch("asyncio.sleep", side_effect=fake_sleep):
            await p.run()

        assert sleep_args == [300]   # 50% session → normal tier (300s)
