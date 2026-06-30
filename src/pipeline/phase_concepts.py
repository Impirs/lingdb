"""
Phase 2 — Concept graph construction (ORI_predlog.md, Faza 2).

Implements passes 1 + 2 + 3 (pass 4 — LaBSE — runs separately, later):

  • Pass 1 — direct edges (confidence 1.0): a sense in language A is linked to the
    sense of the word it translates to in language B, ONLY when that target word is
    unambiguous (has exactly one sense). Matching is by (language, POS, normalized
    lemma). Restricting to single-sense targets avoids merging everything through
    high-frequency polysemous "hub" words (the giant-component problem).
  • Pass 2 — transitive closure via Union-Find (networkx.utils.UnionFind).
  • Pass 3 — TF-IDF homonym resolution (confidence 0.85): for AMBIGUOUS hints
    (target word has several senses) we pick the single target sense whose gloss is
    most similar (TF-IDF cosine ≥ CONCEPT_TFIDF_THRESHOLD) to the source sense gloss,
    and add that edge. Pairs with no gloss overlap (typically cross-lingual) score
    below threshold and are left for pass 4 (LaBSE).

Each connected component of senses (over pass-1 + pass-3 edges) = one concept.
Components larger than CONCEPT_COMPONENT_CAP are treated as homonym-bridged giant
components and left unassigned for pass 4. The graph is rebuilt from scratch on
each run; incremental append-only attachment is future work.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from pipeline.config import CONCEPT_COMPONENT_CAP, CONCEPT_TFIDF_THRESHOLD
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


def _hints(conn):
    """Yield (src_sid, src_pos, target_lang, target_word) for real source senses."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT th.sense_id, w.pos_id, th.target_lang, th.target_word
            FROM translation_hints th
            JOIN senses s ON s.id = th.sense_id AND s.form_of_lemma IS NULL
            JOIN words  w ON w.id = s.word_id
        """)
        yield from cur


# ── Pass 3: TF-IDF disambiguation of ambiguous hints ──────────

def _tfidf_edges(ambiguous, info, threshold):
    """ambiguous: {src_sid: set(candidate_target_sids)} where the target word is
    polysemous. Returns [(src_sid, best_target_sid)] for pairs whose source/target
    glosses are similar enough (TF-IDF cosine ≥ threshold)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    # Collect every sid that needs a gloss vector (sources + candidates with a gloss).
    needed = set()
    for src, cands in ambiguous.items():
        if info[src][2]:
            for t in cands:
                if info[t][2]:
                    needed.add(src)
                    needed.add(t)
    if not needed:
        return []
    sids = list(needed)
    row = {sid: i for i, sid in enumerate(sids)}
    vec = TfidfVectorizer(max_features=50000)
    X = vec.fit_transform(info[sid][2] for sid in sids)   # L2-normalized rows

    # Build candidate pairs (only where both have a gloss).
    src_rows, cand_rows, pair_src, pair_cand = [], [], [], []
    for src, cands in ambiguous.items():
        if not info[src][2]:
            continue
        for t in cands:
            if info[t][2]:
                src_rows.append(row[src]); cand_rows.append(row[t])
                pair_src.append(src); pair_cand.append(t)
    if not pair_src:
        return []
    # Cosine per pair = row dot product (rows already L2-normalized). Batched to
    # bound memory (the pair count can reach millions on full data).
    best: dict[int, tuple] = {}   # src_sid → (sim, target_sid)
    BATCH = 200_000
    for i in range(0, len(src_rows), BATCH):
        sr = src_rows[i:i + BATCH]; cr = cand_rows[i:i + BATCH]
        sims = np.asarray(X[sr].multiply(X[cr]).sum(axis=1)).ravel()
        for j, sim in enumerate(sims):
            if sim >= threshold:
                s = pair_src[i + j]
                if s not in best or sim > best[s][0]:
                    best[s] = (sim, pair_cand[i + j])
    return [(s, t) for s, (sim, t) in best.items()]


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
        run_id = run_start(conn, STEP, {"component_cap": CONCEPT_COMPONENT_CAP,
                                        "tfidf_threshold": CONCEPT_TFIDF_THRESHOLD})
        report.rule("Phase 2 — Concept graph (passes 1+2+3)")

        with conn.cursor() as cur:
            cur.execute("TRUNCATE sense_concepts, concept_relations RESTART IDENTITY")
            cur.execute("DELETE FROM concepts")
            cur.execute("ALTER SEQUENCE concepts_id_seq RESTART WITH 1")
        conn.commit()

        report.step("Loading senses…")
        info, index = _load_senses(conn)
        lang_ids = load_language_ids(conn)
        report.info(f"{len(info):,} senses · {len(index):,} (lang, pos, lemma) keys")

        report.step("Pass 1 — unambiguous direct edges; collecting ambiguous hints…")
        direct_edges = []
        ambiguous: dict[int, set] = defaultdict(set)
        for src_sid, src_pos, tlang, tword in _hints(conn):
            tlid = lang_ids.get(tlang)
            if tlid is None:
                continue
            targets = index.get((tlid, src_pos, _norm(tword)))
            if not targets:
                continue
            if len(targets) == 1:                       # unambiguous → pass 1
                if targets[0] != src_sid:
                    direct_edges.append((src_sid, targets[0]))
            else:                                       # ambiguous → pass 3
                ambiguous[src_sid].update(t for t in targets if t != src_sid)
        report.info(f"{len(direct_edges):,} direct edges · {len(ambiguous):,} ambiguous senses")

        report.step("Pass 3 — TF-IDF gloss disambiguation…")
        try:
            tfidf_edges = _tfidf_edges(ambiguous, info, CONCEPT_TFIDF_THRESHOLD)
            report.info(f"{len(tfidf_edges):,} disambiguated edges (cosine ≥ {CONCEPT_TFIDF_THRESHOLD})")
        except ImportError:
            tfidf_edges = []
            report.warn("scikit-learn not installed → pass 3 (TF-IDF) skipped; "
                        "concepts built from passes 1+2 only. "
                        "Run 'venv\\Scripts\\python -m pip install -r requirements.txt' to enable it.")

        report.step("Pass 2 — Union-Find over pass-1 + pass-3 edges…")
        direct_senses = {s for e in direct_edges for s in e}
        components = components_from_edges(direct_edges + tfidf_edges)

        # Assemble concepts (skip giant components → pass 4).
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
        sc_rows = []
        for cid, members in zip(concept_ids, comp_members):
            for sid in members:
                if sid in direct_senses:
                    sc_rows.append((sid, cid, 1.0, "direct", run_id))
                else:
                    sc_rows.append((sid, cid, 0.85, "tfidf", run_id))
        insert_many(conn, "sense_concepts",
                    ["sense_id", "concept_id", "confidence", "method", "run_id"], sc_rows)
        conn.commit()

        progress_set(conn, STEP, "all", status="done", processed=len(concept_ids))
        run_finish(conn, run_id)

    assigned = len(sc_rows)
    total = len(info)
    sizes = [len(m) for m in comp_members]
    n_tfidf = sum(1 for r in sc_rows if r[3] == "tfidf")
    report.summary(
        "Phase 2 — Concept graph complete",
        ["metric", "value"],
        [
            ("concepts", f"{len(concept_ids):,}"),
            ("senses grounded", f"{assigned:,}"),
            ("  · via pass 1 (direct, 1.0)", f"{assigned - n_tfidf:,}"),
            ("  · via pass 3 (tfidf, 0.85)", f"{n_tfidf:,}"),
            ("senses total (real)", f"{total:,}"),
            ("coverage", f"{(100*assigned/total if total else 0):.1f}%"),
            ("largest concept (senses)", f"{max(sizes) if sizes else 0:,}"),
            ("avg concept size", f"{(assigned/len(sizes) if sizes else 0):.1f}"),
            (f"giant components (> {CONCEPT_COMPONENT_CAP}) left for pass 4",
             f"{oversized:,} ({oversized_senses:,} senses)"),
        ],
    )
