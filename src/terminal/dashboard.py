"""
Dashboard — a reusable terminal progress display (Rich).
Each phase creates tasks (e.g. per language) and advances them.

    with Dashboard("Phase 1 — Import") as ui:
        ui.add_task("en", "en English", total=1_400_000)
        ui.advance("en", 2000)
        ui.task_done("en", 12_345, unit="records")

Two-tone bar: the "blue" zone = already done by a previous run (baseline, resume),
"green" = new in the current run. For indeterminate passes (total=None) only a
spinner spins. Degrades gracefully on a non-TTY.
"""
from __future__ import annotations

from datetime import timedelta
from time import monotonic

from rich.progress import (
    MofNCompleteColumn, Progress, ProgressColumn, SpinnerColumn,
    TextColumn, TimeElapsedColumn,
)
from rich.text import Text

from terminal.report import console as _console


class TwoToneBarColumn(ProgressColumn):
    """One bar, two zones: blue = done by a previous run (resume),
    green = new in the current run."""

    def __init__(self, width: int = 28) -> None:
        self.width = width
        super().__init__()

    def render(self, task) -> Text:
        w = self.width
        total = task.total or 0
        if total <= 0:                       # indeterminate (spinner only)
            return Text("─" * w, style="grey42")
        done = int(round(w * min(task.completed, total) / total))
        base = min(int(round(w * min(task.fields.get("baseline", 0) or 0, total) / total)), done)
        bar = Text()
        bar.append("━" * base, style="blue")               # done by a previous run (resume)
        bar.append("━" * (done - base), style="green")      # new in this run
        bar.append("━" * (w - done), style="grey42")        # remaining
        return bar


class EtaColumn(ProgressColumn):
    """Remaining time with a stable fallback: ETA = remaining / average speed
    measured from the first real advance (excluding idle setup time)."""

    def render(self, task) -> Text:
        style = "progress.remaining"
        if task.total is None:
            return Text("-:--:--", style=style)
        if task.finished:
            return Text("0:00:00", style=style)
        eta = self._eta(task)
        if eta is None:
            return Text("-:--:--", style=style)
        return Text(str(timedelta(seconds=int(eta))), style=style)

    @staticmethod
    def _eta(task) -> float | None:
        t0 = task.fields.get("t0")
        if t0 is None:                       # no advance yet
            return None
        dt = monotonic() - t0
        done = task.completed - (task.fields.get("c0") or 0)
        left = task.total - task.completed
        if dt <= 0 or done <= 0 or left <= 0:
            return None
        return left / (done / dt)            # remaining / (processing speed)


class Dashboard:
    def __init__(self, title: str = "") -> None:
        self.console = _console                  # shared with terminal.report
        self.title = title
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            TwoToneBarColumn(width=28),
            MofNCompleteColumn(),
            TextColumn("{task.fields[note]}"),
            TimeElapsedColumn(),
            EtaColumn(),
            console=self.console,
            refresh_per_second=8,
        )
        self._tasks: dict[str, int] = {}

    def __enter__(self) -> "Dashboard":
        if self.title:
            self.console.rule(f"[bold cyan]{self.title}")
        self.progress.start()
        return self

    def __exit__(self, *exc) -> None:
        self.progress.stop()

    def add_task(self, key: str, description: str, total: int | None = None,
                 *, baseline: int = 0) -> None:
        """total=None → indeterminate task (spinner spins).
        baseline → initial "already loaded" amount (blue), new progress is green."""
        self._tasks[key] = self.progress.add_task(
            description, total=total, completed=baseline, note="",
            baseline=baseline, t0=None, c0=baseline)

    def advance(self, key: str, n: int = 1) -> None:
        if key not in self._tasks:
            return
        tid = self._tasks[key]
        if self.progress.tasks[tid].fields.get("t0") is None:
            self.progress.update(tid, t0=monotonic(),
                                 c0=self.progress.tasks[tid].completed)
        self.progress.advance(tid, n)

    def note(self, key: str, text: str) -> None:
        if key in self._tasks:
            self.progress.update(self._tasks[key], note=text)

    def complete(self, key: str) -> None:
        if key in self._tasks:
            t = self.progress.tasks[self._tasks[key]]
            if t.total is not None:
                self.progress.update(self._tasks[key], completed=t.total)

    def finish(self, key: str, *, total: int | None = None, note: str | None = None) -> None:
        """Pin a task at 100% (for already-done / idempotent passes)."""
        if key not in self._tasks:
            return
        tid = self._tasks[key]
        upd: dict = {}
        if total is not None:
            upd["total"] = total
            upd["completed"] = total
        else:
            t = self.progress.tasks[tid]
            if t.total is not None:
                upd["completed"] = t.total
        if note is not None:
            upd["note"] = note
        self.progress.update(tid, **upd)

    def task_done(self, key: str, n: int | None = None, *, unit: str = "items") -> None:
        """Mark a per-item task complete with a uniform English 'done' note."""
        self.note(key, f"done: {n:,} {unit}" if n is not None else "done")
        self.complete(key)

    def task_failed(self, key: str, exc: object) -> None:
        """Flag a task as failed (red note) without completing its bar."""
        self.note(key, f"[red]error: {exc}[/red]")

    def log(self, msg: str) -> None:
        self.console.log(msg)


class InProcReporter:
    """A shim with a .put((key, delta, finished)) interface for single-process mode."""
    def __init__(self, ui: Dashboard) -> None:
        self.ui = ui

    def put(self, item) -> None:
        key, delta, _finished = item
        if delta:
            self.ui.advance(key, delta)
