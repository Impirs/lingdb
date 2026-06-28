-- ============================================================
-- 02_reference.sql — reference (dimension) tables.
-- Small, static, addressed by code. Seeds live in 08_seed_reference.sql.
-- ============================================================

-- ── Languages ─────────────────────────────────────────────────
-- Adding a new language = one row here (+ a dump in DUMPS_DIR). No code changes.
CREATE TABLE IF NOT EXISTS languages (
    id            SMALLSERIAL PRIMARY KEY,
    code          VARCHAR(8)  NOT NULL UNIQUE,           -- 'en','de','ru'
    name          VARCHAR(64) NOT NULL,
    native_name   VARCHAR(64),
    script        VARCHAR(16),                           -- 'Latn','Cyrl'
    morph_backend VARCHAR(16) NOT NULL DEFAULT 'stanza', -- stanza|pymorphy3|passthrough
    wordnet_id    VARCHAR(32),                           -- wordnet id in the `wn` library (for evaluation); NULL = none
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE
);

-- ── Parts of speech ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parts_of_speech (
    id      SMALLSERIAL PRIMARY KEY,
    code    VARCHAR(16) NOT NULL UNIQUE,                 -- 'noun','verb','adj',…
    ud_upos VARCHAR(8)                                   -- 'NOUN','VERB',… (Universal Dependencies)
);

-- ── Graph relation types ──────────────────────────────────────
-- scope='concept' — relation between concepts (hypernym/hyponym/antonym/…)
-- scope='lexical' — relation between words (Wiktionary: synonym/derived/…)
CREATE TABLE IF NOT EXISTS relation_types (
    id           SMALLSERIAL PRIMARY KEY,
    code         VARCHAR(24) NOT NULL UNIQUE,            -- 'synonym','antonym','hypernym',…
    is_symmetric BOOLEAN     NOT NULL DEFAULT FALSE,
    scope        VARCHAR(8)  NOT NULL                    -- 'concept' | 'lexical'
        CHECK (scope IN ('concept', 'lexical'))
);
