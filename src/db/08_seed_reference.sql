-- ============================================================
-- 08_seed_reference.sql — static reference data.
--
-- Starting set: 3 languages (en, de, ru) — see ORI_predlog.md §2.
-- wordnet_id is set for the EVALUATION stage (comparing concepts to OMW).
-- Russian has no wordnet in OMW → wordnet_id = NULL (evaluated via Swadesh / MUSE).
-- ============================================================

-- ── Languages ─────────────────────────────────────────────────
INSERT INTO languages (code, name, native_name, script, morph_backend, wordnet_id) VALUES
    ('en', 'English', 'English', 'Latn', 'stanza',    'oewn'),    -- oewn (~120k synsets)
    ('de', 'German',  'Deutsch', 'Latn', 'stanza',    'odenet'),  -- odenet:1.3 (ILI ~55%)
    ('ru', 'Russian', 'Русский', 'Cyrl', 'pymorphy3', NULL)       -- NOT in OMW → evaluate via MUSE/Swadesh
ON CONFLICT (code) DO NOTHING;

-- ── Parts of speech (code → UD UPOS) ──────────────────────────
INSERT INTO parts_of_speech (code, ud_upos) VALUES
    ('noun',    'NOUN'),
    ('verb',    'VERB'),
    ('adj',     'ADJ'),
    ('adv',     'ADV'),
    ('pron',    'PRON'),
    ('det',     'DET'),
    ('adp',     'ADP'),      -- prepositions/postpositions
    ('conj',    'CCONJ'),
    ('sconj',   'SCONJ'),
    ('num',     'NUM'),
    ('part',    'PART'),
    ('intj',    'INTJ'),
    ('propn',   'PROPN'),    -- proper nouns
    ('phrase',  'X'),
    ('affix',   'X'),
    ('unknown', 'X')
ON CONFLICT (code) DO NOTHING;

-- ── Relation types ────────────────────────────────────────────
-- concept-scope (between concepts)
INSERT INTO relation_types (code, is_symmetric, scope) VALUES
    ('hypernym',        FALSE, 'concept'),
    ('hyponym',         FALSE, 'concept'),
    ('meronym',         FALSE, 'concept'),
    ('holonym',         FALSE, 'concept'),
    ('antonym',         TRUE,  'concept'),
    ('similar',         TRUE,  'concept')
ON CONFLICT (code) DO NOTHING;

-- lexical-scope (from Wiktionary, between words)
INSERT INTO relation_types (code, is_symmetric, scope) VALUES
    ('synonym',         TRUE,  'lexical'),
    ('antonym_lex',     TRUE,  'lexical'),
    ('derived',         FALSE, 'lexical'),
    ('related',         TRUE,  'lexical'),
    ('coordinate_term', TRUE,  'lexical')
ON CONFLICT (code) DO NOTHING;
