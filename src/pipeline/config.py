"""Pipeline configuration: .env, language registry, dump discovery."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]      # src/pipeline/ → repo root
load_dotenv(ROOT / ".env")

DB_URL: str = os.environ.get(
    "DB_URL", "postgresql://postgres:postgres@localhost:5432/lingdb_dev"
)
DUMPS_DIR  = Path(os.environ.get("DUMPS_DIR",  str(ROOT / "dumps")))
STANZA_DIR = Path(os.environ.get("STANZA_DIR", str(ROOT / "stanza_resources")))

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "2000"))

# ── Concepts (Phase 2) ─────────────────────────────────────────
# Union-Find components larger than this are treated as homonym-bridged "giant
# components" (bridged through high-frequency polysemous words) and are NOT
# grounded in passes 1-2 — they are left for passes 3-4 (TF-IDF / LaBSE).
CONCEPT_COMPONENT_CAP = int(os.environ.get("CONCEPT_COMPONENT_CAP", "2000"))
# Pass 3: minimum TF-IDF cosine between source and candidate target sense glosses
# to accept a disambiguated edge. Cross-lingual pairs (no shared tokens) score ~0
# and fall below this → left for pass 4 (LaBSE).
CONCEPT_TFIDF_THRESHOLD = float(os.environ.get("CONCEPT_TFIDF_THRESHOLD", "0.50"))

# Embeddings (Phase 2, pass 4 — LaBSE attachment of the remainder).
# The proposal names LaBSE; on CPU it is very slow over millions of senses, so the
# default is the faster multilingual MiniLM (cross-lingual, ~480 MB). For the
# proposal model set EMBED_MODEL=sentence-transformers/LaBSE.
EMBED_MODEL = os.environ.get(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "256"))
# Cosine threshold to attach an ungrounded sense to the nearest concept (pass 4).
CONCEPT_SIM_THRESHOLD = float(os.environ.get("CONCEPT_SIM_THRESHOLD", "0.75"))

# Active languages (English first — it is rich in translations). See ORI_predlog.md §2.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "ru": "Russian",
}

# Dump file name (kaikki flat naming) → language code.
DUMP_NAME_TO_CODE: dict[str, str] = {
    "english": "en", "german": "de", "russian": "ru",
}

# Language code → lang_code as it appears in the dump, WHEN it differs (same for en/de/ru).
DUMP_LANG_CODE: dict[str, str] = {}


def dump_files(langs: list[str] | None = None) -> list[tuple[Path, str]]:
    """[(path, lang_code)] for the dumps of active languages in DUMPS_DIR."""
    want = set(langs) if langs else set(LANGUAGES)
    out: list[tuple[Path, str]] = []
    for p in sorted(DUMPS_DIR.glob("*.jsonl")):
        stem = p.stem.lower()
        code = stem.split("-")[0]
        if code not in LANGUAGES:
            code = DUMP_NAME_TO_CODE.get(stem, "")
        if code in LANGUAGES and code in want:
            out.append((p, code))
    return out
