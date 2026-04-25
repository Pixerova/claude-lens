"""
test_suggestions.py — Unit tests for the suggestions engine.

Covers:
  - trigger_evaluator: always, low_utilization_eow (tiers), post_reset
  - suggestion_engine: trigger/cooldown/snooze filter, sort order, project resolution
  - suggestions_loader: schema validation, skip-with-warning behaviour
  - db: suggestion writer functions (shown, acted_on, dismissed, snoozed)
  - GET /suggestions endpoint (integration via TestClient)

Run with:
    cd sidecar
    python -m pytest tests/test_suggestions.py -v
"""

from __future__ import annotations

import sqlite3
import textwrap
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from conftest import make_session, make_snapshot

import db
import trigger_evaluator
import suggestion_engine as engine
from suggestions_loader import load_suggestions, _load_bundled, _load_custom


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

# Fixed UTC reference so every test that uses time mocking is deterministic.
FAKE_UTC = datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc)
FAKE_LOCAL = datetime(2026, 4, 20, 10, 0, 0)


def make_config(
    weekly_pct_below=0.50,
    hours_until_below=48,
    drop_threshold=0.30,
    window_hours=4,
    max_visible=5,
    enabled=True,
    tiers=None,
):
    """Build a minimal config dict for tests.

    By default creates a single-tier low_utilization_eow config from
    weekly_pct_below / hours_until_below.  Pass tiers=[...] explicitly to
    test multi-tier behaviour.
    """
    resolved_tiers = tiers if tiers is not None else [
        {"hoursUntilResetBelow": hours_until_below, "weeklyPctBelow": weekly_pct_below},
    ]
    return {
        "suggestions": {
            "enabled": enabled,
            "maxVisible": max_visible,
            "triggers": {
                "low_utilization_eow": {
                    "tiers": resolved_tiers,
                },
                "post_reset": {
                    "dropThreshold": drop_threshold,
                    "windowHours": window_hours,
                },
            },
        }
    }


def make_suggestion(
    id="s001",
    trigger="always",
    show_every_n_days=7,
    category="testing",
    actions=None,
    prompt="Work on {{project}}.",
):
    return {
        "id": id,
        "category": category,
        "title": f"Title {id}",
        "description": "Description.",
        "prompt": prompt,
        "trigger": trigger,
        "show_every_n_days": show_every_n_days,
        "actions": actions or ["copy_prompt"],
    }


class MockDatetime:
    """Patches trigger_evaluator.datetime to return FAKE_UTC / FAKE_LOCAL."""
    _fromisoformat = datetime.fromisoformat

    @staticmethod
    def now(tz=None):
        return FAKE_UTC if tz is not None else FAKE_LOCAL

    @staticmethod
    def fromisoformat(s):
        return MockDatetime._fromisoformat(s)


# ══════════════════════════════════════════════════════════════════════════════
# trigger_evaluator
# ══════════════════════════════════════════════════════════════════════════════


class TestLowUtilizationEOW:
    def _eval(self, weekly_pct, weekly_resets, config):
        with patch.object(trigger_evaluator, "datetime", MockDatetime):
            return trigger_evaluator.evaluate_triggers(
                weekly_pct=weekly_pct,
                weekly_resets=weekly_resets,
                prior_weekly_pct=None,
                prior_recorded_at=None,
                config=config,
            )

    def test_fires_when_both_conditions_met(self):
        config = make_config(weekly_pct_below=0.50, hours_until_below=48)
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        assert "low_utilization_eow" in self._eval(0.30, resets, config)

    def test_does_not_fire_when_pct_too_high(self):
        config = make_config(weekly_pct_below=0.50, hours_until_below=48)
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        assert "low_utilization_eow" not in self._eval(0.65, resets, config)

    def test_does_not_fire_when_reset_too_far(self):
        config = make_config(weekly_pct_below=0.50, hours_until_below=48)
        resets = (FAKE_UTC + timedelta(hours=100)).isoformat()
        assert "low_utilization_eow" not in self._eval(0.20, resets, config)

    def test_boundary_pct_exactly_at_threshold_excluded(self):
        """weekly_pct == threshold should NOT fire (condition is strictly <)."""
        config = make_config(weekly_pct_below=0.50, hours_until_below=48)
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        assert "low_utilization_eow" not in self._eval(0.50, resets, config)

    def test_fires_on_second_tier_when_first_does_not_match(self):
        """Two tiers: first requires 72 h / 70 %, second requires 48 h / 50 %.
        Usage is 60 % with 60 h to reset — first tier matches (pct < 70%, hours < 72)."""
        config = make_config(tiers=[
            {"hoursUntilResetBelow": 72, "weeklyPctBelow": 0.70},
            {"hoursUntilResetBelow": 48, "weeklyPctBelow": 0.50},
        ])
        resets = (FAKE_UTC + timedelta(hours=60)).isoformat()
        assert "low_utilization_eow" in self._eval(0.60, resets, config)

    def test_second_tier_fires_when_first_does_not(self):
        """Two tiers: 72 h / 70 % and 48 h / 50 %.
        Usage is 40 % with 24 h to reset — only second tier matches."""
        config = make_config(tiers=[
            {"hoursUntilResetBelow": 72, "weeklyPctBelow": 0.70},
            {"hoursUntilResetBelow": 48, "weeklyPctBelow": 0.50},
        ])
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        assert "low_utilization_eow" in self._eval(0.40, resets, config)

    def test_no_tier_matches_does_not_fire(self):
        """Two tiers; usage is too high for both — should not fire."""
        config = make_config(tiers=[
            {"hoursUntilResetBelow": 72, "weeklyPctBelow": 0.70},
            {"hoursUntilResetBelow": 48, "weeklyPctBelow": 0.50},
        ])
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        # pct=0.80 exceeds both weeklyPctBelow values
        assert "low_utilization_eow" not in self._eval(0.80, resets, config)

    def test_empty_tiers_does_not_fire(self):
        config = make_config(tiers=[])
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        assert "low_utilization_eow" not in self._eval(0.10, resets, config)


class TestPostReset:
    def _eval(self, weekly_pct, weekly_resets, prior_pct, prior_at, config):
        with patch.object(trigger_evaluator, "datetime", MockDatetime):
            return trigger_evaluator.evaluate_triggers(
                weekly_pct=weekly_pct,
                weekly_resets=weekly_resets,
                prior_weekly_pct=prior_pct,
                prior_recorded_at=prior_at,
                config=config,
            )

    def test_fires_on_large_drop_within_window(self):
        config = make_config(drop_threshold=0.30, window_hours=4)
        prior_at = (FAKE_UTC - timedelta(hours=2)).isoformat()
        result = self._eval(0.05, None, prior_pct=0.75, prior_at=prior_at, config=config)
        assert "post_reset" in result

    def test_does_not_fire_when_drop_small(self):
        config = make_config(drop_threshold=0.30, window_hours=4)
        prior_at = (FAKE_UTC - timedelta(hours=2)).isoformat()
        result = self._eval(0.60, None, prior_pct=0.70, prior_at=prior_at, config=config)
        assert "post_reset" not in result

    def test_does_not_fire_when_outside_window(self):
        config = make_config(drop_threshold=0.30, window_hours=4)
        prior_at = (FAKE_UTC - timedelta(hours=6)).isoformat()  # 6 h > 4 h window
        result = self._eval(0.05, None, prior_pct=0.80, prior_at=prior_at, config=config)
        assert "post_reset" not in result

    def test_does_not_fire_without_prior(self):
        config = make_config()
        result = self._eval(0.05, None, prior_pct=None, prior_at=None, config=config)
        assert "post_reset" not in result


class TestBuildTriggerContext:
    def test_context_shape_and_types(self):
        resets = (FAKE_UTC + timedelta(hours=24)).isoformat()
        ctx = trigger_evaluator.build_trigger_context(
            weekly_pct=0.28,
            weekly_resets=resets,
            active_triggers={"always", "low_utilization_eow"},
        )
        assert ctx["always"] is True
        assert ctx["low_utilization_eow"] is True
        assert ctx["post_reset"] is False
        assert 0.0 <= ctx["weekly_pct"] <= 1.0
        assert ctx["hours_until_reset"] >= 0


# ══════════════════════════════════════════════════════════════════════════════
# suggestion_engine
# ══════════════════════════════════════════════════════════════════════════════

class TestResolvePrompt:
    def test_substitutes_project(self):
        assert engine.resolve_prompt("Work on {{project}}.", "Maximizer") == "Work on Maximizer."

    def test_empty_string_when_no_project(self):
        assert engine.resolve_prompt("Work on {{project}}.", "") == "Work on ."

    def test_none_treated_as_empty(self):
        assert engine.resolve_prompt("Work on {{project}}.", None) == "Work on ."

    def test_no_template_unchanged(self):
        assert engine.resolve_prompt("Generic prompt.", "X") == "Generic prompt."


class TestCooldown:
    def test_never_shown_not_in_cooldown(self):
        s = make_suggestion(show_every_n_days=7)
        assert engine._in_cooldown(s, {}) is False

    def test_shown_yesterday_within_7day_window(self):
        s = make_suggestion(id="s1", show_every_n_days=7)
        yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        assert engine._in_cooldown(s, {"s1": {"shown_at": yesterday, "snoozed_until": None}}) is True

    def test_shown_8_days_ago_past_cooldown(self):
        s = make_suggestion(id="s1", show_every_n_days=7)
        old = (datetime.now(tz=timezone.utc) - timedelta(days=8)).isoformat()
        assert engine._in_cooldown(s, {"s1": {"shown_at": old, "snoozed_until": None}}) is False


class TestSnooze:
    def test_not_snoozed_when_no_history(self):
        assert engine._is_snoozed(make_suggestion(), {}) is False

    def test_snoozed_until_future(self):
        s = make_suggestion(id="s1")
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=2)).isoformat()
        assert engine._is_snoozed(s, {"s1": {"shown_at": None, "snoozed_until": future}}) is True

    def test_snooze_expired(self):
        s = make_suggestion(id="s1")
        past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        assert engine._is_snoozed(s, {"s1": {"shown_at": None, "snoozed_until": past}}) is False


class TestSortKey:
    def test_trigger_specific_before_always(self):
        low_s = make_suggestion(id="b", trigger="low_utilization_eow")
        always_s = make_suggestion(id="a", trigger="always")
        assert engine._sort_key(low_s, {}) < engine._sort_key(always_s, {})

    def test_never_shown_before_recently_shown(self):
        new_s = make_suggestion(id="new", trigger="always")
        old_s = make_suggestion(id="old", trigger="always")
        recent = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        assert engine._sort_key(new_s, {}) < engine._sort_key(
            old_s, {"old": {"shown_at": recent, "snoozed_until": None}}
        )

    def test_older_shown_before_newer_shown(self):
        a = make_suggestion(id="a", trigger="always")
        b = make_suggestion(id="b", trigger="always")
        older = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
        newer = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        hist = {
            "a": {"shown_at": older, "snoozed_until": None},
            "b": {"shown_at": newer, "snoozed_until": None},
        }
        assert engine._sort_key(a, hist) < engine._sort_key(b, hist)


class TestGetEligibleSuggestions:
    """Integration-style tests using the isolated_db fixture from conftest."""

    def test_filters_by_active_trigger(self, isolated_db):
        conn = db.get_connection()
        suggestions = [
            make_suggestion(id="a", trigger="always"),
            make_suggestion(id="b", trigger="low_utilization_eow"),
        ]
        result = engine.get_eligible_suggestions(
            suggestions, {"always"}, conn, make_config(), _project_override="P"
        )
        conn.close()
        ids = [s["id"] for s in result]
        assert "a" in ids
        assert "b" not in ids

    def test_filters_snoozed(self, isolated_db):
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=2)).isoformat()
        db.record_suggestion_shown("a")
        db.record_suggestion_snoozed("a", future)
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            [make_suggestion(id="a", trigger="always")],
            {"always"}, conn, make_config(), _project_override="P",
        )
        conn.close()
        assert len(result) == 0

    def test_filters_cooldown(self, isolated_db):
        db.record_suggestion_shown("a")
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            [make_suggestion(id="a", trigger="always", show_every_n_days=7)],
            {"always"}, conn, make_config(), _project_override="P",
        )
        conn.close()
        assert len(result) == 0

    def test_respects_max_visible(self, isolated_db):
        suggestions = [make_suggestion(id=f"s{i}", trigger="always") for i in range(10)]
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            suggestions, {"always"}, conn, make_config(max_visible=3), _project_override="P"
        )
        conn.close()
        assert len(result) <= 3

    def test_trigger_specific_before_always(self, isolated_db):
        suggestions = [
            make_suggestion(id="always_s", trigger="always"),
            make_suggestion(id="low_s",    trigger="low_utilization_eow"),
        ]
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            suggestions, {"always", "low_utilization_eow"}, conn, make_config(),
            _project_override="P",
        )
        conn.close()
        ids = [s["id"] for s in result]
        assert ids.index("low_s") < ids.index("always_s")

    def test_never_shown_before_old_shown(self, isolated_db):
        # "old" shown 5 days ago (past 1-day cooldown) — should still appear but after "new".
        db.record_suggestion_shown("old")
        # Backdate that row to 5 days ago
        five_days_ago = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
        conn_raw = sqlite3.connect(isolated_db)
        conn_raw.execute(
            "UPDATE suggestion_history SET shown_at = ? WHERE suggestion_id = 'old'",
            (five_days_ago,),
        )
        conn_raw.commit()
        conn_raw.close()

        suggestions = [
            make_suggestion(id="new", trigger="always", show_every_n_days=1),
            make_suggestion(id="old", trigger="always", show_every_n_days=1),
        ]
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            suggestions, {"always"}, conn, make_config(), _project_override="P"
        )
        conn.close()
        ids = [s["id"] for s in result]
        assert "new" in ids and "old" in ids
        assert ids.index("new") < ids.index("old")

    def test_resolves_project_from_db(self, isolated_db):
        now = datetime.now(tz=timezone.utc).isoformat()
        db.upsert_session_summary(**make_session(session_id="s1", project="MyProject"))
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            [make_suggestion(id="a", trigger="always")],
            {"always"}, conn, make_config(),
        )
        conn.close()
        assert len(result) == 1
        assert "MyProject" in result[0]["prompt"]
        assert "{{project}}" not in result[0]["prompt"]

    def test_empty_triggers_returns_empty(self, isolated_db):
        conn = db.get_connection()
        result = engine.get_eligible_suggestions(
            [make_suggestion(id="a", trigger="always")],
            set(), conn, make_config(), _project_override="P",
        )
        conn.close()
        assert len(result) == 0

    def test_empty_suggestions_returns_empty(self, isolated_db):
        conn = db.get_connection()
        result = engine.get_eligible_suggestions([], {"always"}, conn, make_config())
        conn.close()
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════════════════════
# db — suggestion writer functions
# ══════════════════════════════════════════════════════════════════════════════

class TestDbSuggestionWriters:
    def _row(self, isolated_db, suggestion_id: str):
        conn = sqlite3.connect(isolated_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM suggestion_history WHERE suggestion_id = ? "
            "ORDER BY shown_at DESC LIMIT 1",
            (suggestion_id,),
        ).fetchone()
        conn.close()
        return row

    def test_record_shown_inserts_row(self, isolated_db):
        db.record_suggestion_shown("testing001")
        row = self._row(isolated_db, "testing001")
        assert row is not None
        assert row["suggestion_id"] == "testing001"
        assert row["shown_at"] is not None
        assert row["acted_on"] == 0

    def test_record_shown_multiple_creates_multiple_rows(self, isolated_db):
        db.record_suggestion_shown("testing001")
        db.record_suggestion_shown("testing001")
        conn = sqlite3.connect(isolated_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM suggestion_history WHERE suggestion_id = 'testing001'"
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_record_acted_on(self, isolated_db):
        db.record_suggestion_shown("testing001")
        db.record_suggestion_acted_on("testing001")
        row = self._row(isolated_db, "testing001")
        assert row["acted_on"] == 1

    def test_record_dismissed(self, isolated_db):
        db.record_suggestion_shown("testing001")
        db.record_suggestion_dismissed("testing001")
        row = self._row(isolated_db, "testing001")
        assert row["dismissed_at"] is not None

    def test_record_snoozed_updates_existing_row(self, isolated_db):
        db.record_suggestion_shown("testing001")
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=4)).isoformat()
        db.record_suggestion_snoozed("testing001", future)
        row = self._row(isolated_db, "testing001")
        assert row["snoozed_until"] == future

    def test_record_snoozed_inserts_when_no_prior_shown(self, isolated_db):
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=4)).isoformat()
        db.record_suggestion_snoozed("testing002", future)
        row = self._row(isolated_db, "testing002")
        assert row is not None
        assert row["snoozed_until"] == future


# ══════════════════════════════════════════════════════════════════════════════
# suggestions_loader
# ══════════════════════════════════════════════════════════════════════════════

class TestSuggestionsLoader:
    def _write_bundled(self, tmp_path, content: str) -> Path:
        p = tmp_path / "suggestions.yaml"
        p.write_text(textwrap.dedent(content))
        return p

    def _write_custom(self, tmp_path, content: str) -> Path:
        p = tmp_path / "custom_suggestions.yaml"
        p.write_text(textwrap.dedent(content))
        return p

    # ── bundled loading ───────────────────────────────────────────────────────

    def test_loads_valid_bundled_entry(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: testing001
                category: testing
                title: "Audit test coverage"
                description: "Finds untested areas."
                prompt: "Look at {{project}}."
                trigger: always
                show_every_n_days: 7
                actions:
                  - copy_prompt
        """)
        results = load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent"))
        assert len(results) == 1
        assert results[0]["id"] == "testing001"
        assert results[0]["trigger"] == "always"

    def test_bundled_source_field_injected(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: testing001
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        results = load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent"))
        assert results[0]["source"] == "bundled"

    def test_list_trigger_normalised_to_scalar(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: s1
                category: testing
                title: "T"
                description: "D"
                prompt: "P"
                trigger:
                  - always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        results = load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent"))
        assert results[0]["trigger"] == "always"

    def test_skips_invalid_category(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: s1
                category: INVALID
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) == []

    def test_skips_invalid_trigger(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: s1
                category: testing
                title: T
                description: D
                prompt: P
                trigger: on_boredom
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) == []

    def test_skips_missing_required_fields(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: s1
                category: testing
                title: T
                # missing description, prompt, trigger, show_every_n_days, actions
        """)
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) == []

    def test_skips_duplicate_ids(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: dup
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
              - id: dup
                category: testing
                title: T2
                description: D2
                prompt: P2
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        results = load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent"))
        assert len(results) == 1

    def test_valid_and_invalid_mixed(self, tmp_path):
        p = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: good
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
              - id: bad
                category: NOPE
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        results = load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent"))
        assert len(results) == 1
        assert results[0]["id"] == "good"

    def test_empty_suggestions_list(self, tmp_path):
        p = self._write_bundled(tmp_path, "version: '1.0'\nsuggestions: []\n")
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) == []

    def test_returns_none_on_invalid_yaml(self, tmp_path):
        """A bundled YAML parse error returns None so the caller keeps its existing cache."""
        p = tmp_path / "suggestions.yaml"
        p.write_text("key: [unclosed bracket\n  - bad\n")
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) is None

    def test_loads_real_bundled_yaml(self):
        """The bundled sidecar/data/suggestions.yaml should parse without errors."""
        bundled = Path(__file__).parent.parent / "data" / "suggestions.yaml"
        results = load_suggestions(bundled_yaml_path=bundled, custom_yaml_path=Path("/nonexistent"))
        assert len(results) > 0
        for s in results:
            assert "id" in s
            assert "trigger" in s
            assert s["trigger"] in {"always", "low_utilization_eow", "post_reset"}
            assert s["source"] == "bundled"

    def test_bundled_rejects_custom_prefix_id(self, tmp_path):
        p = self._write_bundled(tmp_path, """
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
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) == []

    def test_bundled_rejects_custom_prefix_category(self, tmp_path):
        p = self._write_bundled(tmp_path, """
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
        assert load_suggestions(bundled_yaml_path=p, custom_yaml_path=Path("/nonexistent")) == []

    # ── custom loading ────────────────────────────────────────────────────────

    def test_loads_valid_custom_entry(self, tmp_path):
        p = self._write_custom(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_testing001
                category: custom_testing
                title: "My custom suggestion"
                description: "Does something useful."
                prompt: "Do the thing in {{project}}."
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        results = _load_custom(p)
        assert len(results) == 1
        assert results[0]["id"] == "custom_testing001"
        assert results[0]["source"] == "custom"

    def test_custom_source_field_injected(self, tmp_path):
        p = self._write_custom(tmp_path, """
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
        """)
        results = _load_custom(p)
        assert results[0]["source"] == "custom"

    def test_custom_rejects_missing_id_prefix(self, tmp_path):
        p = self._write_custom(tmp_path, """
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
        assert _load_custom(p) == []

    def test_custom_rejects_missing_category_prefix(self, tmp_path):
        p = self._write_custom(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_s001
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        assert _load_custom(p) == []

    # ── merge behaviour ───────────────────────────────────────────────────────

    def test_merge_bundled_and_custom(self, tmp_path):
        bundled = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: testing001
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        custom = self._write_custom(tmp_path, """
            version: "1.0"
            suggestions:
              - id: custom_testing001
                category: custom_testing
                title: CT
                description: CD
                prompt: CP
                trigger: always
                show_every_n_days: 3
                actions: [copy_prompt]
        """)
        results = load_suggestions(bundled_yaml_path=bundled, custom_yaml_path=custom)
        assert len(results) == 2
        ids = [s["id"] for s in results]
        assert "testing001" in ids
        assert "custom_testing001" in ids
        # bundled comes first
        assert results[0]["id"] == "testing001"

    def test_custom_without_prefix_is_dropped_by_load_custom(self, tmp_path):
        bundled = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: testing001
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        custom_p = tmp_path / "custom_suggestions.yaml"
        custom_p.write_text(textwrap.dedent("""
            version: "1.0"
            suggestions:
              - id: testing001
                category: custom_testing
                title: CT
                description: CD
                prompt: CP
                trigger: always
                show_every_n_days: 3
                actions: [copy_prompt]
        """))
        # The custom entry lacks the custom_ id prefix so _load_custom rejects it
        # at the require_custom_prefix validation step — never reaches the merge.
        # (The merge-level collision guard in load_suggestions is belt-and-suspenders:
        # custom_ prefix rules make a true id collision structurally impossible.)
        results = load_suggestions(bundled_yaml_path=bundled, custom_yaml_path=custom_p)
        assert len(results) == 1
        assert results[0]["source"] == "bundled"

    def test_custom_parse_error_falls_back_to_bundled_only(self, tmp_path):
        bundled = self._write_bundled(tmp_path, """
            version: "1.0"
            suggestions:
              - id: testing001
                category: testing
                title: T
                description: D
                prompt: P
                trigger: always
                show_every_n_days: 7
                actions: [copy_prompt]
        """)
        bad_custom = tmp_path / "custom_suggestions.yaml"
        bad_custom.write_text("key: [unclosed bracket\n  - bad\n")
        results = load_suggestions(bundled_yaml_path=bundled, custom_yaml_path=bad_custom)
        assert results is not None
        assert len(results) == 1
        assert results[0]["id"] == "testing001"


# ══════════════════════════════════════════════════════════════════════════════
# GET /suggestions — endpoint integration tests
# ══════════════════════════════════════════════════════════════════════════════

_BUNDLED_YAML = Path(__file__).parent.parent / "data" / "suggestions.yaml"


def _make_mock_poller(weekly_pct: float = 0.30) -> MagicMock:
    """Return a UsagePoller mock whose .run() coroutine completes immediately."""
    snapshot = MagicMock()
    snapshot.weekly_pct = weekly_pct
    snapshot.weekly_resets_at = "2099-01-01T00:00:00+00:00"
    snapshot.recorded_at = "2026-04-22T00:00:00+00:00"
    snapshot.is_stale = False
    snapshot.session_pct = 0.1

    poller = MagicMock()
    poller.current = snapshot
    poller.interval_sec = 300
    poller.run = AsyncMock()
    return poller



@contextmanager
def _suggestions_client(weekly_pct: float = 0.30, extra_patches=None):
    """Yield a TestClient with the standard sidecar startup mocks applied."""
    import main as _main
    poller = _make_mock_poller(weekly_pct=weekly_pct)
    patches = [
        patch("main.scan_all_sessions"),
        patch("main.start_watchers", return_value=MagicMock()),
        patch("main.UsagePoller", return_value=poller),
        patch("main.load_suggestions",
              side_effect=lambda: load_suggestions(
                  bundled_yaml_path=_BUNDLED_YAML,
                  custom_yaml_path=Path("/nonexistent"),
              )),
        *(extra_patches or []),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        with TestClient(_main.app) as client:
            yield _main, client


class TestSuggestionsEndpoint:
    """
    Integration tests for GET /suggestions via FastAPI TestClient.

    These run the full lifespan so they catch wiring bugs in main.py that
    unit tests of the engine/loader in isolation would miss — e.g. the
    missing `global _all_suggestions` declaration that caused the endpoint
    to always return an empty list even though startup logged 25 loaded.
    """

    def test_always_suggestions_returned(self, isolated_db):
        """Endpoint returns suggestions when always trigger is active."""
        with _suggestions_client(weekly_pct=0.30) as (_main, client):
            resp = client.get("/suggestions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["trigger_context"]["always"] is True
        assert len(data["suggestions"]) > 0, (
            "Expected always-trigger suggestions but got none — "
            "check that _all_suggestions is declared global in lifespan"
        )

    def test_suggestions_have_required_fields(self, isolated_db):
        """Each returned suggestion has the fields the frontend expects."""
        with _suggestions_client() as (_main, client):
            resp = client.get("/suggestions")

        for s in resp.json()["suggestions"]:
            assert "id" in s
            assert "category" in s
            assert "title" in s
            assert "description" in s
            assert "prompt" in s
            assert "trigger" in s
            assert "actions" in s

    def test_suggestions_disabled_returns_empty(self, isolated_db):
        """suggestions.enabled=false short-circuits the engine and returns []."""
        import main as _main
        disabled_config = {**_main.DEFAULT_CONFIG}
        disabled_config["suggestions"] = {**disabled_config["suggestions"], "enabled": False}

        with _suggestions_client(
            extra_patches=[patch("main.load_config", return_value=disabled_config)]
        ) as (_main, client):
            resp = client.get("/suggestions")

        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []

    def test_capped_at_max_visible(self, isolated_db):
        """Endpoint returns no more suggestions than maxVisible."""
        import main as _main
        config = {**_main.DEFAULT_CONFIG}
        config["suggestions"] = {**config["suggestions"], "maxVisible": 2}

        with _suggestions_client(
            extra_patches=[patch("main.load_config", return_value=config)]
        ) as (_main, client):
            resp = client.get("/suggestions")

        assert len(resp.json()["suggestions"]) <= 2
