-- ============================================================
-- 01_extensions.sql — PostgreSQL extensions.
-- All of these are contrib (shipped with a standard PostgreSQL 18 install).
-- Search indexes built on top of them come later, after data is loaded.
-- ============================================================

-- Substring / fuzzy search: LIKE '%x%' / % via a GIN index (gin_trgm_ops).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Diacritics stripping (ad-hoc input normalization; already baked into *_norm in ETL).
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Scalar + trigram in one GIN index → substring search scoped to a language.
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Fuzzy matching: levenshtein() — "did you mean", typo ranking.
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
