-- ============================================================
-- 04_lexical.sql — lexical core: words, word forms, morphology.
--
-- `words` is the single carrier of a "word" (lexeme). "All words" =
-- rows in words (+ word_forms for the paradigm's surface forms).
-- ============================================================

-- ── Words (lexemes) ───────────────────────────────────────────
-- A lexeme = (language, part of speech, lemma).
CREATE TABLE IF NOT EXISTS words (
    id          BIGSERIAL PRIMARY KEY,
    language_id SMALLINT  NOT NULL REFERENCES languages(id),
    pos_id      SMALLINT  REFERENCES parts_of_speech(id),
    unit_type   VARCHAR(16) NOT NULL DEFAULT 'word'      -- word|phrase|proverb
        CHECK (unit_type IN ('word','phrase','proverb')),
    lemma       TEXT      NOT NULL,
    lemma_norm  TEXT      NOT NULL,                      -- NFC + casefold for matching
    etymology   TEXT,
    gender      VARCHAR(16),                             -- noun grammatical gender from the dump (Masc|Fem|Neut|combination); NULL = n/a
    freq_rank   INT,                                     -- prioritization (NULL = unknown)
    source_id   INT       REFERENCES sources(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULLS NOT DISTINCT: with unknown part of speech (pos_id=NULL) we avoid duplicates (PG15+)
    UNIQUE NULLS NOT DISTINCT (language_id, pos_id, lemma)
);
CREATE INDEX IF NOT EXISTS idx_words_lang_norm ON words (language_id, lemma_norm);

-- ── Word forms ────────────────────────────────────────────────
-- Every inflected surface form; the headword is stored as a form too.
CREATE TABLE IF NOT EXISTS word_forms (
    id        BIGSERIAL PRIMARY KEY,
    word_id   BIGINT    NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    form      TEXT      NOT NULL,
    form_norm TEXT      NOT NULL,
    tags      JSONB     NOT NULL DEFAULT '[]',           -- raw morpho-tags from the dump
    UNIQUE (word_id, form, tags)
);
CREATE INDEX IF NOT EXISTS idx_word_forms_norm ON word_forms (form_norm);

-- ── Form morphology (UD parse: Stanza / pymorphy3) ────────────
-- The "form → lemma" link is needed to search by any form of a word (Phase 1).
CREATE TABLE IF NOT EXISTS form_morphology (
    word_form_id BIGINT      PRIMARY KEY REFERENCES word_forms(id) ON DELETE CASCADE,
    upos         VARCHAR(8),                             -- UD UPOS
    feats        JSONB       NOT NULL DEFAULT '{}',       -- UD features (Case=Nom|Number=Sing|…)
    lemma        TEXT,                                    -- parsed lemma
    source       VARCHAR(12) NOT NULL DEFAULT 'stanza'   -- stanza|pymorphy3|dump
);
CREATE INDEX IF NOT EXISTS idx_form_morph_lemma ON form_morphology (lemma);
