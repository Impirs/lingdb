"""
terminal.report — formatted, non-progress console output shared by all phases.

Every piece of human-facing terminal text (in English) lives in the `terminal`
package, not in the pipeline phases. Phases call these helpers instead of print(...).

  • Live per-item progress bars               → terminal.dashboard.Dashboard
  • Headers / notes / warnings / summaries     → this module
"""
from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence

from rich.console import Console
from rich.table import Table

try:                                  # Windows console → UTF-8 (Cyrillic, box glyphs)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

console = Console()


def rule(title: str) -> None:
    """Section header rule at the start of a phase."""
    console.rule(f"[bold cyan]{title}")


def info(msg: str) -> None:
    console.print(f"[dim]·[/dim] {msg}")


def step(msg: str) -> None:
    console.print(f"[cyan]▶[/cyan] {msg}")


def ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]![/yellow] {msg}")


def error(msg: str) -> None:
    console.print(f"[red]✗[/red] {msg}")


def summary(title: str, columns: Sequence[str], rows: Iterable[Sequence]) -> None:
    """Print a per-phase result table. First column left-aligned, rest right."""
    table = Table(title=title, title_style="bold green", header_style="bold",
                  title_justify="left")
    for i, col in enumerate(columns):
        table.add_column(col, justify="left" if i == 0 else "right")
    for row in rows:
        table.add_row(*(str(c) for c in row))
    console.print(table)
