-- ============================================================
-- 07_serving.sql — translation raw material (Phase 2 input).
--
-- IMPORTANT: there is NO pairwise translation "table". A translation is
-- computed by QUERYING the concept graph (Phase 3). Materializing all pairs
-- grows quadratically with languages × vocabulary; the concept pivot returns
-- a translation in one join, and adding a language costs linearly in its size.
--
-- Here we keep only the RAW material: explicit translation hints from the
-- dumps, the input for Phase 2 (Union-Find builds concepts over these edges).
-- ============================================================

-- ── Raw translation hints from the dumps ──────────────────────
-- E.g. the EN article 'dog' has translations: de=Hund, ru=собака → rows here.
CREATE TABLE IF NOT EXISTS translation_hints (
    id          BIGSERIAL PRIMARY KEY,
    sense_id    BIGINT    NOT NULL REFERENCES senses(id) ON DELETE CASCADE,
    target_lang VARCHAR(8) NOT NULL,
    target_word TEXT      NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trans_hints_sense
    ON translation_hints (sense_id);
CREATE INDEX IF NOT EXISTS idx_trans_hints_target
    ON translation_hints (target_lang, target_word);
