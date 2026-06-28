-- ============================================================
-- 00_init.sql — master init script for the `lingdb_dev` database.
--
-- Run manually (once):
--
--   createdb lingdb_dev
--   psql -d lingdb_dev -f src/db/00_init.sql
--
-- Applies layers in dependency order. Every file is idempotent
-- (IF NOT EXISTS / ON CONFLICT DO NOTHING) — re-running is safe.
--
-- Target RDBMS: PostgreSQL 18.
-- Schema rationale: see ../../ORI_predlog.md (Phase 4 — Storage).
-- ============================================================

\set ON_ERROR_STOP on
\encoding UTF8
\echo '=== lingdb schema init ==='

\echo '-- 01 extensions'
\ir 01_extensions.sql
\echo '-- 02 reference'
\ir 02_reference.sql
\echo '-- 03 provenance'
\ir 03_provenance.sql
\echo '-- 04 lexical'
\ir 04_lexical.sql
\echo '-- 05 semantic'
\ir 05_semantic.sql
\echo '-- 06 relations'
\ir 06_relations.sql
\echo '-- 07 serving (translation hints — Phase 2 input)'
\ir 07_serving.sql
\echo '-- 08 seed reference data (3 languages: en, de, ru)'
\ir 08_seed_reference.sql

\echo '=== lingdb schema init complete ==='
