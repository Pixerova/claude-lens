"""
validate_suggestions.py — Validator for custom suggestions YAML files.

Checks that all entries conform to the custom suggestion conventions:
  • id and category must start with 'custom_'
  • All required fields must be present
  • trigger must be a recognised value
  • show_every_n_days must be an integer ≥ 1
  • actions must be a non-empty list
  • No duplicate ids within the file

Usage:
    python validate_suggestions.py [path/to/custom_suggestions.yaml]

If no path is given, validates ~/.claudelens/custom_suggestions.yaml.

Exit codes:
    0  All entries are valid (or the file has no entries).
    1  One or more entries failed validation.
    2  File not found or YAML parse error.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from suggestions_schema import CUSTOM_PREFIX, VALID_TRIGGERS, REQUIRED_FIELDS

_DEFAULT_PATH = Path.home() / ".claudelens" / "custom_suggestions.yaml"


def _check_entry(entry: Any, index: int) -> list[str]:
    """Return a list of error strings for this entry (empty list = valid)."""
    errors: list[str] = []

    if not isinstance(entry, dict):
        return [f"Entry #{index}: not a mapping"]

    entry_id = entry.get("id", "<missing>")
    label = f"Entry #{index} (id={entry_id!r})"

    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        errors.append(f"{label}: missing required fields: {', '.join(sorted(missing))}")

    if "id" in entry:
        if not str(entry["id"]).startswith(CUSTOM_PREFIX):
            errors.append(
                f"{label}: id must start with 'custom_' (got {entry['id']!r})"
            )

    if "category" in entry:
        if not str(entry["category"]).startswith(CUSTOM_PREFIX):
            errors.append(
                f"{label}: category must start with 'custom_' (got {entry['category']!r})"
            )

    if "trigger" in entry:
        raw = entry["trigger"]
        triggers = raw if isinstance(raw, list) else [raw]
        bad = set(triggers) - VALID_TRIGGERS
        if bad:
            errors.append(
                f"{label}: invalid trigger(s): {', '.join(sorted(bad))}. "
                f"Must be one of: {', '.join(sorted(VALID_TRIGGERS))}"
            )

    if "show_every_n_days" in entry:
        n = entry["show_every_n_days"]
        if not isinstance(n, int) or n < 1:
            errors.append(
                f"{label}: show_every_n_days must be an integer ≥ 1 (got {n!r})"
            )

    if "actions" in entry:
        a = entry["actions"]
        if not isinstance(a, list) or len(a) == 0:
            errors.append(f"{label}: actions must be a non-empty list")

    return errors


def validate_file(path: Path) -> tuple[bool, list[str], int]:
    """Validate a custom suggestions YAML file.

    Returns (ok, errors, count). ok is True when all entries pass validation.
    count is the number of entries in the file (0 on file-level errors).
    Errors starting with 'File not found' or containing 'parse error' indicate
    a file-level problem rather than entry-level validation failures.
    """
    if not path.exists():
        return False, [f"File not found: {path}"], 0

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return False, [f"YAML parse error: {exc}"], 0

    if not isinstance(raw, dict) or "suggestions" not in raw:
        return False, [
            "Unexpected file structure — expected a 'suggestions' key at the top level"
        ], 0

    entries = raw.get("suggestions")
    if not isinstance(entries, list):
        return False, ["'suggestions' must be a list"], 0

    if len(entries) == 0:
        return True, [], 0

    all_errors: list[str] = []
    seen_ids: set[str] = set()

    for i, entry in enumerate(entries):
        all_errors.extend(_check_entry(entry, i))

        if isinstance(entry, dict) and "id" in entry:
            sid = str(entry["id"])
            if sid in seen_ids:
                all_errors.append(f"Entry #{i} (id={sid!r}): duplicate id")
            seen_ids.add(sid)

    return len(all_errors) == 0, all_errors, len(entries)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_PATH

    print(f"Validating: {path}")
    ok, errors, count = validate_file(path)

    if ok:
        print(f"  {count} {'entry' if count == 1 else 'entries'}, all valid.")
        return 0

    is_file_error = any(
        "File not found" in e
        or "parse error" in e
        or "Unexpected file structure" in e
        or "must be a list" in e
        for e in errors
    )

    for e in errors:
        print(f"  error: {e}")

    if not is_file_error:
        n = len(errors)
        print(f"\n{n} validation error{'s' if n != 1 else ''} found.")

    return 2 if is_file_error else 1


if __name__ == "__main__":
    sys.exit(main())
