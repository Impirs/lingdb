# lingdb

A tool for building a **local multilingual lexical database** from Wiktionary
dumps (kaikki.org) and constructing an **interlingual concept graph**.
Three languages: English (`en`), German (`de`), Russian (`ru`).

The full problem statement, methodology, and evaluation metrics are in
[ORI_predlog.md](ORI_predlog.md) (the approved project proposal).

> **Status:** Phase 1 (cleaning + morphology) is implemented and verified.
> Phases 2–3 (concept graph, analytics) are in progress (see [Roadmap](#roadmap)).

---

## What it is and why

Many NLP tasks (machine translation, cross-lingual search) need multilingual
dictionaries and concept databases. Paid solutions (BabelNet) are closed; open
ones (OMW) are small and purely semantic — without word forms, examples, or
transcriptions. Wiktionary contains all of that, but stores it as "dirty" JSONL
dumps. lingdb turns them into a clean, normalized database with a concept graph
and a translation API.

## Architecture: a 4-phase ETL pipeline

| Phase | What it does | Status |
|-------|--------------|:------:|
| **1. Cleaning + morphology** | streaming dump read → normalized `words`, `word_forms`, `senses`, `examples`, `translation_hints`, `lexical_relations`; strips wiki markup / stress / footnotes; POS tagging and lemmatization (Stanza + pymorphy3) | ✅ done |
| **2. Concept graph** | 4 passes of decreasing confidence: direct translation edges (1.0) → Union-Find transitive closure → TF-IDF gloss matching (0.85) → embedding attachment (0.70). Graph on NetworkX | ✅ passes 1–4 (`concepts` + `labse`) |
| **3. Analytics** | translation over the graph, synonym clusters, coverage, graph metrics | 🚧 in progress |
| **4. Storage** | everything in PostgreSQL (schema in [`src/db/`](src/db/)) | ✅ schema done |

The pipeline is **extensible**: adding a language = a row in `languages` + a dump;
no code changes, existing data is not recomputed.

## Repository layout

```
src/
  main.py            single entry point (phase orchestrator; multiprocessing)
  pipeline/          pipeline phases
    config.py        language registry, .env, dump discovery
    db.py            DB access: batch inserts (UNNEST), provenance, resumability
    phase_import.py  Phase 1a — import and cleaning
    phase_morph.py   Phase 1b — morphology (Stanza / pymorphy3)
    phase_concepts.py Phase 2 — concept graph (passes 1+2: direct edges + Union-Find)
    morph_tags.py    Wiktionary tags → UD features (fast path, no neural net)
  db/                DB schema (00_init.sql … 08_seed_reference.sql)
  terminal/          progress UI: Rich dashboard (TTY) + plain text (notebook); get_dashboard() picks
  tests/             tests
ORI_predlog.md       project proposal (methodology, evaluation)
requirements.txt     Python dependencies
.env.example         configuration template
lingdb.ipynb         defense/presentation notebook
```

---

## Installation

Requirements: **Python 3.14**, **PostgreSQL 18**.

```bash
# 1. Virtual environment and dependencies
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt

# 2. Configuration
cp .env.example .env          # edit DB_URL and DUMPS_DIR if needed

# 3. Place the kaikki.org dumps into DUMPS_DIR (from .env):
#    english.jsonl, german.jsonl, russian.jsonl

# 4. Create the database and apply the schema
createdb lingdb_dev
psql -d lingdb_dev -f src/db/00_init.sql
```

Stanza models (`en`, `de`) are downloaded automatically on the first run of
Phase 1b into `STANZA_DIR`.

## Running

```bash
# All of Phase 1 for all languages (import + morphology)
venv\Scripts\python src\main.py --phase import morph

# A slice check (5000 records per language, single process — handy for debugging)
venv\Scripts\python src\main.py --phase import morph --langs en --workers 1 --limit 5000

# Import only, German only
venv\Scripts\python src\main.py --phase import --langs de

# Phase 2 — build the concept graph (after Phase 1; rebuilds from current DB content)
venv\Scripts\python src\main.py --phase concepts

# Phase 2, pass 4 — LaBSE/MiniLM attachment of the remainder (separate, heavy; --limit to slice)
venv\Scripts\python src\main.py --phase labse

# Everything (once all phases are ready)
venv\Scripts\python src\main.py --phase all
```

### Command-line flags

| Flag | Meaning | Default |
|------|---------|---------|
| `--phase` | phases: `import`, `morph`, `concepts`, `labse`, `analytics`, or `all` | `all` |
| `--langs` | language codes (`en de ru`) | all active |
| `--workers` | processes for CPU-bound phases (multiprocessing) | CPU count |
| `--limit` | row limit per dump — for a slice check | no limit |
| `--engine` | morphology: `tags` (dump tags only) · `auto` (tags + neural on the remainder) · `neural` (everything via Stanza/pymorphy3) | `auto` |

**Resumability:** on interruption (Ctrl+C) committed batches are kept; re-running
the same command continues from where it stopped (`pipeline_progress`).

---

## Database

PostgreSQL 18. The schema is applied by a single file
[`src/db/00_init.sql`](src/db/00_init.sql), which pulls in the layers in
dependency order:

| File | Contents |
|------|----------|
| `01_extensions.sql` | extensions (pg_trgm, unaccent, btree_gin, fuzzystrmatch) |
| `02_reference.sql` | reference tables: `languages`, `parts_of_speech`, `relation_types` |
| `03_provenance.sql` | `sources`, `pipeline_runs`, `pipeline_progress`, `source_records` |
| `04_lexical.sql` | `words`, `word_forms`, `form_morphology` |
| `05_semantic.sql` | `concepts`, `senses`, `sense_concepts`, `examples` |
| `06_relations.sql` | `concept_relations`, `lexical_relations` |
| `07_serving.sql` | `translation_hints` (Phase 2 input) |
| `08_seed_reference.sql` | seeds: 3 languages, parts of speech, relation types |

All files are idempotent (`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`) — re-running
is safe.

---

## Data cleaning in Phase 1

The kaikki dumps are "dirty". Phase 1 cleans:
- **wiki markup** `[[…]]` from texts;
- **stress marks** in Russian (combining acute/grave `соба́ка` → `собака`) —
  otherwise lemmatization and translation matching break;
- **kaikki footnote markers** in forms (`вас^△`, `есмь^*`);
- **junk forms** with no letters (`?`, `—`);
- **deduplication** of words by the key `(language, part of speech, lemma)`.

---

## Roadmap

- [x] **Phase 1** — import, cleaning, morphology; DB schema; CLI orchestrator.
- [x] **Phase 2 (passes 1+2+3)** — concept graph: unambiguous direct edges (1.0) + Union-Find (NetworkX) + TF-IDF gloss disambiguation of ambiguous targets (0.85).
- [x] **Phase 2 (pass 4)** — embedding attachment of the remainder (0.70) via `--phase labse` (multilingual MiniLM by default; LaBSE configurable). Resumable.
- [ ] **Phase 2 incremental** — append-only attachment when adding a language (currently the graph is rebuilt from scratch).
- [ ] **Phase 3** — analytics: `translate_word()` over the graph, synonym clusters, metrics.
- [ ] **Evaluation** — coverage, comparison with MUSE and OMW (F1), the Swadesh list.
- [ ] **`lingdb.ipynb`** — defense notebook (function calls, tests, metrics).

## Technologies

Python 3.14 · PostgreSQL 18 · psycopg 3 · Stanza + pymorphy3 · NetworkX ·
scikit-learn (TF-IDF) · sentence-transformers (LaBSE) · Rich · tqdm
