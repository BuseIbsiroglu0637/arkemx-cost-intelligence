"""Publicly inspectable M4 synthetic benchmark; never claims production accuracy."""
from .technical import compare, VERSION

# Synthetic positive and counterexample pairs. 'acceptable' refers only to the
# limited v0.1 rule-defined properties, not actual procurement correctness.
FIXTURES = (
    ("Gazbeton duvar 10 cm", "m²", "Gazbeton duvar 10 cm", "m²", True),
    ("Gazbeton duvar 10 cm", "m²", "Gazbeton duvar 15 cm", "m²", False),
    ("Gazbeton duvar", "m²", "Gazbeton duvar 10 cm", "m²", False),
    ("Porselen seramik zemin kaplama 60x60", "m²",
     "Porselen seramik zemin kaplama 60x60", "m²", True),
    ("Porselen seramik zemin kaplama 60x60", "m²",
     "Porselen seramik zemin kaplama 30x60", "m²", False),
    ("Porselen seramik zemin kaplama 60x60", "m²",
     "Porselen seramik duvar kaplama 60x60", "m²", False),
    ("Porselen seramik kaplama 60x60", "m²",
     "Porselen seramik zemin kaplama 60x60", "m²", False),
    ("Kapı montaj", "adet", "Kapı söküm", "adet", False),
    ("Kapı montaj", "adet", "Kapı montaj", "adet", True),
    ("Kapı montaj", "adet", "Kapı montaj", "m²", False),
    ("İç duvar boya işleri", "m²", "Dış duvar boya işleri", "m²", False),
    ("İç duvar boya işleri", "m²", "İç duvar boya işleri", "m²", True),
    ("Gazbeton duvar 100 mm", "m²", "Gazbeton duvar 10 cm", "m²", True),
    ("Hazır beton döküm", "m³", "Hazır beton döküm", "m³", True),
    ("Hazır beton döküm", "m³", "Hazır çelik döküm", "m³", False),
    ("Boya işleri", "m²", "Boya işleri", "m²", True),
)


def evaluate_fixture():
    true_positive = false_positive = true_negative = false_negative = 0
    examples = []
    for description, unit, candidate_description, candidate_unit, acceptable in FIXTURES:
        result = compare(description, unit, candidate_description, candidate_unit)
        predicted = result["manual_approval_allowed"]
        if predicted and acceptable:
            true_positive += 1
        elif predicted and not acceptable:
            false_positive += 1
        elif not predicted and not acceptable:
            true_negative += 1
        else:
            false_negative += 1
        examples.append({"metraj": description, "catalog": candidate_description,
                         "expected_acceptable": acceptable,
                         "status": result["status"], "blockers": result["blockers"],
                         "review_flags": result["review_flags"]})
    n = len(FIXTURES)
    return {
        "fixture": "synthetic-v0.1", "rule_version": VERSION, "sample_size": n,
        "not_production_validation": True,
        "true_positive": true_positive, "false_positive": false_positive,
        "true_negative": true_negative, "false_negative": false_negative,
        "precision": round(true_positive / max(1, true_positive + false_positive), 4),
        "recall": round(true_positive / max(1, true_positive + false_negative), 4),
        "examples": examples,
    }
