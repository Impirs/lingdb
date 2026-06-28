"""
PlainDashboard — a plain-text progress renderer for non-TTY contexts
(Jupyter notebook, log capture). Same interface as terminal.dashboard.Dashboard,
but instead of a live Rich region it prints throttled, line-by-line updates that
capture and stream cleanly (no ANSI, no cursor moves).

Selected automatically when stdout is not a TTY, or via LINGDB_UI=plain
(see terminal.get_dashboard). It is intentionally not pretty — just correct and
comfortable to read in a notebook cell.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import timedelta

_MARKUP = re.compile(r"\[/?[a-zA-Z0-9 #]+\]")   # strip Rich markup like [red]…[/red]


def _plain(text: str) -> str:
    return _MARKUP.sub("", text)


class PlainDashboard:
    MIN_INTERVAL = 2.0          # seconds between progress lines per task
    PCT_STEP = 5                # …or print whenever the percentage moves this much

    def __init__(self, title: str = "") -> None:
        self.title = title
        self._t: dict[str, dict] = {}

    def __enter__(self) -> "PlainDashboard":
        if self.title:
            print(f"=== {self.title} ===", flush=True)
        return self

    def __exit__(self, *exc) -> None:
        return None

    def add_task(self, key: str, description: str, total: int | None = None,
                 *, baseline: int = 0) -> None:
        self._t[key] = dict(desc=description, total=total, completed=baseline,
                            last_t=0.0, last_pct=-1, note="", t0=time.monotonic())
        tot = f" (total {total:,})" if total else ""
        print(f"  {description}: start{tot}", flush=True)

    def _line(self, key: str, force: bool = False) -> None:
        t = self._t.get(key)
        if not t:
            return
        now = time.monotonic()
        if not force and now - t["last_t"] < self.MIN_INTERVAL:
            return
        c, tot = t["completed"], t["total"]
        elapsed = str(timedelta(seconds=int(now - t["t0"])))
        if tot:
            pct = int(100 * c / tot) if tot else 0
            if not force and abs(pct - t["last_pct"]) < self.PCT_STEP:
                return
            t["last_pct"] = pct
            msg = f"  {t['desc']}: {c:,} / {tot:,} ({pct:3d}%)  elapsed {elapsed}"
        else:
            msg = f"  {t['desc']}: {c:,}  elapsed {elapsed}"
        if t["note"]:
            msg += f"  — {t['note']}"
        t["last_t"] = now
        print(msg, flush=True)

    def advance(self, key: str, n: int = 1) -> None:
        t = self._t.get(key)
        if not t:
            return
        t["completed"] += n
        self._line(key)

    def note(self, key: str, text: str) -> None:
        t = self._t.get(key)
        if t:
            t["note"] = _plain(text)

    def complete(self, key: str) -> None:
        t = self._t.get(key)
        if t and t["total"] is not None:
            t["completed"] = t["total"]

    def finish(self, key: str, *, total: int | None = None, note: str | None = None) -> None:
        t = self._t.get(key)
        if not t:
            return
        if total is not None:
            t["total"] = total
            t["completed"] = total
        elif t["total"] is not None:
            t["completed"] = t["total"]
        if note is not None:
            t["note"] = _plain(note)
        self._line(key, force=True)

    def task_done(self, key: str, n: int | None = None, *, unit: str = "items") -> None:
        self.note(key, f"done: {n:,} {unit}" if n is not None else "done")
        self.complete(key)
        self._line(key, force=True)

    def task_failed(self, key: str, exc: object) -> None:
        self.note(key, f"error: {exc}")
        self._line(key, force=True)

    def log(self, msg: str) -> None:
        print(msg, flush=True)


class InProcReporter:
    """Shim with a .put((key, delta, finished)) interface for single-process mode."""
    def __init__(self, ui) -> None:
        self.ui = ui

    def put(self, item) -> None:
        key, delta, _finished = item
        if delta:
            self.ui.advance(key, delta)
