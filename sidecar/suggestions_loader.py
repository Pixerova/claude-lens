"""
suggestions_loader.py — Suggestions YAML loader.

Loads and validates suggestion definitions from suggestions.yaml.

Bootstrap behaviour:
  - On first launch, the bundled copy (sidecar/data/suggestions.yaml) is
    copied to ~/.claudelens/suggestions.yaml.
  - On subsequent launches, the user copy is read, allowing local additions.

Invalid entries are skipped with a logged WARNING; valid entries load normally.
The loader is cheap to call repeatedly — safe to call on every poll cycle.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Canonical path of the bundled YAML, relative to this file's directory.
_BUNDLED_YAML = Path(__file__).parent / "data" / "suggestions.yaml"

# Where the user copy lives.
_USER_YAML = Path.home() / ".claudelens" / "suggestions.yaml"

VALID_TRIGGERS = {"always", "low_utilization_eow", "post_reset"}
VALID_CATEGORIES = {
    "code_health",
    "dependencies",
    "documentation",
    "maintenance",
    "product",
    "productivity",
    "security",
    "testing",
}
REQUIRED_FIELDS = {
    "id",
    "category",
    "title",
    "description",
    "prompt",
    "trigger",
    "show_every_n_days",
    "actions",
}


def _ensure_user_copy() -> Path:
    """Copy bundled YAML to ~/.claudelens/ on first launch; return the user path."""
    _USER_YAML.parent.mkdir(parents=True, exist_ok=True)
    if not _USER_YAML.exists():
        if not _BUNDLED_YAML.exists():
            log.error(
                "Bundled suggestions.yaml not found at %s — cannot bootstrap user copy.",
                _BUNDLED_YAML,
            )
        else:
            shutil.copy2(_BUNDLED_YAML, _USER_YAML)
            log.info("Bootstrapped suggestions.yaml → %s", _USER_YAML)
    return _USER_YAML


def _validate_entry(entry: Any, index: int) -> dict | None:
    """Validate a single suggestion entry.  Returns the dict or None if invalid."""
    if not isinstance(entry, dict):
        log.warning("suggestions.yaml entry #%d is not a mapping — skipped.", index)
        return None

    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        log.warning(
            "suggestions.yaml entry #%d (id=%r) missing required fields %s — skipped.",
            index,
            entry.get("id"),
            sorted(missing),
        )
        return None

    suggestion_id = entry["id"]

    if entry["category"] not in VALID_CATEGORIES:
        log.warning(
            "suggestions.yaml entry %r has invalid category %r — skipped.",
            suggestion_id,
            entry["category"],
        )
        return None

    # Schema supports list for future use; v1 uses a single string.
    raw_trigger = entry["trigger"]
    triggers = raw_trigger if isinstance(raw_trigger, list) else [raw_trigger]

    invalid = set(triggers) - VALID_TRIGGERS
    if invalid:
        log.warning(
            "suggestions.yaml entry %r has invalid trigger(s) %s — skipped.",
            suggestion_id,
            sorted(invalid),
        )
        return None

    n = entry.get("show_every_n_days")
    if not isinstance(n, int) or n < 1:
        log.warning(
            "suggestions.yaml entry %r has invalid show_every_n_days %r — skipped.",
            suggestion_id,
            n,
        )
        return None

    actions = entry.get("actions")
    if not isinstance(actions, list) or len(actions) == 0:
        log.warning(
            "suggestions.yaml entry %r has empty or missing actions — skipped.",
            suggestion_id,
        )
        return None

    result = dict(entry)
    result["trigger"] = triggers[0]  # normalise to scalar for v1
    return result


def load_suggestions(user_yaml_path: Path | None = None) -> list[dict] | None:
    """Load, validate, and return all suggestions.

    Args:
        user_yaml_path: Override path for the user YAML (used in tests).

    Returns:
        List of validated suggestion dicts on success (may be empty if the file
        is valid but contains no entries).
        None if the file cannot be parsed as YAML — the caller should keep its
        existing cache rather than replacing it with an empty list.
        Individual invalid entries are skipped with a WARNING and never cause
        None to be returned.
    """
    source = user_yaml_path or _ensure_user_copy()

    if not source.exists():
        log.error("suggestions.yaml not found at %s — returning empty list.", source)
        return []

    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        log.error(
            "suggestions.yaml is not valid YAML and could not be parsed: %s", exc
        )
        return None  # signal: do NOT clear the caller's existing cache

    if not isinstance(raw, dict) or "suggestions" not in raw:
        log.error("suggestions.yaml has unexpected structure — returning empty list.")
        return []

    entries = raw.get("suggestions")
    if not isinstance(entries, list):
        log.error("suggestions.yaml 'suggestions' key is not a list — returning empty list.")
        return []

    validated: list[dict] = []
    seen_ids: set[str] = set()

    for i, entry in enumerate(entries):
        result = _validate_entry(entry, i)
        if result is None:
            continue
        sid = result["id"]
        if sid in seen_ids:
            log.warning(
                "suggestions.yaml entry #%d has duplicate id %r — skipped.", i, sid
            )
            continue
        seen_ids.add(sid)
        validated.append(result)

    log.info("Loaded %d valid suggestions from %s.", len(validated), source)
    return validated
