"""
Phase 1b — Morphology: for each word form → form_morphology (upos, feats, lemma).

Skip optimization: lemma = owner word, upos = its POS, and UD features are derived
from the dump tags (morph_tags) — without a neural net. The neural parse (Stanza for
en/de; pymorphy3 for ru) runs ONLY on the remainder — forms without useful tags
(engine='auto'), or on everything (engine='neural'), or never (engine='tags').

One process per language (multiprocessing); resumability — forms that already have
form_morphology are skipped. See ORI_predlog.md — Phase 1.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from queue import Empty

from pipeline.config import LANGUAGES, STANZA_DIR
from pipeline.db import (
    get_conn, insert_many, load_language_ids, mark_run_cancelled,
    progress_set, run_finish, run_start,
)
from pipeline.morph_tags import tags_to_feats

STEP = "morph"
REPORT_EVERY = 2000
CHUNK = 20000
_CYR = re.compile(r"[Ѐ-ӿ]")


_stanza_cache: dict[str, object] = {}
_pymorphy = None


def _get_stanza(lang: str):
    if lang not in _stanza_cache:
        import stanza
        _stanza_cache.clear()  # one model per process — saves RAM
        _stanza_cache[lang] = stanza.Pipeline(
            lang=lang, processors="tokenize,pos,lemma",
            tokenize_pretokenized=True, model_dir=str(STANZA_DIR),
            logging_level="ERROR", use_gpu=False, download_method=None,
        )
    return _stanza_cache[lang]


def _get_pymorphy():
    global _pymorphy
    if _pymorphy is None:
        try:
            import pymorphy3 as pm
        except ImportError:
            import pymorphy2 as pm
        _pymorphy = pm.MorphAnalyzer()
    return _pymorphy


_OC_UPOS = {"NOUN": "NOUN", "VERB": "VERB", "INFN": "VERB", "ADJF": "ADJ", "ADJS": "ADJ",
            "ADVB": "ADV", "NPRO": "PRON", "PREP": "ADP", "CONJ": "CCONJ", "PRCL": "PART",
            "INTJ": "INTJ", "NUMR": "NUM", "PRTF": "ADJ", "PRTS": "ADJ", "GRND": "VERB",
            "COMP": "ADJ", "PRED": "ADV"}
_OC = {"nomn": ("Case", "Nom"), "gent": ("Case", "Gen"), "datv": ("Case", "Dat"),
       "accs": ("Case", "Acc"), "ablt": ("Case", "Ins"), "loct": ("Case", "Loc"),
       "sing": ("Number", "Sing"), "plur": ("Number", "Plur"),
       "masc": ("Gender", "Masc"), "femn": ("Gender", "Fem"), "neut": ("Gender", "Neut"),
       "past": ("Tense", "Past"), "pres": ("Tense", "Pres"), "futr": ("Tense", "Fut"),
       "1per": ("Person", "1"), "2per": ("Person", "2"), "3per": ("Person", "3"),
       "perf": ("Aspect", "Perf"), "impf": ("Aspect", "Imp"),
       "anim": ("Animacy", "Anim"), "inan": ("Animacy", "Inan")}


def _pymorphy_analyse(form: str):
    p = _get_pymorphy().parse(form)
    if not p:
        return form, "X", {}
    best = p[0]
    grams = set(str(best.tag).replace(" ", ",").split(","))
    feats = {k: v for g, (k, v) in _OC.items() if g in grams}
    return best.normal_form, _OC_UPOS.get(best.tag.POS or "", "X"), feats


def _stanza_analyse(lang: str, forms: list[str]):
    nlp = _get_stanza(lang)
    doc = nlp([[f] for f in forms])
    out = []
    for sent in doc.sentences:
        if sent.words:
            w = sent.words[0]
            feats = {}
            if w.feats and w.feats != "_":
                feats = dict(p.split("=", 1) for p in w.feats.split("|") if "=" in p)
            out.append((w.lemma or None, w.upos or "X", feats))
        else:
            out.append((None, "X", {}))
    return out


def morph_language(lang_code, language_id, engine, limit, q):
    conn = get_conn()
    processed, last_id = 0, 0
    total_left = limit
    pm_source = "pymorphy3" if lang_code == "ru" else "stanza"
    try:
        while True:
            rows = _fetch(conn, language_id, last_id, CHUNK if not limit else min(CHUNK, total_left or CHUNK))
            if not rows:
                break
            # neural candidates (engine-dependent)
            neural_idx = []
            for i, (wfid, form, tags, lemma, upos) in enumerate(rows):
                feats = tags_to_feats(tags)
                if engine == "neural" or (engine == "auto" and not feats and form != lemma):
                    neural_idx.append(i)
                rows[i] = (wfid, form, tags, lemma, upos, feats)

            neural_res = {}
            if engine != "tags" and neural_idx:
                try:
                    if lang_code == "ru":
                        for i in neural_idx:
                            wfid, form, *_ = rows[i]
                            if _CYR.search(form):
                                neural_res[i] = _pymorphy_analyse(form)
                    else:
                        forms = [rows[i][1] for i in neural_idx]
                        for i, res in zip(neural_idx, _stanza_analyse(lang_code, forms)):
                            neural_res[i] = res
                except Exception:
                    neural_res = {}   # neural engine unavailable → fall back to the dump-tag path

            out = []
            for i, (wfid, form, tags, lemma, upos, feats) in enumerate(rows):
                if i in neural_res:
                    nlemma, nupos, nfeats = neural_res[i]
                    out.append((wfid, nupos or upos or "X", nfeats or feats,
                                nlemma or lemma, pm_source))
                else:
                    out.append((wfid, upos or "X", feats, lemma, "dump"))
                last_id = wfid
            insert_many(conn, "form_morphology",
                        ["word_form_id", "upos", "feats", "lemma", "source"], out,
                        on_conflict="ON CONFLICT (word_form_id) DO NOTHING")
            conn.commit()
            processed += len(rows)
            if q is not None:
                q.put((lang_code, len(rows), False))
            if limit:
                total_left -= len(rows)
                if total_left <= 0:
                    break
    except KeyboardInterrupt:
        pass                       # Ctrl+C: stop promptly; committed chunks stay
    finally:
        conn.close()
    if q is not None:
        q.put((lang_code, 0, True))
    return {"lang": lang_code, "processed": processed}


def _fetch(conn, language_id, last_id, n):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT wf.id, wf.form, wf.tags, w.lemma, p.ud_upos
            FROM word_forms wf
            JOIN words w ON w.id = wf.word_id AND w.language_id = %s
            LEFT JOIN parts_of_speech p ON p.id = w.pos_id
            WHERE wf.id > %s
              AND NOT EXISTS (SELECT 1 FROM form_morphology m WHERE m.word_form_id = wf.id)
            ORDER BY wf.id LIMIT %s
        """, (language_id, last_id, n))
        return [list(r) for r in cur.fetchall()]


def _count(conn, language_id) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM word_forms wf JOIN words w ON w.id = wf.word_id
            WHERE w.language_id = %s
              AND NOT EXISTS (SELECT 1 FROM form_morphology m WHERE m.word_form_id = wf.id)
        """, (language_id,))
        return cur.fetchone()[0]


def run(langs=None, workers=None, engine="auto", limit=None) -> None:
    from terminal import get_dashboard, InProcReporter, report
    Dashboard = get_dashboard()

    targets = [c for c in (langs or LANGUAGES) if c in LANGUAGES]
    workers = workers or min(len(targets), os.cpu_count() or 4)

    with get_conn() as conn:
        lang_ids = load_language_ids(conn)
        run_id = run_start(conn, STEP, {"langs": targets, "engine": engine, "limit": limit})
        totals = {c: (limit or _count(conn, lang_ids[c])) for c in targets}

    results: dict[str, dict] = {}
    with Dashboard(f"Phase 1 — Morphology (engine={engine})") as ui:
        for c in targets:
            ui.add_task(c, f"{c} {LANGUAGES[c]}", total=totals[c])

        if workers <= 1:
            rep = InProcReporter(ui)
            for c in targets:
                results[c] = morph_language(c, lang_ids[c], engine, limit, rep)
                ui.task_done(c, results[c]["processed"], unit="forms")
        else:
            q = mp.Manager().Queue()
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(morph_language, c, lang_ids[c], engine, limit, q): c
                        for c in targets}
                pending = dict(futs)
                try:
                    while pending:
                        try:
                            while True:
                                key, delta, _ = q.get_nowait()
                                ui.advance(key, delta)
                        except Empty:
                            pass
                        for f in [f for f in pending if f.done()]:
                            c = pending.pop(f)
                            try:
                                results[c] = f.result()
                                ui.task_done(c, results[c]["processed"], unit="forms")
                            except Exception as exc:
                                ui.task_failed(c, exc)
                                with get_conn() as cc:
                                    progress_set(cc, STEP, c, status="failed", error_msg=str(exc))
                        time.sleep(0.05)
                except KeyboardInterrupt:
                    pool.shutdown(wait=False, cancel_futures=True)
                    mark_run_cancelled(STEP, run_id, pending.values())
                    raise

    with get_conn() as conn:
        for c, res in results.items():
            progress_set(conn, STEP, c, status="done", processed=res["processed"])
        run_finish(conn, run_id)

    report.summary(
        "Phase 1 — Morphology complete",
        ["language", "forms"],
        [(f"{c} {LANGUAGES[c]}", f"{res['processed']:,}") for c, res in results.items()],
    )
