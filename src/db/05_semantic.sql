-- ============================================================
-- 05_semantic.sql — semantic core: concepts, senses, membership, examples.
--
-- A concept is an interlingual unit of meaning (no EN pivot). Concepts are
-- built FROM the Wiktionary translation GRAPH (ORI_predlog.md, Phase 2), NOT
-- from OMW. The ili/wordnet_synset columns are optional and filled only during
-- EVALUATION (aligning our concepts to OMW synsets). See Phase 2.
-- ============================================================

-- ── Concepts (concept vertices of the graph) ──────────────────
-- Append-only: concepts are not renumbered when a language is added later.
CREATE TABLE IF NOT EXISTS concepts (
    id             BIGSERIAL  PRIMARY KEY,
    pos_id         SMALLINT   REFERENCES parts_of_speech(id),
    gloss          TEXT,                                 -- representative gloss (any language)
    gloss_en       TEXT,                                 -- English gloss if available (QA/search)
    ili            VARCHAR(24) UNIQUE,                   -- CILI id — filled ONLY during OMW evaluation; NULL by default
    wordnet_synset VARCHAR(32),                          -- 'oewn-02084071-n' — same, optional
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Senses — sense vertices of the graph ──────────────────────
-- One sense of a word. Belongs to a specific word (and through it, a language).
CREATE TABLE IF NOT EXISTS senses (
    id            BIGSERIAL PRIMARY KEY,
    word_id       BIGINT    NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    sense_index   SMALLINT  NOT NULL DEFAULT 0,
    gloss         TEXT,
    -- If the meaning is actually a word form (kaikki form_of/alt_of: "plural of pie"),
    -- this holds the lemma_norm of the target lemma. Such meanings are NOT grounded
    -- into concepts (Phase 2): form translation goes via morphology form→lemma→lemma's concepts.
    form_of_lemma TEXT,
    -- Sense labels from the dump (dialect/region/register).
    tags          JSONB     NOT NULL DEFAULT '[]',
    source_id     INT       REFERENCES sources(id)
);
CREATE INDEX IF NOT EXISTS idx_senses_word ON senses (word_id);
CREATE INDEX IF NOT EXISTS idx_senses_form_of ON senses (form_of_lemma)
    WHERE form_of_lemma IS NOT NULL;

-- ── Sense → concept membership (edges "sense belongs to concept") ─
-- method — which Phase 2 pass attached it (ORI_predlog.md §3, Phase 2):
--   direct     — direct translation edges (confidence 1.0)
--   transitive — Union-Find transitive closure
--   tfidf      — gloss-similarity disambiguation (confidence 0.85)
--   labse      — LaBSE embedding attachment (confidence 0.70)
-- Incremental: when a language is added, write rows only for NEW senses.
CREATE TABLE IF NOT EXISTS sense_concepts (
    sense_id   BIGINT     NOT NULL REFERENCES senses(id) ON DELETE CASCADE,
    concept_id BIGINT     NOT NULL REFERENCES concepts(id),
    confidence REAL       NOT NULL DEFAULT 1.0,
    method     VARCHAR(16) NOT NULL
        CHECK (method IN ('direct','transitive','tfidf','labse')),
    run_id     BIGINT     REFERENCES pipeline_runs(id),
    PRIMARY KEY (sense_id, concept_id)
);
CREATE INDEX IF NOT EXISTS idx_sense_concepts_concept ON sense_concepts (concept_id);

-- ── Usage examples ────────────────────────────────────────────
-- Normalized table (attached to a SPECIFIC sense, not the whole word).
CREATE TABLE IF NOT EXISTS examples (
    id          BIGSERIAL PRIMARY KEY,
    sense_id    BIGINT    NOT NULL REFERENCES senses(id) ON DELETE CASCADE,
    text        TEXT      NOT NULL,
    translation TEXT,                                    -- example translation (if any)
    reference   TEXT                                     -- source/citation
);
CREATE INDEX IF NOT EXISTS idx_examples_sense ON examples (sense_id);
