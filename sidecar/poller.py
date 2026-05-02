"""
poller.py — OAuth API client with dynamic polling interval and exponential backoff.

Polls GET https://api.anthropic.com/api/oauth/usage on an adaptive schedule:
  ≥ 90%  → every 30 s   (critical)
  ≥ 80%  → every 60 s   (high)
  ≥ 60%  → every 120 s  (elevated)
  ≥ 20%  → every 300 s  (normal)
  ≥ 5%   → every 1800 s (low)
  < 5%   → every 3600 s (minimal)

Outside working hours the poller enters sleep mode and polls every 30 minutes
instead. If new Claude session activity is detected after end-of-day, the active
window is extended by one hour from the last detected event.

On 429, respects the Retry-After header and backs off up to a 2-hour cap.
On other errors, backs off exponentially up to a 10-min cap.
On restart, honours the saved poll interval to avoid an immediate burst.
The last known good response is always persisted to state.json for offline display.
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path
from typing import Optional

import httpx

from keychain import get_oauth_token
from db import store_snapshot

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
API_BETA_HEADER = "oauth-2025-04-20"
STATE_PATH = Path.home() / ".claude-lens" / "state.json"

BACKOFF_MAX_SEC = 600              # 10 minutes — for transient errors
RATE_LIMIT_BACKOFF_MIN_SEC = 60    # never back off less than 1 minute on 429
RATE_LIMIT_BACKOFF_MAX_SEC = 7200  # 2 hours — for 429s
SLEEP_INTERVAL_SEC = 1800          # 30 minutes — outside working hours


# ── Exceptions ────────────────────────────────────────────────────────────────

class RateLimitedError(Exception):
    """Raised when the API returns 429. retry_after is seconds to wait."""
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited — retry after {retry_after}s")


class AuthError(Exception):
    """Raised when the API returns 401 — token expired or invalid."""


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class UsageSnapshot:
    session_pct: float
    session_resets_at: str   # ISO 8601 UTC
    weekly_pct: float
    weekly_resets_at: str    # ISO 8601 UTC
    recorded_at: str         # ISO 8601 UTC
    is_stale: bool = False


# ── State file ────────────────────────────────────────────────────────────────

def load_state() -> tuple[Optional[UsageSnapshot], int]:
    """
    Load the last known usage snapshot and saved poll interval from disk.
    Returns (snapshot, interval_sec). interval_sec is 0 if not saved.
    """
    try:
        if STATE_PATH.exists():
            data = json.loads(STATE_PATH.read_text())
            usage = data.get("lastKnownUsage", {})
            interval = int(data.get("currentIntervalSec", 0))
            if usage:
                snapshot = UsageSnapshot(
                    session_pct=usage["sessionPct"],
                    session_resets_at=usage["sessionResetsAt"],
                    weekly_pct=usage["weeklyPct"],
                    weekly_resets_at=usage["weeklyResetsAt"],
                    recorded_at=data.get("lastPollAt", ""),
                    is_stale=True,
                )
                return snapshot, interval
    except Exception as exc:
        log.debug("Could not load state.json: %s", exc)
    return None, 0


def save_state(snapshot: UsageSnapshot, interval_sec: int) -> None:
    """Persist latest snapshot + current interval to state.json."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lastPollAt": snapshot.recorded_at,
        "lastKnownUsage": {
            "sessionPct":      snapshot.session_pct,
            "sessionResetsAt": snapshot.session_resets_at,
            "weeklyPct":       snapshot.weekly_pct,
            "weeklyResetsAt":  snapshot.weekly_resets_at,
        },
        "currentIntervalSec": interval_sec,
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2))


# ── Interval calculation ──────────────────────────────────────────────────────

def compute_interval(
    session_pct: float,
    weekly_pct: float,
    thresholds: list[tuple[float, int]],
) -> int:
    """Return the appropriate poll interval in seconds given current utilisation."""
    utilisation = session_pct
    for threshold, interval in thresholds:
        if utilisation >= threshold:
            return interval
    return thresholds[-1][1] if thresholds else 300


def _effective_interval(
    snapshot: "UsageSnapshot",
    thresholds: list[tuple[float, int]],
) -> int:
    """
    Return the poll interval for the given snapshot.

    At 100% session usage the next poll can't change anything until the session
    resets, so we sleep exactly until `session_resets_at` rather than hammering
    the API every 30 s.  Falls back to `compute_interval` if the reset time is
    unparseable, already in the past, or session is below 100%.
    """
    if snapshot.session_pct >= 1.0 and snapshot.session_resets_at:
        try:
            resets_at = datetime.fromisoformat(
                snapshot.session_resets_at.replace("Z", "+00:00")
            )
            secs = int((resets_at - datetime.now(timezone.utc)).total_seconds())
            if secs > 0:
                return secs
        except Exception:
            pass
    return compute_interval(snapshot.session_pct, snapshot.weekly_pct, thresholds)


# ── Working hours ─────────────────────────────────────────────────────────────

def _parse_hhmm(hhmm: str) -> dtime:
    """Parse "HH:MM" → datetime.time. Raises ValueError on bad input."""
    h, m = hhmm.split(":")
    return dtime(int(h), int(m))


def _is_in_working_hours(
    wh_start: dtime,
    wh_end: dtime,
    active_until: datetime,
    _now_local: Optional[datetime] = None,
    _now_utc: Optional[datetime] = None,
) -> bool:
    """
    Return True if the poller should be in normal (awake) polling mode.

    Two conditions:
      1. Local wall-clock time is within [wh_start, wh_end]  (core window), OR
      2. Local time is past wh_end AND UTC now ≤ active_until (post-EOD extension).

    Pre-start-of-day is always sleeping — active_until only extends the end, not
    the beginning, of the working day.

    Working-hours comparison uses local time intentionally; the sidecar runs on
    the user's own machine so datetime.now() reflects their timezone.

    _now_local and _now_utc are injectable for tests only.
    """
    now_local = _now_local if _now_local is not None else datetime.now()
    now_time = now_local.time()

    if wh_start <= now_time <= wh_end:
        return True

    # Extension only applies after end-of-day
    if now_time > wh_end:
        now_utc = _now_utc if _now_utc is not None else datetime.now(timezone.utc)
        if now_utc <= active_until:
            return True

    return False


# ── API client ────────────────────────────────────────────────────────────────

async def fetch_usage(token: str) -> Optional[UsageSnapshot]:
    """
    Call the Anthropic OAuth usage endpoint.
    Returns a UsageSnapshot on success, None on transient/unexpected failure.
    Raises AuthError on 401 (token expired or invalid).
    Raises RateLimitedError on 429.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": API_BETA_HEADER,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(USAGE_API_URL, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            five_hour = data.get("five_hour", {})
            seven_day = data.get("seven_day", {})
            now = datetime.now(timezone.utc).isoformat()

            snapshot = UsageSnapshot(
                session_pct=float(five_hour.get("utilization", 0)) / 100,
                session_resets_at=five_hour.get("resets_at") or "",
                weekly_pct=float(seven_day.get("utilization", 0)) / 100,
                weekly_resets_at=seven_day.get("resets_at") or "",
                recorded_at=now,
                is_stale=False,
            )
            return snapshot

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            try:
                retry_after = int(exc.response.headers.get("Retry-After", RATE_LIMIT_BACKOFF_MAX_SEC))
            except (ValueError, TypeError):
                retry_after = RATE_LIMIT_BACKOFF_MAX_SEC
            raise RateLimitedError(retry_after)
        elif exc.response.status_code == 401:
            log.error("OAuth token rejected (401) — may need to re-authenticate Claude Code")
            raise AuthError()
        else:
            log.warning("Usage API returned %s", exc.response.status_code)
    except httpx.RequestError as exc:
        log.warning("Network error fetching usage: %s", exc)
    except Exception as exc:
        log.exception("Unexpected error fetching usage: %s", exc)

    return None


# ── Poller ────────────────────────────────────────────────────────────────────

class UsagePoller:
    """Background async task that polls the usage API on a dynamic interval."""

    def __init__(
        self,
        thresholds: list[tuple[float, int]],
        working_hours: Optional[dict] = None,
    ):
        self._thresholds = thresholds
        self._current, saved_interval = load_state()
        self._backoff_sec: int = 0
        self._running = False
        self._auth_error: bool = False

        # Working hours — None means disabled (never sleep).
        self._wh_start: Optional[dtime] = None
        self._wh_end:   Optional[dtime] = None
        if working_hours:
            try:
                self._wh_start = _parse_hhmm(working_hours["start"])
                self._wh_end   = _parse_hhmm(working_hours["end"])
                log.info(
                    "Working hours: %s – %s (sleep interval %ds)",
                    working_hours["start"], working_hours["end"], SLEEP_INTERVAL_SEC,
                )
            except (KeyError, ValueError) as exc:
                log.warning("Invalid workingHours config (%s) — sleep mode disabled", exc)

        # active_until starts expired so no extension is in effect on startup.
        # extend_active_window() bumps it to now+1h when out-of-hours activity fires.
        self._active_until: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._wh_lock = threading.Lock()

        # Calculate how long to wait before the first poll based on saved state.
        # If we restarted before the saved interval elapsed, wait the remainder
        # rather than hammering the API immediately.
        self._initial_sleep_sec: int = 0
        if self._current and saved_interval > 0:
            try:
                last_poll = datetime.fromisoformat(self._current.recorded_at)
                elapsed = int((datetime.now(timezone.utc) - last_poll).total_seconds())
                remaining = saved_interval - elapsed
                self._initial_sleep_sec = max(0, remaining)
            except Exception:
                pass

        self._interval_sec: int = saved_interval or compute_interval(0.20, 0.0, thresholds)
        if self._initial_sleep_sec > 0:
            log.info("Resuming poll schedule — first poll in %ds", self._initial_sleep_sec)

    @property
    def current(self) -> Optional[UsageSnapshot]:
        return self._current

    @property
    def interval_sec(self) -> int:
        return self._interval_sec

    @property
    def auth_error(self) -> bool:
        return self._auth_error

    @property
    def is_sleeping(self) -> bool:
        """True when outside working hours with no active extension in effect."""
        if self._wh_start is None or self._wh_end is None:
            return False
        with self._wh_lock:
            active_until = self._active_until
        return not _is_in_working_hours(self._wh_start, self._wh_end, active_until)

    @property
    def active_until(self) -> Optional[datetime]:
        """The UTC datetime until which the active window has been extended, or None if
        working hours are not configured."""
        if self._wh_start is None:
            return None
        with self._wh_lock:
            return self._active_until

    def extend_active_window(self) -> None:
        """Thread-safe. Extend the active window to now+1h (no-op if already further out).

        Called by ActivityMonitor from the watchdog observer thread when Claude
        session file activity is detected outside working hours.
        """
        candidate = datetime.now(timezone.utc) + timedelta(hours=1)
        with self._wh_lock:
            if candidate > self._active_until:
                self._active_until = candidate
        log.info("Active window extended — polling until %s", candidate.isoformat())

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        consecutive_failures = 0

        # Honour the saved poll schedule on restart
        if self._initial_sleep_sec > 0:
            await asyncio.sleep(self._initial_sleep_sec)

        while self._running:
            token = get_oauth_token()
            if not token:
                log.error("No OAuth token — retrying in 60s")
                await asyncio.sleep(60)
                continue

            try:
                snapshot = await fetch_usage(token)
            except RateLimitedError as exc:
                consecutive_failures += 1
                if self._current:
                    self._current.is_stale = True
                wait = max(RATE_LIMIT_BACKOFF_MIN_SEC, min(exc.retry_after, RATE_LIMIT_BACKOFF_MAX_SEC))
                log.warning(
                    "Rate limited (429) — backing off %ds (attempt %d)",
                    wait, consecutive_failures,
                )
                await asyncio.sleep(wait)
                continue
            except AuthError:
                self._auth_error = True
                if self._current:
                    self._current.is_stale = True
                # Auth errors are persistent, not transient — don't increment
                # consecutive_failures so backoff stays at its current level.
                log.warning("Auth error (401) — retrying in %ds", BACKOFF_MAX_SEC)
                await asyncio.sleep(BACKOFF_MAX_SEC)
                continue

            if snapshot:
                consecutive_failures = 0
                self._backoff_sec = 0
                self._auth_error = False
                self._current = snapshot

                store_snapshot(
                    session_pct=snapshot.session_pct,
                    session_resets=snapshot.session_resets_at,
                    weekly_pct=snapshot.weekly_pct,
                    weekly_resets=snapshot.weekly_resets_at,
                )
                self._interval_sec = _effective_interval(snapshot, self._thresholds)
                sleeping = self.is_sleeping
                if sleeping:
                    self._interval_sec = SLEEP_INTERVAL_SEC
                save_state(snapshot, self._interval_sec)

                log.info(
                    "Usage: session=%.0f%% weekly=%.0f%% → next poll in %ds%s",
                    snapshot.session_pct * 100,
                    snapshot.weekly_pct * 100,
                    self._interval_sec,
                    " (sleeping)" if sleeping else "",
                )
                await asyncio.sleep(self._interval_sec)

            else:
                # Transient failure — exponential backoff capped at 10 min
                consecutive_failures += 1
                if self._current:
                    self._current.is_stale = True

                self._backoff_sec = min(
                    30 * (2 ** (consecutive_failures - 1)), BACKOFF_MAX_SEC
                )
                log.warning(
                    "Usage fetch failed (attempt %d) — backing off %ds",
                    consecutive_failures,
                    self._backoff_sec,
                )
                await asyncio.sleep(self._backoff_sec)

    async def force_refresh(self) -> Optional[UsageSnapshot]:
        """Trigger an immediate poll outside the normal schedule.

        Returns the new UsageSnapshot on success, or None if the token is
        missing or a transient network/API error occurred.
        Raises AuthError if the token is rejected (401).
        Raises RateLimitedError if the Anthropic API is rate-limiting (429).
        """
        token = get_oauth_token()
        if not token:
            return None
        try:
            snapshot = await fetch_usage(token)
        except AuthError:
            self._auth_error = True
            return None
        # Do not clear _auth_error on a transient None return — main.py checks
        # _poller.auth_error after a None result to decide 401 vs 502. Leaving
        # _auth_error untouched keeps the auth banner visible through a network
        # hiccup and prevents the wrong error panel from appearing.
        if snapshot:
            self._auth_error = False
            self._current = snapshot
            self._backoff_sec = 0
            store_snapshot(
                session_pct=snapshot.session_pct,
                session_resets=snapshot.session_resets_at,
                weekly_pct=snapshot.weekly_pct,
                weekly_resets=snapshot.weekly_resets_at,
            )
            self._interval_sec = _effective_interval(snapshot, self._thresholds)
            if self.is_sleeping:
                self._interval_sec = SLEEP_INTERVAL_SEC
            save_state(snapshot, self._interval_sec)
        return snapshot
