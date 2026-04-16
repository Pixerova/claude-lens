"""
test_db_stats.py — Tests for M3/M4 additions to db.py:
  - get_session_stats()
  - get_week_total_cost()

These functions power the stats cards and pctOfWeek calculation.
"""

import pytest
from datetime import datetime, timezone, timedelta

from conftest import make_session
import db


# ── Helpers ───────────────────────────────────────────────────────────────────

def insert(isolated_db, **kwargs):
    """Insert a session using make_session defaults merged with kwargs.
    isolated_db must be passed so the fixture is active in the calling test."""
    s = make_session(**kwargs)
    db.upsert_session_summary(**s)
    return s


def today(isolated_db, **kwargs):
    return insert(isolated_db, started_offset_hours=0, **kwargs)


def yesterday(isolated_db, **kwargs):
    return insert(isolated_db, started_offset_hours=25, **kwargs)


def old(isolated_db, **kwargs):
    return insert(isolated_db, started_offset_hours=240, **kwargs)  # 10 days ago


# ── get_session_stats() ───────────────────────────────────────────────────────

class TestGetSessionStats:
    def test_empty_db_returns_zeros(self, isolated_db):
        stats = db.get_session_stats()
        assert stats["cost_today"]          == 0.0
        assert stats["cost_this_week"]      == 0.0
        assert stats["total_duration_sec"]  == 0
        assert stats["session_count"]       == 0
        assert stats["most_active_project"] is None

    def test_cost_today_includes_todays_sessions(self, isolated_db):
        today(isolated_db, session_id="s1", cost_usd=0.50)
        today(isolated_db, session_id="s2", cost_usd=0.30)
        stats = db.get_session_stats()
        assert abs(stats["cost_today"] - 0.80) < 1e-6

    def test_cost_today_excludes_yesterdays_sessions(self, isolated_db):
        today(isolated_db,     session_id="s1", cost_usd=0.50)
        yesterday(isolated_db, session_id="s2", cost_usd=1.00)
        stats = db.get_session_stats()
        assert abs(stats["cost_today"] - 0.50) < 1e-6

    def test_cost_this_week_includes_all_within_7_days(self, isolated_db):
        today(isolated_db,     session_id="s1", cost_usd=0.10)
        yesterday(isolated_db, session_id="s2", cost_usd=0.20)
        stats = db.get_session_stats()
        assert abs(stats["cost_this_week"] - 0.30) < 1e-6

    def test_cost_this_week_excludes_old_sessions(self, isolated_db):
        today(isolated_db, session_id="s1", cost_usd=0.10)
        old(isolated_db,   session_id="s2", cost_usd=5.00)
        stats = db.get_session_stats()
        assert abs(stats["cost_this_week"] - 0.10) < 1e-6

    def test_session_count_reflects_week_window(self, isolated_db):
        today(isolated_db,     session_id="s1")
        yesterday(isolated_db, session_id="s2")
        old(isolated_db,       session_id="s3")   # excluded
        stats = db.get_session_stats()
        assert stats["session_count"] == 2

    def test_total_duration_sums_within_week(self, isolated_db):
        today(isolated_db,     session_id="s1", duration_sec=1800)
        yesterday(isolated_db, session_id="s2", duration_sec=3600)
        old(isolated_db,       session_id="s3", duration_sec=9999)  # excluded
        stats = db.get_session_stats()
        assert stats["total_duration_sec"] == 5400

    def test_most_active_project_is_highest_cost(self, isolated_db):
        today(isolated_db, session_id="s1", project="alpha", cost_usd=0.10)
        today(isolated_db, session_id="s2", project="alpha", cost_usd=0.20)
        today(isolated_db, session_id="s3", project="beta",  cost_usd=0.50)
        stats = db.get_session_stats()
        assert stats["most_active_project"] == "beta"

    def test_most_active_project_ignores_null_project(self, isolated_db):
        today(isolated_db, session_id="s1", project=None,          cost_usd=9.99)
        today(isolated_db, session_id="s2", project="real-project", cost_usd=0.01)
        stats = db.get_session_stats()
        assert stats["most_active_project"] == "real-project"

    def test_most_active_project_none_when_all_projects_null(self, isolated_db):
        today(isolated_db, session_id="s1", project=None)
        stats = db.get_session_stats()
        assert stats["most_active_project"] is None

    def test_custom_days_window_respected(self, isolated_db):
        today(isolated_db,     session_id="s1", cost_usd=0.10)
        yesterday(isolated_db, session_id="s2", cost_usd=0.20)
        # days=1 — "yesterday" at 25h ago falls outside a 24-hour window
        stats = db.get_session_stats(days=1)
        assert stats["session_count"] == 1
        assert abs(stats["cost_this_week"] - 0.10) < 1e-6

    def test_return_types_are_correct(self, isolated_db):
        today(isolated_db, session_id="s1", cost_usd=0.05)
        stats = db.get_session_stats()
        assert isinstance(stats["cost_today"],         float)
        assert isinstance(stats["cost_this_week"],     float)
        assert isinstance(stats["total_duration_sec"], int)
        assert isinstance(stats["session_count"],      int)


# ── get_week_total_cost() ─────────────────────────────────────────────────────

class TestGetWeekTotalCost:
    def test_returns_zero_when_no_sessions(self, isolated_db):
        assert db.get_week_total_cost() == 0.0

    def test_sums_all_sessions_in_window(self, isolated_db):
        today(isolated_db,     session_id="s1", cost_usd=0.25)
        yesterday(isolated_db, session_id="s2", cost_usd=0.75)
        assert abs(db.get_week_total_cost() - 1.00) < 1e-6

    def test_excludes_sessions_older_than_window(self, isolated_db):
        today(isolated_db, session_id="s1", cost_usd=0.50)
        old(isolated_db,   session_id="s2", cost_usd=5.00)
        assert abs(db.get_week_total_cost() - 0.50) < 1e-6

    def test_custom_days_window(self, isolated_db):
        today(isolated_db,     session_id="s1", cost_usd=0.10)
        yesterday(isolated_db, session_id="s2", cost_usd=0.20)
        # 25h ago is outside a 1-day window
        assert abs(db.get_week_total_cost(days=1) - 0.10) < 1e-6

    def test_returns_float(self, isolated_db):
        today(isolated_db, session_id="s1", cost_usd=0.10)
        assert isinstance(db.get_week_total_cost(), float)

    def test_multiple_sources_combined(self, isolated_db):
        today(isolated_db, session_id="s1", source="code",   cost_usd=0.30)
        today(isolated_db, session_id="s2", source="cowork", cost_usd=0.20)
        assert abs(db.get_week_total_cost() - 0.50) < 1e-6
