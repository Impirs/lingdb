"""
Database access: connection, batch inserts (UNNEST), provenance (sources/runs),
resumability (pipeline_progress). Shared by all phases.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pipeline.config import DB_URL


# ── Connection ────────────────────────────────────────────────

def get_conn(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(DB_URL, autocommit=autocommit)


# ── Batch INSERT via UNNEST (returns ids in order) ───────────

def _pg_type(val: Any) -> str:
    if isinstance(val, (dict, list)):
        return "::jsonb[]"
    if isinstance(val, bool):
        return "::bool[]"
    if isinstance(val, int):
        return "::bigint[]"
    if isinstance(val, float):
        return "::real[]"
    return "::text[]"


def insert_returning(conn, table: str, columns: list[str], rows: list[tuple],
                     *, on_conflict: str = "") -> list[int]:
    """Bulk-insert *rows* and return their ids (in inserted order)."""
    if not rows:
        return []
    col_lists = [list(c) for c in zip(*rows)]
    sample = rows[0]
    unnest_args = ", ".join(f"%s{_pg_type(sample[i])}" for i in range(len(columns)))
    cols = ", ".join(columns)
    tcols = ", ".join(f"c{i}" for i in range(len(columns)))
    sql = (f"INSERT INTO {table} ({cols}) "
           f"SELECT {tcols} FROM UNNEST({unnest_args}) AS t({tcols}) "
           f"{on_conflict} RETURNING id")
    typed = []
    for i, lst in enumerate(col_lists):
        if isinstance(sample[i], (dict, list)):
            typed.append([json.dumps(v) for v in lst])
        else:
            typed.append(lst)
    with conn.cursor() as cur:
        cur.execute(sql, typed)
        return [r[0] for r in cur.fetchall()]


def _adapt(row: tuple) -> tuple:
    return tuple(Jsonb(v) if isinstance(v, (dict, list)) else v for v in row)


def insert_many(conn, table: str, columns: list[str], rows: list[tuple],
                *, on_conflict: str = "") -> None:
    """Bulk-insert without returning ids."""
    if not rows:
        return
    cols = ", ".join(columns)
    ph = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({ph}) {on_conflict}"
    with conn.cursor() as cur:
        cur.executemany(sql, [_adapt(r) for r in rows])


# ── Reference caches: language_id / pos_id ───────────────────

def load_language_ids(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM languages")
        return {code: lid for code, lid in cur.fetchall()}


def load_pos_ids(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM parts_of_speech")
        return {code: pid for code, pid in cur.fetchall()}


def load_relation_type_ids(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM relation_types")
        return {code: rid for code, rid in cur.fetchall()}


# ── Provenance: sources / pipeline_runs ──────────────────────

def source_get_or_create(conn, kind: str, name: str, version: str | None,
                         language_id: int | None = None,
                         license: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (kind, language_id, name, version, license) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (kind, name, version) DO UPDATE SET loaded_at = now() "
            "RETURNING id",
            (kind, language_id, name, version, license),
        )
        return cur.fetchone()[0]


def run_start(conn, step: str, params: dict | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (step, params) VALUES (%s,%s) RETURNING id",
            (step, Jsonb(params or {})),
        )
        rid = cur.fetchone()[0]
    conn.commit()
    return rid


def run_finish(conn, run_id: int, status: str = "done") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET status=%s, finished_at=now() WHERE id=%s",
            (status, run_id),
        )
    conn.commit()


def mark_run_cancelled(step: str, run_id: int | None,
                       pending_langs: Iterable[str] = ()) -> None:
    """Best-effort bookkeeping when a run is interrupted (Ctrl+C).

    Opens its own connection (the caller's may be unwound by the exception),
    marks in-flight languages as failed and the run as 'cancelled'. NEVER
    raises. Committed batches stay intact — the phase is resumable.
    """
    if run_id is None:
        return
    try:
        with get_conn() as conn:
            for lang in pending_langs:
                progress_set(conn, step, lang, status="failed",
                             error_msg="interrupted by user (SIGINT)")
            run_finish(conn, run_id, status="cancelled")
    except Exception:
        pass


# ── Resumability: pipeline_progress ──────────────────────────

def progress_get(conn, step: str, lang: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT status, processed, last_id FROM pipeline_progress "
            "WHERE step=%s AND language_code=%s", (step, lang))
        row = cur.fetchone()
    return row or {"status": "pending", "processed": 0, "last_id": 0}


def progress_set(conn, step: str, lang: str, *, status: str,
                 processed: int = 0, last_id: int = 0,
                 error_msg: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO pipeline_progress
                (step, language_code, status, processed, last_id, error_msg, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (step, language_code) DO UPDATE SET
                status=EXCLUDED.status, processed=EXCLUDED.processed,
                last_id=EXCLUDED.last_id, error_msg=EXCLUDED.error_msg,
                updated_at=now()
        """, (step, lang, status, processed, last_id, error_msg))
    conn.commit()


def progress_reset(conn, step: str, lang: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pipeline_progress WHERE step=%s AND language_code=%s",
                    (step, lang))
    conn.commit()
