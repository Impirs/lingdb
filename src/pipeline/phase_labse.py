"""
Phase 2 — pass 4: LaBSE embedding attachment (ORI_predlog.md, Faza 2, pass 4).

Runs SEPARATELY after the main concept build (passes 1-3). For senses still
ungrounded (no concept) after passes 1-3, it embeds the gloss with a multilingual
sentence model and attaches the sense to the nearest existing concept if the cosine
similarity is high enough (CONCEPT_SIM_THRESHOLD). Membership: method 'labse',
confidence 0.70.

Model: the proposal names LaBSE; the default is the faster multilingual MiniLM
(set EMBED_MODEL=sentence-transformers/LaBSE for the proposal model). On CPU this
is a long job over the full remainder — use --limit to process a slice for a check.

A concept's embedding is the embedding of its representative gloss (gloss_en or
gloss). The remainder is matched against all concept embeddings (cosine), and the
best match above the threshold wins.
"""
from __future__ import annotations

from pipeline.config import CONCEPT_SIM_THRESHOLD, EMBED_BATCH_SIZE, EMBED_MODEL
from pipeline.db import (
    get_conn, insert_many, progress_set, run_finish, run_start,
)

STEP = "labse"


def _load_concept_embeddings(conn, model):
    """Return (concept_ids ndarray, normalized concept embedding matrix)."""
    import numpy as np
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, COALESCE(gloss_en, gloss)
            FROM concepts
            WHERE COALESCE(gloss_en, gloss) IS NOT NULL AND COALESCE(gloss_en, gloss) <> ''
        """)
        rows = cur.fetchall()
    ids = np.array([r[0] for r in rows], dtype="int64")
    emb = model.encode([r[1] for r in rows], batch_size=EMBED_BATCH_SIZE,
                       normalize_embeddings=True, show_progress_bar=False)
    return ids, np.asarray(emb, dtype="float32")


def _fetch_ungrounded(conn, last_id, n):
    """Senses without a concept (and with a gloss), ordered by id for resumability."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.gloss
            FROM senses s
            WHERE s.form_of_lemma IS NULL
              AND s.gloss IS NOT NULL AND s.gloss <> ''
              AND s.id > %s
              AND NOT EXISTS (SELECT 1 FROM sense_concepts sc WHERE sc.sense_id = s.id)
            ORDER BY s.id
            LIMIT %s
        """, (last_id, n))
        return cur.fetchall()


def _count_ungrounded(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM senses s
            WHERE s.form_of_lemma IS NULL AND s.gloss IS NOT NULL AND s.gloss <> ''
              AND NOT EXISTS (SELECT 1 FROM sense_concepts sc WHERE sc.sense_id = s.id)
        """)
        return cur.fetchone()[0]


def run(langs=None, workers=None, limit=None) -> None:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from terminal import get_dashboard, report
    Dashboard = get_dashboard()

    report.rule(f"Phase 2 — Pass 4 (embedding attachment · {EMBED_MODEL})")
    report.step("Loading model…")
    model = SentenceTransformer(EMBED_MODEL, device="cpu")

    with get_conn() as conn:
        run_id = run_start(conn, STEP, {"model": EMBED_MODEL,
                                        "threshold": CONCEPT_SIM_THRESHOLD, "limit": limit})
        report.step("Embedding concept glosses (building the index)…")
        concept_ids, C = _load_concept_embeddings(conn, model)
        report.info(f"{len(concept_ids):,} concepts indexed (dim {C.shape[1] if len(C) else 0})")

        total = _count_ungrounded(conn)
        target = min(total, limit) if limit else total
        report.info(f"{total:,} ungrounded senses with a gloss"
                    + (f"; processing {target:,} (--limit)" if limit else ""))

        attached, processed, last_id = 0, 0, 0
        CHUNK = 5000
        with Dashboard("Phase 2 — Pass 4 (embedding attachment)") as ui:
            ui.add_task("emb", f"{EMBED_MODEL.split('/')[-1]}", total=target)
            while processed < target:
                rows = _fetch_ungrounded(conn, last_id, min(CHUNK, target - processed))
                if not rows:
                    break
                ids = [r[0] for r in rows]
                S = np.asarray(model.encode([r[1] for r in rows], batch_size=EMBED_BATCH_SIZE,
                                            normalize_embeddings=True, show_progress_bar=False),
                               dtype="float32")
                sims = S @ C.T                      # (b × n_concepts) cosine (rows normalized)
                best = sims.argmax(axis=1)
                best_sim = sims[np.arange(len(ids)), best]
                out = [(ids[i], int(concept_ids[best[i]]), 0.70, "labse", run_id)
                       for i in range(len(ids)) if best_sim[i] >= CONCEPT_SIM_THRESHOLD]
                if out:
                    insert_many(conn, "sense_concepts",
                                ["sense_id", "concept_id", "confidence", "method", "run_id"],
                                out, on_conflict="ON CONFLICT (sense_id, concept_id) DO NOTHING")
                    conn.commit()
                    attached += len(out)
                processed += len(rows)
                last_id = ids[-1]
                ui.advance("emb", len(rows))
            ui.task_done("emb", processed, unit="senses")

        progress_set(conn, STEP, "all", status="done", processed=attached)
        run_finish(conn, run_id)

    report.summary(
        "Phase 2 — Pass 4 complete",
        ["metric", "value"],
        [
            ("model", EMBED_MODEL),
            ("cosine threshold", f"{CONCEPT_SIM_THRESHOLD}"),
            ("ungrounded senses processed", f"{processed:,}"),
            ("attached to a concept (labse, 0.70)", f"{attached:,}"),
            ("attach rate", f"{(100*attached/processed if processed else 0):.1f}%"),
        ],
    )
