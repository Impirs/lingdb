"""
Phase 1 unit tests — pure cleaning/parsing functions (no DB).

Run:  venv\\Scripts\\python -m pytest src/tests -q
 or:  venv\\Scripts\\python -m unittest discover -s src/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/

from pipeline.phase_import import _clean, _destress, _extract_gender, _norm, _parse
from pipeline.morph_tags import tags_to_feats


class TestCleaning(unittest.TestCase):
    def test_clean_strips_wiki_brackets(self):
        self.assertEqual(_clean("[[dog]]"), "dog")

    def test_clean_strips_footnote_markers(self):
        # caret + footnote sign (triangle / asterisk / dagger)
        self.assertEqual(_clean("вас^△"), "вас")
        self.assertEqual(_clean("есмь^*"), "есмь")
        self.assertEqual(_clean("еси^†"), "еси")

    def test_destress_removes_stress_keeps_yo(self):
        # combining acute is removed, the letter ё is preserved
        self.assertEqual(_destress("соба́ка"), "собака")
        self.assertEqual(_destress("берёза"), "берёза")

    def test_norm_nfc_casefold(self):
        self.assertEqual(_norm("  ДОМ "), "дом")


class TestMorphTags(unittest.TestCase):
    def test_tags_to_feats_known(self):
        feats = tags_to_feats(["genitive", "plural"])
        self.assertEqual(feats, {"Case": "Gen", "Number": "Plur"})

    def test_tags_to_feats_ignores_noise(self):
        self.assertEqual(tags_to_feats(["multiword-construction", "archaic"]), {})


class TestParse(unittest.TestCase):
    def test_parse_english_entry(self):
        obj = {
            "word": "dog", "pos": "noun", "lang_code": "en",
            "senses": [{
                "glosses": ["A domesticated carnivorous mammal."],
                "examples": [{"text": "The dog barked.", "ref": ""}],
                "translations": [
                    {"lang_code": "de", "word": "Hund"},
                    {"lang_code": "ru", "word": "собака"},
                ],
            }],
            "forms": [{"form": "dogs", "tags": ["plural"]}],
            "synonyms": [{"word": "hound"}],
        }
        rec = _parse(obj, "en")
        self.assertEqual(rec["title"], "dog")
        self.assertEqual(rec["pos_code"], "noun")
        self.assertEqual(rec["unit_type"], "word")
        self.assertEqual(len(rec["senses"]), 1)
        self.assertEqual(rec["senses"][0]["gloss"], "A domesticated carnivorous mammal.")
        self.assertIn(("de", "Hund"), rec["senses"][0]["tr"])
        self.assertIn(("ru", "собака"), rec["senses"][0]["tr"])
        self.assertIn(("dogs", ["plural"]), rec["forms"])
        self.assertIn(("synonym", "hound"), rec["rels"])

    def test_parse_russian_destresses_everywhere(self):
        obj = {
            "word": "соба́ка", "pos": "noun", "lang_code": "ru",
            "senses": [{"glosses": ["пёс"], "translations": []}],
            "forms": [{"form": "соба́ки", "tags": ["genitive"]}],
        }
        rec = _parse(obj, "ru")
        self.assertEqual(rec["title"], "собака")             # lemma without stress
        self.assertIn(("собаки", ["genitive"]), rec["forms"])  # form without stress

    def test_parse_skips_punctuation_only_forms(self):
        obj = {"word": "x", "pos": "noun", "lang_code": "en",
               "forms": [{"form": "?", "tags": []}, {"form": "xs", "tags": ["plural"]}]}
        rec = _parse(obj, "en")
        form_strings = [f for f, _ in rec["forms"]]
        self.assertNotIn("?", form_strings)
        self.assertIn("xs", form_strings)

    def test_extract_gender_german_top_level_tags(self):
        self.assertEqual(_extract_gender({"tags": ["masculine"]}), "Masc")
        self.assertEqual(_extract_gender({"tags": ["feminine"]}), "Fem")

    def test_extract_gender_german_article_fallback(self):
        obj = {"forms": [{"form": "Haus", "tags": ["nominative", "singular"], "article": "das"}]}
        self.assertEqual(_extract_gender(obj), "Neut")


if __name__ == "__main__":
    unittest.main(verbosity=2)
