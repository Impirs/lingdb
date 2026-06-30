"""
Phase 2 unit tests — the pure Union-Find component logic (no DB).

Run:  venv\\Scripts\\python -m unittest discover -s src/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/

from pipeline.phase_concepts import _tfidf_edges, components_from_edges


def _norm_sets(components):
    return sorted(sorted(c) for c in components)


class TestComponents(unittest.TestCase):
    def test_transitive_closure(self):
        # A↔B, B↔C ⇒ {A,B,C}; a separate pair stays separate
        comps = components_from_edges([(1, 2), (2, 3), (10, 11)])
        self.assertEqual(_norm_sets(comps), [[1, 2, 3], [10, 11]])

    def test_merges_two_chains_via_bridge(self):
        comps = components_from_edges([(1, 2), (3, 4), (2, 3)])
        self.assertEqual(_norm_sets(comps), [[1, 2, 3, 4]])

    def test_duplicate_edges_are_harmless(self):
        comps = components_from_edges([(1, 2), (1, 2), (2, 1)])
        self.assertEqual(_norm_sets(comps), [[1, 2]])

    def test_no_edges_no_components(self):
        self.assertEqual(components_from_edges([]), [])


class TestTfidfDisambiguation(unittest.TestCase):
    # info[sid] = (language_id, pos_id, gloss, lang_code)
    def test_picks_best_gloss_match(self):
        info = {
            1: (1, 1, "a small domesticated feline animal that purrs", "en"),
            2: (2, 1, "small domesticated feline animal kept as a pet that purrs", "de"),
            3: (2, 1, "a large wild canine that howls at the moon", "de"),
        }
        # source 1 must attach to the feline candidate (2), not the canine (3)
        self.assertEqual(_tfidf_edges({1: {2, 3}}, info, 0.2), [(1, 2)])

    def test_no_match_below_threshold(self):
        info = {1: (1, 1, "alpha beta gamma", "en"), 2: (2, 1, "delta epsilon zeta", "de")}
        self.assertEqual(_tfidf_edges({1: {2}}, info, 0.5), [])

    def test_skips_senses_without_gloss(self):
        info = {1: (1, 1, "", "en"), 2: (2, 1, "some gloss text", "de")}
        self.assertEqual(_tfidf_edges({1: {2}}, info, 0.1), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
