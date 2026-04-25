"""
activity_monitor.py — File-system event handler that extends the poller's
active window when Claude session activity is detected outside working hours.

Scheduled on the same watchdog Observer as _SessionFileHandler in parser.py —
no extra threads or observers needed.
"""

import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler

log = logging.getLogger(__name__)


class ActivityMonitor(FileSystemEventHandler):
    """
    Extends the poller's active window when JSONL session activity is detected
    while the poller is sleeping (outside working hours, no extension in effect).

    Only post-end-of-day extension is supported — see UsagePoller.extend_active_window.
    Before the working-hours start time the app remains sleeping regardless of activity.
    """

    def __init__(self, poller):
        super().__init__()
        self._poller = poller

    def on_created(self, event):
        self._maybe_extend(event)

    def on_modified(self, event):
        self._maybe_extend(event)

    def _maybe_extend(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".jsonl" or path.name == "audit.jsonl":
            return
        if self._poller.is_sleeping:
            log.info(
                "Out-of-hours session activity detected (%s) — extending active window",
                path.name,
            )
            self._poller.extend_active_window()
