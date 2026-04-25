"""
suggestions_loader.py — Suggestions YAML loader.

Loads and merges suggestion definitions from two sources:

  1. Bundled suggestions (sidecar/data/suggestions.yaml):
     Always read directly on every launch — never copied to the user directory.
     Updates, removals, and additions propagate automatically.

  2. Custom suggestions (~/.claudelens/custom_suggestions.yaml):
     Bootstrapped from a template on first launch; never overwritten by the app.
     All entries must have ids and categories prefixed with 'custom_'.

Invalid entries are skipped with a logged WARNING. The merged list has bundled
suggestions first, then custom additions. Bundled IDs take precedence on any
collision.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

from suggestions_schema import CUSTOM_PREFIX, VALID_TRIGGERS, REQUIRED_FIELDS

log = logging.getLogger(__name__)

_BUNDLED_YAML = Path(__file__).parent / "data" / "suggestions.yaml"
_CUSTOM_TEMPLATE = Path(__file__).parent / "data" / "custom_suggestions_template.yaml"
_CUSTOM_YAML = Path.home() / ".claudelens" / "custom_suggestions.yaml"

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


def _ensure_custom_file() -> Path:
    """Bootstrap custom_suggestions.yaml from the template on first launch."""
    _CUSTOM_YAML.parent.mkdir(parents=True, exist_ok=True)
    if not _CUSTOM_YAML.exists():
        if _CUSTOM_TEMPLATE.exists():
            shutil.copy2(_CUSTOM_TEMPLATE, _CUSTOM_YAML)
            log.info("Bootstrapped custom_suggestions.yaml → %s", _CUSTOM_YAML)
        else:
            log.warning(
                "Custom suggestions template not found at %s — skipping bootstrap.",
                _CUSTOM_TEMPLATE,
            )
    return _CUSTOM_YAML


def _parse_yaml_file(path: Path) -> list | None:
    """Read and parse a suggestions YAML file.

    Returns:
        list  — raw entries from the 'suggestions' key (may be [] for an empty list).
        None  — file is missing, unparseable, or structurally invalid; caller should preserve its cache.
    """
    if not path.exists():
        log.error("Suggestions file not found at %s.", path)
        return None

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        log.error("Suggestions file at %s is not valid YAML: %s", path, exc)
        return None

    if not isinstance(raw, dict) or "suggestions" not in raw:
        log.error(
            "Suggestions file at %s has unexpected structure — expected a 'suggestions' key.",
            path,
        )
        return None

    entries = raw.get("suggestions")
    if not isinstance(entries, list):
        log.error("Suggestions file at %s: 'suggestions' key is not a list.", path)
        return None

    return entries


def _validate_entry(
    entry: Any,
    index: int,
    *,
    require_custom_prefix: bool = False,
    reject_custom_prefix: bool = False,
) -> dict | None:
    """Validate a single suggestion entry. Returns the validated dict or None."""
    if not isinstance(entry, dict):
        log.warning("Suggestion entry #%d is not a mapping — skipped.", index)
        return None

    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        log.warning(
            "Suggestion entry #%d (id=%r) missing required fields %s — skipped.",
            index,
            entry.get("id"),
            sorted(missing),
        )
        return None

    suggestion_id = str(entry["id"])
    category = str(entry["category"])

    if require_custom_prefix:
        if not suggestion_id.startswith(CUSTOM_PREFIX):
            log.warning(
                "Custom suggestion %r: id must start with %r — skipped. "
                "Run validate_suggestions.py to check your custom_suggestions.yaml.",
                suggestion_id,
                CUSTOM_PREFIX,
            )
            return None
        if not category.startswith(CUSTOM_PREFIX):
            log.warning(
                "Custom suggestion %r: category must start with %r — skipped. "
                "Run validate_suggestions.py to check your custom_suggestions.yaml.",
                suggestion_id,
                CUSTOM_PREFIX,
            )
            return None

    if reject_custom_prefix:
        if suggestion_id.startswith(CUSTOM_PREFIX):
            log.warning(
                "Bundled suggestion %r: id must not start with %r — skipped.",
                suggestion_id,
                CUSTOM_PREFIX,
            )
            return None
        if category.startswith(CUSTOM_PREFIX):
            log.warning(
                "Bundled suggestion %r: category must not start with %r — skipped.",
                suggestion_id,
                CUSTOM_PREFIX,
            )
            return None

    if not category.startswith(CUSTOM_PREFIX) and category not in VALID_CATEGORIES:
        log.warning(
            "Suggestion entry %r has invalid category %r — skipped.",
            suggestion_id,
            category,
        )
        return None

    raw_trigger = entry["trigger"]
    triggers = raw_trigger if isinstance(raw_trigger, list) else [raw_trigger]
    invalid_triggers = set(triggers) - VALID_TRIGGERS
    if invalid_triggers:
        log.warning(
            "Suggestion entry %r has invalid trigger(s) %s — skipped.",
            suggestion_id,
            sorted(invalid_triggers),
        )
        return None

    n = entry.get("show_every_n_days")
    if not isinstance(n, int) or n < 1:
        log.warning(
            "Suggestion entry %r has invalid show_every_n_days %r — skipped.",
            suggestion_id,
            n,
        )
        return None

    actions = entry.get("actions")
    if not isinstance(actions, list) or len(actions) == 0:
        log.warning(
            "Suggestion entry %r has empty or missing actions — skipped.",
            suggestion_id,
        )
        return None

    result = dict(entry)
    result["trigger"] = triggers[0]  # normalise to scalar for v1
    return result


def _load_bundled(path: Path | None = None) -> list[dict] | None:
    """Load and validate bundled suggestions.

    Returns a list of validated dicts (each with source='bundled'), or None if
    the file cannot be parsed — caller should keep its existing cache.
    """
    source = path or _BUNDLED_YAML
    entries = _parse_yaml_file(source)
    if entries is None:
        return None

    validated: list[dict] = []
    seen_ids: set[str] = set()

    for i, entry in enumerate(entries):
        result = _validate_entry(entry, i, reject_custom_prefix=True)
        if result is None:
            continue
        sid = result["id"]
        if sid in seen_ids:
            log.warning("Bundled suggestion entry #%d has duplicate id %r — skipped.", i, sid)
            continue
        seen_ids.add(sid)
        result["source"] = "bundled"
        validated.append(result)

    log.info("Loaded %d bundled suggestions from %s.", len(validated), source)
    return validated


def _load_custom(path: Path | None = None) -> list[dict] | None:
    """Load and validate custom suggestions.

    Returns a list of validated dicts (each with source='custom'), [] if the
    file is absent (normal on first launch when template is missing), or None
    if the file exists but cannot be parsed (caller should log and fall back).
    """
    source = path if path is not None else _ensure_custom_file()
    if not source.exists():
        return []
    entries = _parse_yaml_file(source)
    if entries is None:
        return None

    validated: list[dict] = []
    seen_ids: set[str] = set()

    for i, entry in enumerate(entries):
        result = _validate_entry(entry, i, require_custom_prefix=True)
        if result is None:
            continue
        sid = result["id"]
        if sid in seen_ids:
            log.warning("Custom suggestion entry #%d has duplicate id %r — skipped.", i, sid)
            continue
        seen_ids.add(sid)
        result["source"] = "custom"
        validated.append(result)

    log.info("Loaded %d custom suggestions from %s.", len(validated), source)
    return validated


def load_suggestions(
    bundled_yaml_path: Path | None = None,
    custom_yaml_path: Path | None = None,
) -> list[dict] | None:
    """Load and merge bundled and custom suggestions.

    Args:
        bundled_yaml_path: Override for the bundled YAML path (used in tests).
        custom_yaml_path: Override for the custom YAML path (used in tests).

    Returns:
        Merged list of validated suggestion dicts — bundled first, then custom.
        Returns None if the bundled file cannot be parsed (caller should keep
        its existing cache rather than replacing with an empty list).
        A custom file parse error is logged but does not cause None to be returned.
    """
    bundled = _load_bundled(bundled_yaml_path)
    if bundled is None:
        return None

    custom = _load_custom(custom_yaml_path)
    if custom is None:
        log.warning("Custom suggestions file could not be parsed — using bundled only.")
        custom = []

    bundled_ids = {s["id"] for s in bundled}
    merged = list(bundled)
    for s in custom:
        if s["id"] in bundled_ids:
            log.warning(
                "Custom suggestion %r has the same id as a bundled suggestion — skipped.",
                s["id"],
            )
        else:
            merged.append(s)

    return merged
