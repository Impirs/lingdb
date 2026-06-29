#!/usr/bin/env python
"""
lingdb — the SINGLE entry point of the pipeline.

Run (in venv, from the repo root):
    venv\\Scripts\\python src\\main.py --phase import --langs en de
    venv\\Scripts\\python src\\main.py --phase import --langs en --workers 1 --limit 5000   # slice check
    venv\\Scripts\\python src\\main.py --phase import morph
    venv\\Scripts\\python src\\main.py --phase all

Full CPU utilization comes from multiprocessing (separate processes bypass the GIL).

Phases (see ORI_predlog.md):
    import · morph   → Phase 1 (Čišćenje i morfološka analiza)
    concepts         → Phase 2 (Konstrukcija grafa koncepata)   [in progress]
    analytics        → Phase 3 (Analitika)                      [in progress]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Windows: torch (MKL/OpenMP) + faiss (OpenMP) → duplicate OpenMP runtimes can
# silently crash the process. The classic fix is to allow runtimes to coexist.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "8")

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PHASES = ["import", "morph", "concepts", "analytics"]


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="lingdb", description="lingdb pipeline orchestrator")
    ap.add_argument("--phase", nargs="+", default=["all"], metavar="PHASE",
                    help="phases: " + ", ".join(PHASES) + ", or 'all'")
    ap.add_argument("--langs", nargs="+", default=None, metavar="CODE",
                    help="language codes (default: all active — en de ru)")
    ap.add_argument("--workers", type=int, default=os.cpu_count(),
                    help="processes for CPU-bound phases (default: CPU count)")
    ap.add_argument("--limit", type=int, default=None,
                    help="row limit per dump (for slice verification)")
    ap.add_argument("--engine", choices=["tags", "auto", "neural"], default="auto",
                    help="Morphology: tags (dump tags only) | auto (tags + neural on remainder) "
                         "| neural (everything via Stanza/pymorphy3)")
    return ap.parse_args()


def run(phases: list[str], langs, workers: int, limit, engine: str) -> None:
    from terminal import report
    for ph in phases:
        if ph == "import":
            from pipeline import phase_import
            phase_import.run(langs=langs, workers=workers, limit=limit)
        elif ph == "morph":
            from pipeline import phase_morph
            phase_morph.run(langs=langs, workers=workers, engine=engine, limit=limit)
        elif ph == "concepts":
            from pipeline import phase_concepts
            phase_concepts.run(langs=langs, workers=workers)
        else:
            report.warn(f"phase '{ph}' is not implemented yet (in progress).")


def main() -> None:
    args = _parse_args()
    phases = PHASES if "all" in args.phase else [p for p in args.phase if p in PHASES]
    if not phases:
        raise SystemExit(f"Unknown phase(s). Allowed: {', '.join(PHASES)}, all")
    try:
        run(phases, args.langs, args.workers, args.limit, args.engine)
    except KeyboardInterrupt:
        from terminal import report
        report.warn("interrupted by user — committed batches are kept; "
                    "re-run the same command to resume where it stopped.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
