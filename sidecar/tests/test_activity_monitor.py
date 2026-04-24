"""
test_activity_monitor.py — Tests for ActivityMonitor.

The monitor is a watchdog FileSystemEventHandler; we feed it fake events
rather than running a real observer.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from activity_monitor import ActivityMonitor


def _make_event(path: str, is_directory: bool = False):
    ev = MagicMock()
    ev.src_path = path
    ev.is_directory = is_directory
    return ev


def _make_poller(is_sleeping: bool = True):
    p = MagicMock()
    p.is_sleeping = is_sleeping
    return p


class TestActivityMonitor:

    def test_extends_when_sleeping_and_jsonl_modified(self):
        poller = _make_poller(is_sleeping=True)
        monitor = ActivityMonitor(poller)
        monitor.on_modified(_make_event("/home/user/.claude/projects/foo/session.jsonl"))
        poller.extend_active_window.assert_called_once()

    def test_extends_when_sleeping_and_jsonl_created(self):
        poller = _make_poller(is_sleeping=True)
        monitor = ActivityMonitor(poller)
        monitor.on_created(_make_event("/home/user/.claude/projects/foo/session.jsonl"))
        poller.extend_active_window.assert_called_once()

    def test_no_extension_when_awake(self):
        poller = _make_poller(is_sleeping=False)
        monitor = ActivityMonitor(poller)
        monitor.on_modified(_make_event("/home/user/.claude/projects/foo/session.jsonl"))
        poller.extend_active_window.assert_not_called()

    def test_ignores_directory_events(self):
        poller = _make_poller(is_sleeping=True)
        monitor = ActivityMonitor(poller)
        monitor.on_modified(_make_event("/home/user/.claude/projects/foo", is_directory=True))
        poller.extend_active_window.assert_not_called()

    def test_ignores_non_jsonl_files(self):
        poller = _make_poller(is_sleeping=True)
        monitor = ActivityMonitor(poller)
        for path in [
            "/home/user/.claude/projects/foo/session.txt",
            "/home/user/.claude/projects/foo/session.log",
            "/home/user/.claude/projects/foo/session",
        ]:
            monitor.on_modified(_make_event(path))
        poller.extend_active_window.assert_not_called()

    def test_ignores_audit_jsonl(self):
        poller = _make_poller(is_sleeping=True)
        monitor = ActivityMonitor(poller)
        monitor.on_modified(_make_event("/home/user/.claude/projects/foo/audit.jsonl"))
        poller.extend_active_window.assert_not_called()

    def test_extends_only_once_per_event_when_sleeping(self):
        poller = _make_poller(is_sleeping=True)
        monitor = ActivityMonitor(poller)
        monitor.on_modified(_make_event("/a/b/session1.jsonl"))
        monitor.on_modified(_make_event("/a/b/session2.jsonl"))
        assert poller.extend_active_window.call_count == 2
