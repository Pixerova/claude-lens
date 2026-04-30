"""
test_db.py — Tests for db.py: schema, writers, readers, pruning, stats.
Every test uses the `isolated_db` fixture so it works against a fresh
in-memory-equivalent temp database, never ~/.claude-lens.
"""

import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

import db
from conftest import make_snapshot, make_session


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_init_creates_all_tables(self, isolated_db):
        conn = sqlite3.connect(isolated_db)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "plan_usage_snapshots" in tables
        assert "session_summaries" in tables
        assert "suggestion_history" in tables

    def test_init_creates_indexes(self, isolated_db):
        conn = sqlite3.connect(isolated_db)
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        conn.close()
        assert "idx_snapshots_time" in indexes
        assert "idx_sessions_start" in indexes
        assert "idx_sessions_source" in indexes

    def test_init_is_idempotent(self, isolated_db):
        """Calling init_db() twice should not raise or duplicate our tables."""
        db.init_db()
        db.init_db()
        conn = sqlite3.connect(isolated_db)
        # Filter to only our named tables (excludes sqlite_sequence etc.)
        our_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('plan_usage_snapshots','session_summaries','suggestion_history')"
            ).fetchall()
        }
        conn.close()
        assert our_tables == {"plan_usage_snapshots", "session_summaries", "suggestion_history"}


# ── Plan usage snapshots ──────────────────────────────────────────────────────

class TestPlanUsageSnapshots:
    def test_store_and_retrieve_snapshot(self, isolated_db):
        snap = make_snapshot(session_pct=0.21, weekly_pct=0.25)
        db.store_snapshot(**snap)

        row = db.get_latest_snapshot()
        assert row is not None
        assert abs(row["session_pct"] - 0.21) < 1e-6
        assert abs(row["weekly_pct"] - 0.25) < 1e-6

    def test_latest_snapshot_returns_most_recent(self, isolated_db):
        db.store_snapshot(**make_snapshot(session_pct=0.10, weekly_pct=0.10, offset_minutes=60))
        db.store_snapshot(**make_snapshot(session_pct=0.50, weekly_pct=0.50, offset_minutes=0))

        row = db.get_latest_snapshot()
        assert abs(row["session_pct"] - 0.50) < 1e-6

    def test_latest_snapshot_returns_none_when_empty(self, isolated_db):
        assert db.get_latest_snapshot() is None

    def test_snapshot_history_respects_days_filter(self, isolated_db):
        # Old snapshot (10 days ago) — should be excluded from 7-day query
        old = make_snapshot(session_pct=0.10, weekly_pct=0.10)
        old["session_resets"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        old["weekly_resets"]  = old["session_resets"]
        db.store_snapshot(**old)

        # Recent snapshot
        db.store_snapshot(**make_snapshot(session_pct=0.50, weekly_pct=0.50))

        # Manually backdate the old row so recorded_at is actually old
        conn = sqlite3.connect(isolated_db)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE plan_usage_snapshots SET recorded_at = ? WHERE session_pct = 0.10",
            (old_ts,),
        )
        conn.commit()
        conn.close()

        rows = db.get_snapshot_history(days=7)
        assert all(abs(r["session_pct"] - 0.50) < 1e-6 for r in rows)
        assert len(rows) == 1

    def test_snapshot_history_returns_chronological_order(self, isolated_db):
        for i in range(3):
            db.store_snapshot(**make_snapshot(session_pct=i * 0.1, weekly_pct=i * 0.1))
        rows = db.get_snapshot_history(days=7)
        times = [r["recorded_at"] for r in rows]
        assert times == sorted(times)


# ── Session summaries ─────────────────────────────────────────────────────────

class TestSessionSummaries:
    def test_upsert_inserts_new_session(self, isolated_db):
        db.upsert_session_summary(**make_session(session_id="s1"))
        rows = db.get_recent_sessions()
        assert len(rows) == 1
        assert rows[0]["session_id"] == "s1"

    def test_upsert_updates_existing_session(self, isolated_db):
        db.upsert_session_summary(**make_session(session_id="s1", cost_usd=0.10))
        db.upsert_session_summary(**make_session(session_id="s1", cost_usd=0.99))
        rows = db.get_recent_sessions()
        assert len(rows) == 1
        assert abs(rows[0]["cost_usd"] - 0.99) < 1e-6

    def test_get_recent_sessions_returns_newest_first(self, isolated_db):
        db.upsert_session_summary(**make_session(session_id="old", started_offset_hours=5))
        db.upsert_session_summary(**make_session(session_id="new", started_offset_hours=1))
        rows = db.get_recent_sessions()
        assert rows[0]["session_id"] == "new"
        assert rows[1]["session_id"] == "old"

    def test_get_recent_sessions_respects_limit(self, isolated_db):
        for i in range(10):
            db.upsert_session_summary(**make_session(session_id=f"s{i}", started_offset_hours=i))
        rows = db.get_recent_sessions(limit=3)
        assert len(rows) == 3

    def test_sessions_by_source_groups_correctly(self, isolated_db):
        db.upsert_session_summary(**make_session(session_id="c1", source="code",   cost_usd=0.10))
        db.upsert_session_summary(**make_session(session_id="c2", source="code",   cost_usd=0.20))
        db.upsert_session_summary(**make_session(session_id="w1", source="cowork", cost_usd=0.05))

        rows = db.get_sessions_by_source(days=7)
        by_source = {r["source"]: r for r in rows}

        assert by_source["code"]["session_count"] == 2
        assert abs(by_source["code"]["total_cost_usd"] - 0.30) < 1e-6
        assert by_source["cowork"]["session_count"] == 1

    def test_sessions_for_chart_groups_by_day_and_source(self, isolated_db):
        db.upsert_session_summary(**make_session(session_id="c1", source="code",   cost_usd=0.10))
        db.upsert_session_summary(**make_session(session_id="w1", source="cowork", cost_usd=0.05))

        rows = db.get_sessions_for_chart(days=7)
        sources = {r["source"] for r in rows}
        assert "code" in sources
        assert "cowork" in sources

    def test_session_source_constraint(self, isolated_db):
        """Only 'code' and 'cowork' are valid source values."""
        bad = make_session(session_id="bad", source="browser")
        with pytest.raises(Exception):
            db.upsert_session_summary(**bad)

    def test_session_fields_persisted_correctly(self, isolated_db):
        sess = make_session(
            session_id="full-sess",
            source="cowork",
            duration_sec=3600,
            model="claude-opus-4-6",
            project="infra-work",
            cost_usd=1.23,
        )
        db.upsert_session_summary(**sess)
        row = db.get_recent_sessions()[0]
        assert row["source"] == "cowork"
        assert row["duration_sec"] == 3600
        assert row["model"] == "claude-opus-4-6"
        assert row["project"] == "infra-work"
        assert abs(row["cost_usd"] - 1.23) < 1e-6


# ── Suggestion history ────────────────────────────────────────────────────────

class TestSuggestionHistory:
    def test_dismiss_suggestion(self, isolated_db):
        db.record_suggestion_shown("idle_window")
        db.record_suggestion_dismissed("idle_window")
        conn = sqlite3.connect(isolated_db)
        row = conn.execute(
            "SELECT dismissed_at FROM suggestion_history WHERE suggestion_id = ?",
            ("idle_window",),
        ).fetchone()
        conn.close()
        assert row[0] is not None

    def test_mark_suggestion_acted(self, isolated_db):
        db.record_suggestion_shown("end_of_week")
        db.record_suggestion_acted_on("end_of_week")
        conn = sqlite3.connect(isolated_db)
        row = conn.execute(
            "SELECT acted_on FROM suggestion_history WHERE suggestion_id = ?",
            ("end_of_week",),
        ).fetchone()
        conn.close()
        assert row[0] == 1


# ── Retention pruning ─────────────────────────────────────────────────────────

class TestRetentionPruning:
    def _backdate(self, db_path, table, ts_col, new_ts):
        conn = sqlite3.connect(db_path)
        conn.execute(f"UPDATE {table} SET {ts_col} = ?", (new_ts,))
        conn.commit()
        conn.close()

    def test_prune_removes_old_snapshots(self, isolated_db):
        db.store_snapshot(**make_snapshot())
        old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        self._backdate(isolated_db, "plan_usage_snapshots", "recorded_at", old_ts)

        result = db.prune_old_data(retention_days=30)
        assert result["snapshots"] == 1
        assert db.get_latest_snapshot() is None

    def test_prune_keeps_recent_snapshots(self, isolated_db):
        db.store_snapshot(**make_snapshot())
        result = db.prune_old_data(retention_days=30)
        assert result["snapshots"] == 0
        assert db.get_latest_snapshot() is not None

    def test_prune_removes_old_sessions(self, isolated_db):
        db.upsert_session_summary(**make_session(session_id="old-sess"))
        old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        self._backdate(isolated_db, "session_summaries", "started_at", old_ts)

        result = db.prune_old_data(retention_days=30)
        assert result["sessions"] == 1
        assert len(db.get_recent_sessions()) == 0

    def test_prune_keeps_suggestions_for_90_days(self, isolated_db):
        """Suggestions use a fixed 90-day retention regardless of the main setting."""
        db.record_suggestion_shown("test_rule")
        # Backdate to 45 days ago — should NOT be pruned (90-day window)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        self._backdate(isolated_db, "suggestion_history", "shown_at", old_ts)

        result = db.prune_old_data(retention_days=30)
        assert result["suggestions"] == 0

    def test_prune_returns_counts(self, isolated_db):
        result = db.prune_old_data(retention_days=30)
        assert "snapshots" in result
        assert "sessions" in result
        assert "suggestions" in result


# ── DB stats ──────────────────────────────────────────────────────────────────

class TestDbStats:
    def test_stats_returns_correct_counts(self, isolated_db):
        db.store_snapshot(**make_snapshot())
        db.upsert_session_summary(**make_session(session_id="s1"))
        db.upsert_session_summary(**make_session(session_id="s2"))
        db.record_suggestion_shown("rule")

        stats = db.get_db_stats()
        assert stats["snapshot_count"] == 1
        assert stats["session_count"] == 2
        assert stats["suggestion_count"] == 1

    def test_stats_on_empty_db(self, isolated_db):
        stats = db.get_db_stats()
        assert stats["snapshot_count"] == 0
        assert stats["session_count"] == 0
        assert stats["suggestion_count"] == 0

    def test_stats_includes_db_size(self, isolated_db):
        db.store_snapshot(**make_snapshot())
        stats = db.get_db_stats()
        assert stats["db_size_bytes"] > 0
