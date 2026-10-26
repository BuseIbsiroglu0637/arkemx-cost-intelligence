"""M4.3.1: explicit identity-marker guard for the controlled M512 fixture.

Only DEMO-M512-xxx is a declared synthetic identifier namespace. A bare
"kalem 001" in an unrelated real-world specification is NOT an identifier.
This guard may *reject* contradictory fixture identifiers, never grant
engineering approval or infer official position equivalence.
"""
import re
from .excel import normalized

FIXTURE_CODE = re.compile(r"^DEMO-M512-(\d{3})$", re.IGNORECASE)
FIXTURE_LABEL = re.compile(r"\bkalem\s+(\d{1,4})\b")


def _fixture_label(description: str):
    text = normalized(description)
    marks = list(FIXTURE_LABEL.finditer(text))
    values = {int(mark.group(1)) for mark in marks}
    if len(values) != 1:
        return None, None
    mark = marks[0]
    return next(iter(values)), {"excerpt": text[mark.start():mark.end()],
                                "start": mark.start(), "end": mark.end(),
                                "offset_basis": "normalized_text"}


def fixture_identity(metraj_description: str, catalog_description: str,
                     position_code: str):
    """Return an extra evidence check for the declared M512 synthetic catalog.

    'match' merely permits the *existing* separate technical checks to proceed.
    'block' rejects contradictory explicit identity markers.
    'review' keeps one-sided/ambiguous identifiers unapproved.
    """
    code = FIXTURE_CODE.fullmatch((position_code or "").strip())
    if code is None:
        return None
    expected = int(code.group(1))
    metraj_key, metraj_span = _fixture_label(metraj_description)
    catalog_key, catalog_span = _fixture_label(catalog_description)
    if metraj_key is None or catalog_key is None:
        status = "review"
        issue = "M512_ITEM_ID_UNVERIFIED"
    elif metraj_key != catalog_key or catalog_key != expected:
        status = "block"
        issue = "M512_ITEM_ID_MISMATCH"
    else:
        status = "match"
        issue = None
    return {
        "key": "fixture_item_identity",
        "metraj": {"value": str(metraj_key).zfill(3) if metraj_key is not None else None,
                   "quote": metraj_span},
        "catalog": {"value": str(catalog_key).zfill(3) if catalog_key is not None else None,
                    "quote": catalog_span},
        "status": status, "code": issue,
    }


def approval_identity_issue(metraj_description: str, catalog_description: str,
                            position_code: str, recorded_proof: dict | None):
    """Also protect approvals of *old* published evidence without modifying it."""
    check = fixture_identity(metraj_description, catalog_description, position_code)
    if check is None:
        return None
    if check["status"] != "match":
        return check["code"]
    stored = (recorded_proof or {}).get("checks")
    if not isinstance(stored, list):
        return "M512_IDENTITY_EVIDENCE_MISSING"
    entries = [c for c in stored if isinstance(c, dict)
               and c.get("key") == "fixture_item_identity"]
    if len(entries) != 1 or entries[0] != check:
        return "M512_IDENTITY_EVIDENCE_MISSING"
    return None
