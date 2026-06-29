"""
Phase 2 unit tests — the pure Union-Find component logic (no DB).

Run:  venv\\Scripts\\python -m unittest discover -s src/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/

from pipeline.phase_concepts import components_from_edges


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
