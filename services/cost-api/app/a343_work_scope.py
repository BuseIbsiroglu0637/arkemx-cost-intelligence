"""Conservative work-scope guard for PDF positions.

Names referring to the same material are not enough to match the same
construction operation. Explicit material-only or demolition differences
never become cost-eligible matches.
"""
import re
from .excel import normalized


DEMOLITION = re.compile(r"\b(?:sokul\w*|sokum\w*|sokme\w*|demontaj\w*|kiril\w*|yikim\w*)\b")
MATERIAL_ONLY = re.compile(r"\b(?:malzeme(?:si|leri|lerin)?|temin(?:i)?|satin\s*alma)\b")
LABOR_ONLY = re.compile(r"\b(?:iscilik|is\s*cilik)\b")
EXECUTION = re.compile(r"\b(?:yapil\w*|uygulan\w*|dos(en|e)n\w*|montaj\w*|kaplan\w*|kaplama\w*|seril\w*|imalat\w*|yerlestiril\w*)\b")


def scope_blocker(metraj: str, position: str) -> str | None:
    left, right = normalized(metraj), normalized(position)
    source_demolition = bool(DEMOLITION.search(left))
    target_demolition = bool(DEMOLITION.search(right))
    if source_demolition != target_demolition:
        return "WORK_SCOPE_DEMOLITION_MISMATCH"

    source_material = bool(MATERIAL_ONLY.search(left))
    source_labor = bool(LABOR_ONLY.search(left))
    target_work = bool(EXECUTION.search(right))
    # Metraj explicitly prices material supply separately; an installation
    # or a mixed installation+material poz must not double-count it.
    if source_material and not source_labor and target_work:
        return "WORK_SCOPE_MATERIAL_ONLY_MISMATCH"
    # Labor-only metraj cannot take a poz explicitly containing material
    # supply as if it were a labor-only rate.
    if source_labor and not source_material and MATERIAL_ONLY.search(right):
        return "WORK_SCOPE_LABOR_ONLY_MISMATCH"
    return None
