"""
suggestions_schema.py — Shared schema constants for suggestions validation.

Imported by suggestions_loader and validate_suggestions to keep CUSTOM_PREFIX,
VALID_TRIGGERS, and REQUIRED_FIELDS in a single source of truth.
"""

CUSTOM_PREFIX = "custom_"
VALID_TRIGGERS = {"always", "low_utilization_eow", "post_reset"}
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
