-- ============================================================
-- 06_relations.sql — graph edges: relations between concepts and between words.
--
-- concept_relations — between concepts (hypernym/hyponym/antonym/…), derived
--                     in Phase 2/3 from Wiktionary relations lifted to the
--                     concept level.
-- lexical_relations — between words (Wiktionary synonym/antonym/derived/…);
--                     these relations used to be discarded — now we keep them.
-- ============================================================

-- ── Relations between concepts ────────────────────────────────
CREATE TABLE IF NOT EXISTS concept_relations (
    from_concept_id  BIGINT   NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    to_concept_id    BIGINT   NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    relation_type_id SMALLINT NOT NULL REFERENCES relation_types(id),
    source_id        INT      REFERENCES sources(id),
    PRIMARY KEY (from_concept_id, to_concept_id, relation_type_id)
);
CREATE INDEX IF NOT EXISTS idx_concept_rel_to ON concept_relations (to_concept_id);

-- ── Lexical relations (from Wiktionary) ───────────────────────
-- to_word_id NULL + to_lemma — when the target is not imported yet (link later).
CREATE TABLE IF NOT EXISTS lexical_relations (
    id               BIGSERIAL PRIMARY KEY,
    from_word_id     BIGINT   NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    to_word_id       BIGINT   REFERENCES words(id),
    to_lemma         TEXT,
    relation_type_id SMALLINT NOT NULL REFERENCES relation_types(id),
    source_id        INT      REFERENCES sources(id)
);
CREATE INDEX IF NOT EXISTS idx_lexical_rel_from ON lexical_relations (from_word_id);
CREATE INDEX IF NOT EXISTS idx_lexical_rel_to   ON lexical_relations (to_word_id)
    WHERE to_word_id IS NOT NULL;
