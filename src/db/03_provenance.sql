-- ============================================================
-- 03_provenance.sql — provenance, runs, resumability, raw records.
-- Enables reproducibility and safe restart/rollback.
-- ============================================================

-- ── Data sources ──────────────────────────────────────────────
-- A Wiktionary dump (kaikki.org), an OMW wordnet (for evaluation), a morph model.
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL      PRIMARY KEY,
    kind        VARCHAR(16) NOT NULL                     -- wiktionary|omw|other
        CHECK (kind IN ('wiktionary','omw','other')),
    language_id SMALLINT    REFERENCES languages(id),
    name        TEXT        NOT NULL,                    -- file name / wordnet id / model id
    version     TEXT,                                    -- dump date / model version
    license     TEXT,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULLS NOT DISTINCT: version=NULL does not create duplicate sources (PG15+)
    UNIQUE NULLS NOT DISTINCT (kind, name, version)
);

-- ── Pipeline runs ─────────────────────────────────────────────
-- Every derived row (sense_concepts, …) references a run_id
-- → a single method/run can be re-run or rolled back.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id             BIGSERIAL   PRIMARY KEY,
    step           VARCHAR(32) NOT NULL,
    params         JSONB       NOT NULL DEFAULT '{}',
    model_versions JSONB       NOT NULL DEFAULT '{}',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    status         VARCHAR(12) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','done','failed','cancelled'))  -- cancelled = Ctrl+C
);

-- ── Resumability: which step/language we stopped at ───────────
CREATE TABLE IF NOT EXISTS pipeline_progress (
    step          VARCHAR(50) NOT NULL,
    language_code VARCHAR(10) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',-- pending|running|done|failed
    processed     BIGINT      NOT NULL DEFAULT 0,
    last_id       BIGINT      NOT NULL DEFAULT 0,
    error_msg     TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (step, language_code)
);

-- ── Raw dump records (optional, STORE_RAW=1) ──────────────────
-- The record's original JSON — for reprocessing without re-reading the dump.
-- The clean model (words/senses/…) does not carry the blob.
CREATE TABLE IF NOT EXISTS source_records (
    id          BIGSERIAL PRIMARY KEY,
    source_id   INT       NOT NULL REFERENCES sources(id),
    language_id SMALLINT  NOT NULL REFERENCES languages(id),
    title       TEXT      NOT NULL,
    raw         JSONB     NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_records_lang_title
    ON source_records (language_id, title);
