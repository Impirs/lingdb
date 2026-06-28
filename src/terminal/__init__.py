"""
terminal — progress UI selection.

get_dashboard() returns the right progress class for the context:
  • Rich live dashboard  → a real terminal (TTY)
  • PlainDashboard       → non-TTY (notebook / captured output), or LINGDB_UI=plain

Both expose the same interface, so the phases are agnostic to which one is used.
"""
from __future__ import annotations

import os
import sys


def get_dashboard():
    mode = os.environ.get("LINGDB_UI", "").lower()
    if mode not in ("rich", "plain"):
        try:
            tty = sys.stdout.isatty()
        except Exception:
            tty = False
        mode = "rich" if tty else "plain"
    if mode == "plain":
        from terminal.plain import PlainDashboard
        return PlainDashboard
    from terminal.dashboard import Dashboard
    return Dashboard


class InProcReporter:
    """UI-agnostic shim with a .put((key, delta, finished)) interface for
    single-process mode (the phase pushes progress straight into the dashboard)."""
    def __init__(self, ui) -> None:
        self.ui = ui

    def put(self, item) -> None:
        key, delta, _finished = item
        if delta:
            self.ui.advance(key, delta)
