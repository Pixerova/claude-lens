"""
trigger_evaluator.py — Suggestions trigger evaluator.

Evaluates which suggestion trigger types are currently active.

Trigger types
─────────────
always             Always active.
low_utilization_eow  Any configured tier matches: weekly_pct < tier.weeklyPctBelow
                     AND hours_until_reset < tier.hoursUntilResetBelow.
post_reset         weekly_pct dropped ≥ dropThreshold vs prior reading AND
                   that drop was detected within windowHours.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hours_until_reset(weekly_resets_iso: Optional[str]) -> float:
    """Hours from now until the weekly reset.  Returns 9999 on parse failure."""
    if not weekly_resets_iso:
        return 9999.0
    try:
        resets_at = datetime.fromisoformat(weekly_resets_iso.replace("Z", "+00:00"))
        delta = resets_at - datetime.now(tz=timezone.utc)
        return max(delta.total_seconds() / 3600, 0.0)
    except (ValueError, AttributeError):
        log.warning("Could not parse weekly_resets timestamp: %r", weekly_resets_iso)
        return 9999.0


def _low_util_tiers(config: dict) -> list[dict]:
    """Return the list of low_utilization_eow tier dicts from config."""
    try:
        return config["suggestions"]["triggers"]["low_utilization_eow"]["tiers"]
    except (KeyError, TypeError):
        return []


def _post_reset_config(config: dict) -> tuple[float, float]:
    """Return (dropThreshold, windowHours) from config."""
    try:
        t = config["suggestions"]["triggers"]["post_reset"]
        return float(t["dropThreshold"]), float(t["windowHours"])
    except (KeyError, TypeError):
        return 0.30, 4.0


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate_triggers(
    weekly_pct: float,
    weekly_resets: Optional[str],
    prior_weekly_pct: Optional[float],
    prior_recorded_at: Optional[str],
    config: dict,
) -> set[str]:
    """Evaluate which trigger types are currently active.

    Args:
        weekly_pct:         Current weekly utilisation (0.0–1.0).
        weekly_resets:      ISO 8601 UTC string of the next weekly reset.
        prior_weekly_pct:   Weekly utilisation from the previous poll reading.
        prior_recorded_at:  ISO 8601 UTC timestamp of the previous reading.
        config:             Loaded config dict (from ~/.claudelens/config.json).

    Returns:
        Set of active trigger type strings, e.g. {"always", "low_utilization_eow"}.
    """
    active: set[str] = {"always"}

    # ── low_utilization_eow ───────────────────────────────────────────────────
    hours_until = _hours_until_reset(weekly_resets)
    tiers = _low_util_tiers(config)

    for tier in tiers:
        try:
            pct_threshold = float(tier["weeklyPctBelow"])
            hours_threshold = float(tier["hoursUntilResetBelow"])
        except (KeyError, TypeError, ValueError):
            log.warning("Skipping malformed low_utilization_eow tier: %r", tier)
            continue

        if weekly_pct < pct_threshold and hours_until < hours_threshold:
            active.add("low_utilization_eow")
            log.debug(
                "low_utilization_eow tier matched: weekly_pct=%.2f < %.2f, "
                "hours_until=%.1f < %.1f",
                weekly_pct, pct_threshold, hours_until, hours_threshold,
            )
            break  # one matching tier is sufficient

    # ── post_reset ────────────────────────────────────────────────────────────
    drop_threshold, window_hours = _post_reset_config(config)

    if prior_weekly_pct is not None and prior_recorded_at is not None:
        drop = prior_weekly_pct - weekly_pct
        if drop >= drop_threshold:
            try:
                prior_dt = datetime.fromisoformat(prior_recorded_at.replace("Z", "+00:00"))
                hours_since = (datetime.now(tz=timezone.utc) - prior_dt).total_seconds() / 3600
                if hours_since <= window_hours:
                    active.add("post_reset")
                    log.debug(
                        "post_reset: drop=%.2f >= %.2f, hours_since=%.1f <= %.1f",
                        drop, drop_threshold, hours_since, window_hours,
                    )
            except (ValueError, AttributeError):
                log.warning("Could not parse prior_recorded_at: %r", prior_recorded_at)

    return active


def build_trigger_context(
    weekly_pct: float,
    weekly_resets: Optional[str],
    active_triggers: set[str],
) -> dict:
    """Build the trigger_context dict included in GET /suggestions response."""
    return {
        "always":               "always" in active_triggers,
        "low_utilization_eow":  "low_utilization_eow" in active_triggers,
        "post_reset":           "post_reset" in active_triggers,
        "weekly_pct":           round(weekly_pct, 4),
        "hours_until_reset":    round(_hours_until_reset(weekly_resets), 2),
    }
