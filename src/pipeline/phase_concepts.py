"""
Phase 2 — Concept graph construction (ORI_predlog.md, Faza 2).

This module implements passes 1 + 2:
  • Pass 1 — direct translation edges (confidence 1.0): a sense in language A is
    linked to the senses of the word it translates to in language B. Targets are
    matched by (language, part of speech, normalized lemma). Matching within the
    same POS curbs homonym over-merging until pass 3 (TF-IDF) is in place.
  • Pass 2 — transitive closure via Union-Find (networkx.utils.UnionFind): if
    A↔B and B↔C, then A, B, C end up in the same concept.

Each connected component of senses = one concept. Components larger than
CONCEPT_COMPONENT_CAP are treated as homonym-bridged "giant components" and are
left unassigned for the later passes (TF-IDF / LaBSE), not grounded here.

Passes 3 (TF-IDF homonym resolution) and 4 (LaBSE attachment of the remainder)
are added in a later step.

The concept graph is rebuilt from scratch on each run (sense_concepts and
concepts are cleared first); incremental append-only attachment is future work.
"""
from __future__ import annotations

from collections import Counter

from pipeline.config import CONCEPT_COMPONENT_CAP
from pipeline.db import (
    get_conn, insert_many, insert_returning, load_language_ids,
    progress_set, run_finish, run_start,
)
from pipeline.phase_import import _norm

STEP = "concepts"


# ── Pure graph helper (testable without a DB) ─────────────────

def components_from_edges(edges):
    """[(a, b), …] → list of connected-component sets (size ≥ 2), via Union-Find."""
    from networkx.utils import UnionFind
    uf = UnionFind()
    for a, b in edges:
        uf.union(a, b)
    return [s for s in uf.to_sets() if len(s) >= 2]


# ── Data loading ──────────────────────────────────────────────

def _load_senses(conn):
    """sid → (language_id, pos_id, gloss, lang_code); and (lang, pos, lemma_norm) → [sid]."""
    info: dict[int, tuple] = {}
    index: dict[tuple, list[int]] = {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, w.language_id, w.pos_id, w.lemma_norm,
                   COALESCE(s.gloss, ''), l.code
            FROM senses s
            JOIN words w     ON w.id = s.word_id
            JOIN languages l ON l.id = w.language_id
            WHERE s.form_of_lemma IS NULL
        """)
        for sid, lang_id, pos_id, lemma_norm, gloss, code in cur:
            info[sid] = (lang_id, pos_id, gloss, code)
            index.setdefault((lang_id, pos_id, lemma_norm), []).append(sid)
    return info, index


def _translation_edges(conn, index, lang_ids):
    """Yield (src_sid, tgt_sid) edges: a sense → each sense of its translation target
    word in the target language, matched by (language, POS, normalized lemma)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT th.sense_id, w.pos_id, th.target_lang, th.target_word
            FROM translation_hints th
            JOIN senses s ON s.id = th.sense_id AND s.form_of_lemma IS NULL
            JOIN words  w ON w.id = s.word_id
        """)
        for src_sid, src_pos, tlang, tword in cur:
            tlid = lang_ids.get(tlang)
            if tlid is None:
                continue
            for tsid in index.get((tlid, src_pos, _norm(tword)), ()):  # same POS
                if tsid != src_sid:
                    yield (src_sid, tsid)


# ── Concept assembly ──────────────────────────────────────────

def _concept_fields(members, info):
    """(pos_id, gloss, gloss_en) for a concept from its member senses."""
    pos_id = Counter(info[m][1] for m in members).most_common(1)[0][0]
    gloss_en = next((info[m][2] for m in members if info[m][3] == "en" and info[m][2]), None)
    gloss = gloss_en or next((info[m][2] for m in members if info[m][2]), None)
    return pos_id, gloss, gloss_en


def run(langs=None, workers=None) -> None:
    from terminal import report

    with get_conn() as conn:
        run_id = run_start(conn, STEP, {"component_cap": CONCEPT_COMPONENT_CAP})
        report.rule("Phase 2 — Concept graph (passes 1+2: direct edges + Union-Find)")

        # Rebuild from scratch: clear the previous concept graph.
        with conn.cursor() as cur:
            cur.execute("TRUNCATE sense_concepts, concept_relations RESTART IDENTITY")
            cur.execute("DELETE FROM concepts")
            cur.execute("ALTER SEQUENCE concepts_id_seq RESTART WITH 1")
        conn.commit()

        report.step("Loading senses…")
        info, index = _load_senses(conn)
        lang_ids = load_language_ids(conn)
        report.info(f"{len(info):,} senses · {len(index):,} (lang, pos, lemma) keys")

        report.step("Pass 1 — building translation edges…")
        edges = list(_translation_edges(conn, index, lang_ids))
        report.info(f"{len(edges):,} direct translation edges")

        report.step("Pass 2 — Union-Find transitive closure…")
        components = components_from_edges(edges)

        # Assemble concepts (skip homonym-bridged giant components → later passes).
        concept_rows, comp_members, oversized, oversized_senses = [], [], 0, 0
        for comp in components:
            if len(comp) > CONCEPT_COMPONENT_CAP:
                oversized += 1
                oversized_senses += len(comp)
                continue
            members = list(comp)
            concept_rows.append(_concept_fields(members, info))
            comp_members.append(members)

        report.step(f"Creating {len(concept_rows):,} concepts…")
        concept_ids = insert_returning(conn, "concepts",
                                       ["pos_id", "gloss", "gloss_en"], concept_rows)
        sc_rows = [(sid, cid, 1.0, "direct", run_id)
                   for cid, members in zip(concept_ids, comp_members)
                   for sid in members]
        insert_many(conn, "sense_concepts",
                    ["sense_id", "concept_id", "confidence", "method", "run_id"], sc_rows)
        conn.commit()

        progress_set(conn, STEP, "all", status="done", processed=len(concept_ids))
        run_finish(conn, run_id)

    assigned = len(sc_rows)
    total = len(info)
    sizes = [len(m) for m in comp_members]
    report.summary(
        "Phase 2 — Concept graph complete",
        ["metric", "value"],
        [
            ("concepts (components ≥ 2)", f"{len(concept_ids):,}"),
            ("senses grounded", f"{assigned:,}"),
            ("senses total (real)", f"{total:,}"),
            ("coverage", f"{(100*assigned/total if total else 0):.1f}%"),
            ("largest concept (senses)", f"{max(sizes) if sizes else 0:,}"),
            ("avg concept size", f"{(assigned/len(sizes) if sizes else 0):.1f}"),
            (f"giant components (> {CONCEPT_COMPONENT_CAP}) left for passes 3-4",
             f"{oversized:,} ({oversized_senses:,} senses)"),
        ],
    )
