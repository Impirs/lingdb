"""
Phase 1a — Import: JSONL dumps → words / word_forms / senses / examples /
translation_hints / lexical_relations / source_records.

• One process per language (multiprocessing) — for a real run.
• workers=1 → single-process mode (handy for verification / a --limit slice).
• Progress is drawn by terminal.Dashboard; resumability — pipeline_progress.

Dumps are read in a streaming fashion (line by line) since files are several GB.
Junk is filtered out (empty / wrong language), wiki tags ([[…]]) are stripped.
See ORI_predlog.md — Phase 1 (Čišćenje i morfološka analiza).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from queue import Empty

from pipeline.config import BATCH_SIZE, DUMP_LANG_CODE, LANGUAGES, dump_files
from pipeline.db import (
    get_conn, insert_many, insert_returning,
    load_language_ids, load_pos_ids, load_relation_type_ids,
    mark_run_cancelled, progress_set, run_finish, run_start, source_get_or_create,
)

STEP = "import"
REPORT_EVERY = 2000
STORE_RAW = os.environ.get("STORE_RAW", "0") == "1"   # source_records (raw material for reprocessing)

# Wiktionary relation field → relation_types.code (lexical-scope)
_REL_FIELDS = {
    "synonyms": "synonym", "antonyms": "antonym_lex", "derived": "derived",
    "related": "related", "coordinate_terms": "coordinate_term",
}

# kaikki pos → our parts_of_speech.code
_POS_MAP = {
    "noun": "noun", "verb": "verb", "adj": "adj", "adv": "adv", "pron": "pron",
    "det": "det", "article": "det", "prep": "adp", "postp": "adp", "conj": "conj",
    "intj": "intj", "num": "num", "particle": "part", "name": "propn",
    "phrase": "phrase", "proverb": "phrase", "prefix": "affix", "suffix": "affix",
    "infix": "affix", "character": "unknown", "symbol": "unknown",
}


def _norm(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "").casefold().strip()


# kaikki footnote marker in Russian forms: "вас^△", "меня́^△", "есмь^*", "еси^†"
# (caret + geometric triangle U+25B2..U+25BD or a footnote sign * † ‡ §). A caret
# immediately before such a sign never occurs in normal text → safe to remove.
_FOOTNOTE = re.compile(r"\^[*†‡§▲-▽]")


def _clean(s) -> str:
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    s = s.replace("[[", "").replace("]]", "")
    return _FOOTNOTE.sub("", s).strip()


# The Russian kaikki dump carries stress marks (combining acute U+0301 / grave
# U+0300): "бе́лка", "соба́ка". They break pymorphy3 lemmatization and translation
# matching in Phase 2. We strip them (part of "Čišćenje"), keeping the letter ё
# (precomposed U+0451, which is not a combining mark). See ORI_predlog.md — Phase 1.
_STRESS = {0x0300: None, 0x0301: None}   # combining grave / acute


def _destress(s: str) -> str:
    return unicodedata.normalize("NFC", s.translate(_STRESS)) if s else s


def _unit_type(raw_pos: str | None) -> str:
    p = (raw_pos or "").lower()
    if p == "proverb":
        return "proverb"
    if p == "phrase":
        return "phrase"
    return "word"


# Noun grammatical gender — taken from AUTHORITATIVE dump fields, NOT from the
# neural parse of forms (Stanza assigns junk Gender to diminutives). Sources:
#   1) top-level tags (de/ru): masculine/feminine/neuter;
#   2) fallback (de): the article on a nominative+singular form — der→Masc, das→Neut, die→Fem.
_GENDER_TAGS = {"masculine": "Masc", "feminine": "Fem", "neuter": "Neut"}
_ARTICLE_GENDER = {"der": "Masc", "die": "Fem", "das": "Neut"}


def _genders_from(tags) -> str | None:
    """Canonical gender encoding: Masc | Fem | Neut | Masc+Fem | None."""
    out: list[str] = []
    for t in tags or []:
        g = _GENDER_TAGS.get(str(t).lower())
        if g and g not in out:
            out.append(g)
    return ("+".join(out)) if out else None


def _extract_gender(obj: dict) -> str | None:
    g = _genders_from(obj.get("tags"))                       # 1) top level
    if g:
        return g
    for f in obj.get("forms") or []:                         # 2) article (de)
        if isinstance(f, dict) and {"nominative", "singular"} <= set(f.get("tags") or []):
            ag = _ARTICLE_GENDER.get((f.get("article") or "").lower())
            if ag:
                return ag
    return None


def _parse(obj: dict, lang_code: str = "") -> dict | None:
    ru = lang_code == "ru"                               # strip stress marks for Russian
    title = _clean(obj.get("word"))
    if ru:
        title = _destress(title)
    if not title:
        return None
    raw_pos = obj.get("pos")

    rels = []          # (code, target_lemma) — collected at top level AND sense level

    def _collect_rels(container, skip):
        for field, code in _REL_FIELDS.items():
            for r in container.get(field) or []:
                w = _clean(r.get("word") if isinstance(r, dict) else r)
                if ru:
                    w = _destress(w)
                if w and w != skip:
                    rels.append((code, w))

    senses = []
    for s in obj.get("senses") or []:
        gl = s.get("glosses") or s.get("raw_glosses") or []
        examples = []
        for e in s.get("examples") or []:
            txt = _clean(e.get("text") if isinstance(e, dict) else e)
            if txt:
                ref = _clean(e.get("ref")) if isinstance(e, dict) else ""
                examples.append((txt, ref or None))
        trans = []
        for t in s.get("translations") or []:
            lc = (t.get("lang_code") or "").lower()
            w = _clean(t.get("word"))
            if lc == "ru":
                w = _destress(w)
            if lc in LANGUAGES and w:
                trans.append((lc, w))
        # form_of / alt_of: the meaning is a word form ("plural of pie"), not semantics.
        # Keep the target lemma's lemma_norm → Phase 2 does not ground such meanings.
        fo = s.get("form_of") or s.get("alt_of") or []
        fo_first = fo[0] if fo else None
        fo_word = _clean(fo_first.get("word") if isinstance(fo_first, dict) else fo_first)
        _collect_rels(s, title)                          # sense-level relations (don't lose them)
        senses.append({"gloss": _clean(gl[0]) if gl else "", "ex": examples, "tr": trans,
                       "fo": _norm(fo_word) or None,
                       "tags": [t for t in (s.get("tags") or []) if isinstance(t, str)]})
    if not senses:
        senses = [{"gloss": "", "ex": [], "tr": [], "fo": None, "tags": []}]

    for t in obj.get("translations") or []:            # top-level → attach to sense[0]
        lc = (t.get("lang_code") or "").lower()
        w = _clean(t.get("word"))
        if lc == "ru":
            w = _destress(w)
        if lc in LANGUAGES and w:
            senses[0]["tr"].append((lc, w))

    _collect_rels(obj, title)                            # top-level relations

    forms = [(title, [])]
    for f in obj.get("forms") or []:
        if not isinstance(f, dict):
            continue
        fm = _clean(f.get("form"))
        if ru:
            fm = _destress(fm)
        # a form must contain at least one letter (drops junk like "?", "-", "—")
        if fm and fm != title and any(ch.isalpha() for ch in fm):
            forms.append((fm, f.get("tags") or []))

    raw = None
    if STORE_RAW:
        raw = {k: v for k, v in obj.items()
               if k not in ("senses", "forms", "translations", "synonyms",
                            "antonyms", "related", "derived", "coordinate_terms",
                            "hypernyms", "hyponyms", "meronyms", "holonyms",
                            "descendants", "etymology_templates", "head_templates")}

    pos_code = _POS_MAP.get((raw_pos or "").lower(), "unknown")
    return {
        "title": title,
        "pos_code": pos_code,
        "unit_type": _unit_type(raw_pos),
        "etym": (_clean(obj.get("etymology_text"))[:8000] or None),
        "gender": _extract_gender(obj) if pos_code == "noun" else None,
        "senses": senses, "forms": forms, "rels": rels, "raw": raw,
    }


def _flush(conn, recs, language_id, source_id, pos_ids, rel_ids, word_cache):
    unknown_pos = pos_ids.get("unknown")
    for r in recs:
        r["pos_id"] = pos_ids.get(r["pos_code"], unknown_pos)
        r["lemma_norm"] = _norm(r["title"])

    # 1. words (dedup via cache + ON CONFLICT)
    seen, new_rows = set(), []
    for r in recs:
        key = (r["pos_id"], r["title"])
        if key in word_cache or key in seen:
            continue
        seen.add(key)
        new_rows.append((language_id, r["pos_id"], r["unit_type"],
                         r["title"], r["lemma_norm"],
                         r["etym"], r.get("gender"), source_id))
    if new_rows:
        insert_many(conn, "words",
                    ["language_id", "pos_id", "unit_type", "lemma",
                     "lemma_norm", "etymology", "gender", "source_id"],
                    new_rows,
                    on_conflict="ON CONFLICT (language_id, pos_id, lemma) DO NOTHING")
    lemmas = list({r["title"] for r in recs})
    with conn.cursor() as cur:
        cur.execute("SELECT pos_id, lemma, id FROM words "
                    "WHERE language_id=%s AND lemma = ANY(%s)", (language_id, lemmas))
        for pid, lemma, wid in cur.fetchall():
            word_cache[(pid, lemma)] = wid

    # 2. source_records (optional)
    if STORE_RAW:
        sr = [(source_id, language_id, r["title"], r["raw"]) for r in recs if r["raw"] is not None]
        if sr:
            insert_many(conn, "source_records",
                        ["source_id", "language_id", "title", "raw"], sr)

    # 3. forms / senses / relations
    wf, sense_rows, sense_meta, rel_rows = [], [], [], []
    for r in recs:
        wid = word_cache.get((r["pos_id"], r["title"]))
        if wid is None:
            continue
        for form, tags in r["forms"]:
            wf.append((wid, form, _norm(form), tags))
        for idx, s in enumerate(r["senses"]):
            sense_rows.append((wid, idx, s["gloss"] or None, source_id, s.get("fo"),
                               s.get("tags") or []))
            sense_meta.append(s)
        for code, w in r["rels"]:
            rid = rel_ids.get(code)
            if rid:
                rel_rows.append((wid, None, w, rid, source_id))

    if wf:
        insert_many(conn, "word_forms", ["word_id", "form", "form_norm", "tags"], wf,
                    on_conflict="ON CONFLICT (word_id, form, tags) DO NOTHING")
    sense_ids = insert_returning(
        conn, "senses",
        ["word_id", "sense_index", "gloss", "source_id", "form_of_lemma", "tags"],
        sense_rows
    ) if sense_rows else []

    ex_rows, hint_rows = [], []
    for sid, s in zip(sense_ids, sense_meta):
        for txt, ref in s["ex"]:
            ex_rows.append((sid, txt, None, ref))
        for lc, w in s["tr"]:
            hint_rows.append((sid, lc, w))
    if ex_rows:
        insert_many(conn, "examples", ["sense_id", "text", "translation", "reference"], ex_rows)
    if hint_rows:
        insert_many(conn, "translation_hints", ["sense_id", "target_lang", "target_word"], hint_rows)
    if rel_rows:
        insert_many(conn, "lexical_relations",
                    ["from_word_id", "to_word_id", "to_lemma", "relation_type_id", "source_id"],
                    rel_rows)
    conn.commit()


def import_language(lang_code, dump_path, source_id, language_id,
                    pos_ids, rel_ids, limit, q, expected_lang=None):
    conn = get_conn()
    expected = (expected_lang or lang_code).lower()      # lang_code as it appears in the dump
    word_cache: dict[tuple, int] = {}
    buf, processed, skipped = [], 0, 0
    try:
        with open(dump_path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if limit and i >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if (obj.get("lang_code") or expected).lower() != expected:
                    skipped += 1
                    continue
                rec = _parse(obj, lang_code)
                if rec is None:
                    skipped += 1
                    continue
                buf.append(rec)
                processed += 1
                if len(buf) >= BATCH_SIZE:
                    _flush(conn, buf, language_id, source_id, pos_ids, rel_ids, word_cache)
                    buf = []
                if q is not None and processed % REPORT_EVERY == 0:
                    q.put((lang_code, REPORT_EVERY, False))
        if buf:
            _flush(conn, buf, language_id, source_id, pos_ids, rel_ids, word_cache)
        conn.commit()
    except KeyboardInterrupt:
        pass                       # Ctrl+C: stop promptly; committed batches stay
    finally:
        conn.close()
    if q is not None:
        q.put((lang_code, processed % REPORT_EVERY, True))
    return {"lang": lang_code, "processed": processed, "skipped": skipped}


def _count_lines(path: Path) -> int:
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def run(langs=None, workers=None, limit=None) -> None:
    from terminal import get_dashboard, InProcReporter, report
    Dashboard = get_dashboard()

    targets = dump_files(langs)
    if not targets:
        report.warn("Import: no dumps found (check DUMPS_DIR / language codes).")
        return
    workers = workers or min(len(targets), os.cpu_count() or 4)

    with get_conn() as conn:
        lang_ids = load_language_ids(conn)
        pos_ids = load_pos_ids(conn)
        rel_ids = load_relation_type_ids(conn)
        run_id = run_start(conn, STEP, {"langs": [c for _, c in targets], "limit": limit})
        source_ids = {c: source_get_or_create(conn, "wiktionary", p.name, None, lang_ids[c])
                      for p, c in targets}
        conn.commit()

    totals = {c: (limit if limit else _count_lines(p)) for p, c in targets}
    results: dict[str, dict] = {}

    with Dashboard("Phase 1 — Import") as ui:
        for p, c in targets:
            ui.add_task(c, f"{c} {LANGUAGES[c]}", total=totals[c])

        if workers <= 1:
            # single-process mode (verification / slice)
            rep = InProcReporter(ui)
            for p, c in targets:
                res = import_language(c, str(p), source_ids[c], lang_ids[c],
                                      pos_ids, rel_ids, limit, rep,
                                      DUMP_LANG_CODE.get(c, c))
                results[c] = res
                ui.task_done(c, res["processed"], unit="records")
        else:
            mgr = mp.Manager()
            q = mgr.Queue()
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(import_language, c, str(p), source_ids[c], lang_ids[c],
                                    pos_ids, rel_ids, limit, q,
                                    DUMP_LANG_CODE.get(c, c)): c
                        for p, c in targets}
                pending = dict(futs)
                try:
                    while pending:
                        try:
                            while True:
                                key, delta, _fin = q.get_nowait()
                                ui.advance(key, delta)
                        except Empty:
                            pass
                        for f in [f for f in pending if f.done()]:
                            c = pending.pop(f)
                            try:
                                results[c] = f.result()
                                ui.task_done(c, results[c]["processed"], unit="records")
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
        "Phase 1 — Import complete",
        ["language", "records", "skipped"],
        [(f"{c} {LANGUAGES[c]}", f"{res['processed']:,}", f"{res['skipped']:,}")
         for c, res in results.items()],
    )
