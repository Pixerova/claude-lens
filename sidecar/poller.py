"""
poller.py — OAuth API client with dynamic polling interval and exponential backoff.

Polls GET https://api.anthropic.com/api/oauth/usage on an adaptive schedule:
  ≥ 90%  → every 30 s   (critical)
  ≥ 80%  → every 60 s   (high)
  ≥ 60%  → every 120 s  (elevated)
  ≥ 20%  → every 300 s  (normal)
  ≥ 5%   → every 1800 s (low)
  < 5%   → every 3600 s (minimal)

On 429, respects the Retry-After header and backs off up to a 2-hour cap.
On other errors, backs off exponentially up to a 10-min cap.
On restart, honours the saved poll interval to avoid an immediate burst.
The last known good response is always persisted to state.json for offline display.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

import httpx

from keychain import get_oauth_token
from db import store_snapshot

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
API_BETA_HEADER = "oauth-2025-04-20"
STATE_PATH = Path.home() / ".claudelens" / "state.json"

# Default poll thresholds (utilisation → interval seconds).
# Overridable via config.json "poll.thresholds".
DEFAULT_THRESHOLDS: list[tuple[float, int]] = [
    (0.90, 30),
    (0.80, 60),
    (0.60, 120),
    (0.20, 300),
    (0.05, 1800),
    (0.00, 3600),
]

BACKOFF_MAX_SEC = 600        # 10 minutes — for transient errors
RATE_LIMIT_BACKOFF_MAX_SEC = 7200  # 2 hours — for 429s


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
    thresholds: list[tuple[float, int]] = DEFAULT_THRESHOLDS,
) -> int:
    """Return the appropriate poll interval in seconds given current utilisation."""
    utilisation = session_pct
    for threshold, interval in thresholds:
        if utilisation >= threshold:
            return interval
    return DEFAULT_THRESHOLDS[-1][1]


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
    """
    Background async task that polls the usage API on a dynamic interval.

    Usage:
        poller = UsagePoller(on_update=my_callback)
        asyncio.create_task(poller.run())
    """

    def __init__(
        self,
        on_update: Optional[Callable[[UsageSnapshot], None]] = None,
        thresholds: list[tuple[float, int]] = DEFAULT_THRESHOLDS,
    ):
        self._on_update = on_update
        self._thresholds = thresholds
        self._current, saved_interval = load_state()
        self._backoff_sec: int = 0
        self._running = False
        self._auth_error: bool = False

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

        self._interval_sec: int = saved_interval or DEFAULT_THRESHOLDS[3][1]
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
                wait = min(exc.retry_after, RATE_LIMIT_BACKOFF_MAX_SEC)
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
                self._interval_sec = compute_interval(
                    snapshot.session_pct, snapshot.weekly_pct, self._thresholds
                )
                save_state(snapshot, self._interval_sec)

                if self._on_update:
                    result = self._on_update(snapshot)
                    if asyncio.iscoroutine(result):
                        await result

                log.info(
                    "Usage: session=%.0f%% weekly=%.0f%% → next poll in %ds",
                    snapshot.session_pct * 100,
                    snapshot.weekly_pct * 100,
                    self._interval_sec,
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
        """Trigger an immediate poll outside the normal schedule. Returns new snapshot."""
        token = get_oauth_token()
        if not token:
            return None
        try:
            snapshot = await fetch_usage(token)
        except AuthError:
            self._auth_error = True
            return None
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
            self._interval_sec = compute_interval(
                snapshot.session_pct, snapshot.weekly_pct, self._thresholds
            )
            save_state(snapshot, self._interval_sec)
            if self._on_update:
                result = self._on_update(snapshot)
                if asyncio.iscoroutine(result):
                    await result
        return snapshot
