"""
Wiktionary form-tags → UD features (feats). The fast path of Phase 1: most forms
come from the dump with tags (`forms[].tags`) bound to a known lemma+POS, so UD
features are derived by mapping — without a neural net.

Irrelevant tags (multiword-construction, strong/weak/mixed, archaic, …) are ignored.
"""
from __future__ import annotations

TAG2FEAT: dict[str, tuple[str, str]] = {
    # Case
    "nominative": ("Case", "Nom"), "genitive": ("Case", "Gen"),
    "dative": ("Case", "Dat"), "accusative": ("Case", "Acc"),
    "instrumental": ("Case", "Ins"), "prepositional": ("Case", "Loc"),
    "locative": ("Case", "Loc"), "vocative": ("Case", "Voc"),
    "ablative": ("Case", "Abl"), "partitive": ("Case", "Par"),
    # Number
    "singular": ("Number", "Sing"), "plural": ("Number", "Plur"), "dual": ("Number", "Dual"),
    # Gender
    "masculine": ("Gender", "Masc"), "feminine": ("Gender", "Fem"), "neuter": ("Gender", "Neut"),
    # Person
    "first-person": ("Person", "1"), "second-person": ("Person", "2"),
    "third-person": ("Person", "3"),
    # Tense
    "present": ("Tense", "Pres"), "past": ("Tense", "Past"), "future": ("Tense", "Fut"),
    "imperfect": ("Tense", "Imp"), "pluperfect": ("Tense", "Pqp"),
    # Mood
    "indicative": ("Mood", "Ind"), "subjunctive": ("Mood", "Sub"),
    "subjunctive-i": ("Mood", "Sub"), "subjunctive-ii": ("Mood", "Sub"),
    "imperative": ("Mood", "Imp"), "conditional": ("Mood", "Cnd"),
    # VerbForm
    "infinitive": ("VerbForm", "Inf"), "participle": ("VerbForm", "Part"),
    "gerund": ("VerbForm", "Ger"), "adverbial": ("VerbForm", "Conv"),
    # Degree
    "positive": ("Degree", "Pos"), "comparative": ("Degree", "Cmp"),
    "superlative": ("Degree", "Sup"),
    # Voice
    "active": ("Voice", "Act"), "passive": ("Voice", "Pass"),
    "processual-passive": ("Voice", "Pass"), "statal-passive": ("Voice", "Pass"),
    # Aspect (Slavic — important for Russian)
    "perfective": ("Aspect", "Perf"), "imperfective": ("Aspect", "Imp"),
    # Animacy (Russian)
    "animate": ("Animacy", "Anim"), "inanimate": ("Animacy", "Inan"),
    # Definiteness
    "definite": ("Definite", "Def"), "indefinite": ("Definite", "Ind"),
    # Variant
    "short-form": ("Variant", "Short"),
}


def tags_to_feats(tags) -> dict[str, str]:
    feats: dict[str, str] = {}
    for t in tags or []:
        hit = TAG2FEAT.get(str(t).lower())
        if hit:
            feats[hit[0]] = hit[1]
    return feats
