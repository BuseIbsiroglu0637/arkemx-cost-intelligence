"""M4.1 engineering evidence extractor — deterministic, quote-backed, fail-closed.

Evidence spans refer to the displayed NORMALIZED source text, not to original
Excel byte offsets. No source statement -> no invented claim. This is not a
full technical specification interpreter or professional engineering approval.
"""
import hashlib
import json
import re

from .excel import normalized
from .identity_guard import fixture_identity
from .technical import compare as compare_m4

VERSION = "evidence-v0.1"
ALGORITHM = "technical-rules-v0.1+evidence-v0.1"
CONCRETE_CLASS = re.compile(r"\bc\s*(\d{2})\s*/\s*(\d{2})\b", re.IGNORECASE)
STANDARD = re.compile(r"\bts\s*en\s*(\d{2,5}(?:-\d{1,4})?)\b", re.IGNORECASE)
SCOPE = {
    "nakliye": r"(?:nakliye|tasima)",
    "iscilik": r"(?:iscilik)",
    "malzeme": r"(?:malzeme)",
    "montaj": r"(?:montaj|kurulum)",
    "yardimci_imalat": r"(?:yardimci imalat|yardimci isler)",
}
INCLUDE = re.compile(r"\b(?:dahildir|dahil|icerir|kapsar)\b")
EXCLUDE = re.compile(r"\b(?:harictir|haric|dahil degildir|kapsamaz)\b")


def _one(normalized_text: str, pattern: re.Pattern, label: str):
    matches = list(pattern.finditer(normalized_text))
    values = []
    for match in matches:
        if label == "concrete_class":
            value = f"C{match.group(1)}/{match.group(2)}"
        else:
            value = "TS EN " + match.group(1)
        values.append((value, match))
    if len({v for v, _ in values}) > 1:
        # Several different declarations in a single description are ambiguous.
        return {"value": "multiple", "source": _span(normalized_text, values[0][1])}
    if not values:
        return {"value": None, "source": None}
    return {"value": values[0][0], "source": _span(normalized_text, values[0][1])}


def _span(text: str, match: re.Match):
    start, end = match.span()
    return {"excerpt": text[start:end], "start": start, "end": end,
            "offset_basis": "normalized_text"}


def _scope(text: str, keyword: str):
    # Only accept an explicit phrase: "nakliye dahildir" / "nakliye hariçtir".
    # Keyword alone is not permission to invent a scope claim.
    matches = list(re.finditer(r"\b" + keyword + r"\b", text))
    found = []
    for match in matches:
        # Stop at punctuation or another scope keyword: a qualifier for
        # "işçilik" cannot silently become a claim about preceding "nakliye".
        tail = text[match.end():]
        separator = re.search(r"[,;.]", tail)
        next_scope = re.search(
            r"\b(?:nakliye|tasima|iscilik|malzeme|montaj|kurulum|yardimci imalat|yardimci isler)\b",
            tail)
        limit = min(
            38,
            separator.start() if separator else len(tail),
            next_scope.start() if next_scope else len(tail),
        )
        fragment = text[match.start():match.end() + limit]
        negated = re.search(r"\bdahil degildir\b|\bharictir\b|\bharic\b|\bkapsamaz\b", fragment)
        positive = INCLUDE.search(fragment)
        if negated and (not positive or negated.start() <= positive.start()):
            value = "excluded"
            end = match.start() + negated.end()
        elif positive:
            value = "included"
            end = match.start() + positive.end()
        else:
            value = "mentioned"
            end = match.end()
        found.append({"value": value, "source": {
            "excerpt": text[match.start():end], "start": match.start(),
            "end": end, "offset_basis": "normalized_text"
        }})
    if not found:
        return {"value": None, "source": None}
    states = {item["value"] for item in found}
    if len(states) != 1:
        return {"value": "multiple", "source": found[0]["source"]}
    return found[0]


def extract_evidence(description: str) -> dict:
    text = normalized(description)
    concrete = _one(text, CONCRETE_CLASS, "concrete_class")
    standard = _one(text, STANDARD, "standard")
    scope = {key: _scope(text, keyword) for key, keyword in SCOPE.items()}
    return {
        "normalized_text": text,
        "source_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
        "facts": {"concrete_class": concrete, "standard": standard, **{
            f"scope_{key}": record for key, record in scope.items()
        }},
    }


def _status(key: str, left: dict, right: dict):
    a, b = left["value"], right["value"]
    if "multiple" in (a, b) or "mentioned" in (a, b):
        return "review", key.upper() + "_AMBIGUOUS"
    if a is None and b is None:
        return "not_specified", None
    if a is None or b is None:
        return "review", key.upper() + "_UNVERIFIED"
    if a != b:
        return "block", key.upper() + "_MISMATCH"
    return "match", None


def analyze(metraj_description: str, metraj_unit: str | None,
            catalog_description: str, catalog_unit: str | None,
            *, quantity_known: bool = True, review_required: bool = False,
            source_refs: dict | None = None) -> dict:
    basic = compare_m4(
        metraj_description, metraj_unit, catalog_description, catalog_unit,
        quantity_known=quantity_known, review_required=review_required)
    left = extract_evidence(metraj_description)
    right = extract_evidence(catalog_description)
    checks = []
    blockers = list(basic["blockers"])
    reviews = list(basic["review_flags"])
    scope_verified = False
    for key in ("concrete_class", "standard", *[f"scope_{key}" for key in SCOPE]):
        l, r = left["facts"][key], right["facts"][key]
        status, code = _status(key, l, r)
        if key == "concrete_class" and status == "not_specified":
            # Concrete grade cannot be inferred from the word "beton".
            if basic["fields"][1]["metraj"] == "beton" or basic["fields"][1]["catalog"] == "beton":
                status, code = "review", "CONCRETE_CLASS_UNVERIFIED"
        if key.startswith("scope_") and status in {"match", "block"}:
            scope_verified = True
        if status == "block" and code:
            blockers.append(code)
        elif status == "review" and code:
            reviews.append(code)
        checks.append({
            "key": key,
            "metraj": {"value": l["value"], "quote": l["source"]},
            "catalog": {"value": r["value"], "quote": r["source"]},
            "status": status, "code": code,
        })
    identity = fixture_identity(metraj_description, catalog_description,
                                (source_refs or {}).get("catalog", {}).get("position_code", ""))
    if identity is not None:
        checks.append(identity)
        if identity["status"] == "block":
            blockers.append(identity["code"])
        elif identity["status"] == "review":
            reviews.append(identity["code"])
    # Both texts may be merely short titles, not licensed full-position scope.
    # Never claim full compliance from matching titles alone.
    if not scope_verified:
        reviews.append("SCOPE_NOT_VERIFIABLE_FROM_TITLES")
    
    # A0: Temporary fail-closed protection.
    #
    # The existing technical extractor reads only the first
    # thickness. Multiple dimensions in a plaster description
    # therefore require review until the layer-aware engine
    # can associate each measurement with its own material.

    for text in (
        left["normalized_text"],
        right["normalized_text"],
    ):
        has_plaster = re.search(r"\bsiva\b", text) is not None

        thicknesses = re.findall(
            r"\b\d+(?:[.,]\d+)?\s*(?:mm|cm)\b",
            text,
        )

        if has_plaster and len(thicknesses) >= 2:
            reviews.append(
                "PLASTER_MULTIPLE_THICKNESSES_UNVERIFIED"
            )
            break

    if "concrete_class" not in [c["key"] for c in checks]:
        raise AssertionError("Concrete class check missing")
    blockers = sorted(set(blockers))
    reviews = sorted(set(reviews))
    status = "blocked" if blockers else "review" if reviews else "compatible"
    payload = {
        "schema": "arkemx.technical_evidence.v1",
        "version": VERSION,
        "status": status,
        "approval_allowed": status == "compatible",
        "blockers": blockers, "review_flags": reviews,
        "checks": checks,
        "sources": {
            "metraj": {"normalized_text": left["normalized_text"],
                       "sha256": left["source_sha256"]},
            "catalog": {"normalized_text": right["normalized_text"],
                        "sha256": right["source_sha256"]},
        },
        "basic_rule_version": basic["version"],
        "source_refs": source_refs or {},
        "basic_fields": basic["fields"],
        "score_is_probability": False,
        "statement": "Only evidence stated in supplied texts; external technical scope unverified.",
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def verify_evidence(payload: dict) -> bool:
    digest = payload.get("evidence_sha256", "")
    cloned = {k: v for k, v in payload.items() if k != "evidence_sha256"}
    canonical = json.dumps(cloned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
