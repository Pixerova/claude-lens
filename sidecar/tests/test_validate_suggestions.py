"""
test_validate_suggestions.py — Tests for validate_suggestions.py.

Run with:
    cd sidecar
    python -m pytest tests/test_validate_suggestions.py -v
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from validate_suggestions import validate_file, _check_entry


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "custom_suggestions.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def _valid_entry(**overrides) -> dict:
    base = {
        "id": "custom_testing001",
        "category": "custom_testing",
        "title": "My suggestion",
        "description": "Does something.",
        "prompt": "Do the thing in {{project}}.",
        "trigger": "always",
        "show_every_n_days": 7,
        "actions": ["copy_prompt"],
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# _check_entry unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckEntry:
    def test_valid_entry_returns_no_errors(self):
        assert _check_entry(_valid_entry(), 0) == []

    def test_not_a_mapping(self):
        errors = _check_entry("not a dict", 0)
        assert len(errors) == 1
        assert "not a mapping" in errors[0]

    def test_missing_required_fields(self):
        errors = _check_entry({"id": "custom_s001"}, 0)
        assert any("missing required fields" in e for e in errors)

    def test_id_missing_prefix(self):
        errors = _check_entry(_valid_entry(id="testing001"), 0)
        assert any("id must start with 'custom_'" in e for e in errors)

    def test_category_missing_prefix(self):
        errors = _check_entry(_valid_entry(category="testing"), 0)
        assert any("category must start with 'custom_'" in e for e in errors)

    def test_invalid_trigger(self):
        errors = _check_entry(_valid_entry(trigger="on_boredom"), 0)
        assert any("invalid trigger" in e for e in errors)

    def test_trigger_list_with_invalid_value(self):
        errors = _check_entry(_valid_entry(trigger=["always", "bogus"]), 0)
        assert any("invalid trigger" in e for e in errors)

    def test_trigger_list_all_valid(self):
        assert _check_entry(_valid_entry(trigger=["always"]), 0) == []

    def test_show_every_n_days_zero(self):
        errors = _check_entry(_valid_entry(show_every_n_days=0), 0)
        assert any("show_every_n_days" in e for e in errors)

    def test_show_every_n_days_negative(self):
        errors = _check_entry(_valid_entry(show_every_n_days=-1), 0)
        assert any("show_every_n_days" in e for e in errors)

    def test_show_every_n_days_string(self):
        errors = _check_entry(_valid_entry(show_every_n_days="7"), 0)
        assert any("show_every_n_days" in e for e in errors)

    def test_show_every_n_days_one_is_valid(self):
        assert _check_entry(_valid_entry(show_every_n_days=1), 0) == []

    def test_empty_actions_list(self):
        errors = _check_entry(_valid_entry(actions=[]), 0)
        assert any("actions" in e for e in errors)

    def test_actions_not_a_list(self):
        errors = _check_entry(_valid_entry(actions="copy_prompt"), 0)
        assert any("actions" in e for e in errors)

    def test_multiple_errors_reported_together(self):
        errors = _check_entry(
            _valid_entry(id="bad_id", category="bad_cat", trigger="nope"),
            0,
        )
        assert len(errors) >= 3


# ══════════════════════════════════════════════════════════════════════════════
# validate_file tests
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateFile:
    def test_valid_file_returns_ok(self, tmp_path):
        p = _write(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_testing001
                category: custom_testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        ok, errors, _ = validate_file(p)
        assert ok is True
        assert errors == []

    def test_empty_suggestions_list_is_valid(self, tmp_path):
        p = _write(tmp_path, "version: '1.0'\nsuggestions: []\n")
        ok, errors, _ = validate_file(p)
        assert ok is True
        assert errors == []

    def test_file_not_found(self, tmp_path):
        ok, errors, _ = validate_file(tmp_path / "nonexistent.yaml")
        assert ok is False
        assert any("File not found" in e for e in errors)

    def test_yaml_parse_error(self, tmp_path):
        p = tmp_path / "custom_suggestions.yaml"
        p.write_text("key: [unclosed\n  - bad\n")
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("parse error" in e for e in errors)

    def test_missing_suggestions_key(self, tmp_path):
        p = _write(tmp_path, "version: '1.0'\nother_key: []\n")
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert len(errors) > 0

    def test_suggestions_not_a_list_is_file_error(self, tmp_path):
        p = _write(tmp_path, "version: '1.0'\nsuggestions: 42\n")
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("must be a list" in e for e in errors)

    def test_id_missing_prefix_fails(self, tmp_path):
        p = _write(tmp_path, """
            version: "1.0"
            suggestions:
              - id: testing001
                category: custom_testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("id must start with 'custom_'" in e for e in errors)

    def test_category_missing_prefix_fails(self, tmp_path):
        p = _write(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_testing001
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("category must start with 'custom_'" in e for e in errors)

    def test_duplicate_ids_fail(self, tmp_path):
        p = _write(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_s001
                category: custom_testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
              - id: custom_s001
                category: custom_testing
                title: T2
                description: D2
                prompt: P2
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("duplicate id" in e for e in errors)

    def test_multiple_entries_first_valid_second_invalid(self, tmp_path):
        p = _write(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_good001
                category: custom_testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
              - id: bad_id
                category: custom_testing
                title: T2
                description: D2
                prompt: P2
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("bad_id" in e for e in errors)

    def test_invalid_trigger_fails(self, tmp_path):
        p = _write(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_s001
                category: custom_testing
                title: T
                description: D
                prompt: P
                trigger: on_boredom
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        ok, errors, _ = validate_file(p)
        assert ok is False
        assert any("invalid trigger" in e for e in errors)

    def test_all_valid_triggers_accepted(self, tmp_path):
        entries = "\n".join(
            textwrap.dedent(f"""
              - id: custom_s{i:03d}
                category: custom_testing
                title: T
                description: D
                prompt: P
                trigger: {trigger}
                show_every_n_days: 7
                actions: [copy_prompt]
            """)
            for i, trigger in enumerate(["always", "low_utilization_eow", "post_reset"])
        )
        p = _write(tmp_path, f"version: '1.0'\nsuggestions:\n{entries}")
        ok, errors, _ = validate_file(p)
        assert ok is True, errors
