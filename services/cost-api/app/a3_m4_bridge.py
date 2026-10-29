"""Read-only identity checks between saved A3 evidence and latest M4 candidate.

Does not create candidates, decisions, approvals or costs.
"""
import hashlib
import os
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_assessment_store import TechnicalReviewAssessment
from .a3_batch_review import NO_STORE
from .a3_review_assessments import source_row
from .a3_review_records import owned_record, view
from .database import get_db
from .excel import normalize_unit
from .m42 import _context, candidate_detail
from .models import (
    CatalogPosition,
    MatchCandidate,
    MatchDecision,
    MatchRunItemSnapshot,
    User,
)
from .security import current_user
from .technical_analysis.pdf_analysis_source import read_analysis

router = APIRouter(prefix="/api/projects/{project_id}/a3/reviews/{record_id}",
                   tags=["A3 M4 Identity Bridge"])


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@router.get("/m4-link")
def inspect_link(project_id: UUID, record_id: UUID, work_item_id: UUID, response: Response,
                 user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    record = owned_record(db, user, str(project_id), str(record_id))
    item = source_row(record, str(work_item_id))
    saved = view(record, db)
    checks, identity_flags, readiness_flags = [], [], []
    result = {"schema": "arkemx.a3_m4_link.v1", "read_only": True, "approval_allowed": False,
              "engineering_approval": False, "record_id": record.id, "work_item_id": str(work_item_id),
              "snapshot_sha256": record.snapshot_sha256, "candidate_code": item["candidate_code"],
              "link_status": "unresolved", "ready_for_m4_review": False,
              "m4_candidate": None, "currentness": saved["currentness"], "checks": checks}
    response.headers.update(NO_STORE)

    def check(code, ok, *, identity=False):
        checks.append({"code": code, "status": "match" if ok else "review"})
        if not ok:
            (identity_flags if identity else readiness_flags).append(code)

    def finish():
        result["link_status"] = "linked" if not identity_flags else "unresolved"
        result["ready_for_m4_review"] = not identity_flags and not readiness_flags
        result["flags"] = identity_flags + readiness_flags
        return result

    check("A3_REVIEW_CURRENT", saved["currentness"]["status"] == "unchanged", identity=True)
    check("A3_FEATURES_MATCH", item["technical_status"] == "checked_features_match")
    check("A3_PRICE_SOURCE_VERIFIED", item["price_source_status"] == "verified")
    check("CANDIDATE_SELECTED", bool(item["candidate_code"]), identity=True)
    context = _context(db, user, str(project_id))
    check("M4_RUN_FOUND", context is not None, identity=True)
    if context is None:
        return finish()
    run, version, source, rights_active, outdated = context
    check("M4_IMPORT_MATCH", run.import_id == record.import_id, identity=True)
    check("M4_CATALOG_RIGHTS_ACTIVE", rights_active)
    check("M4_IMPORT_CURRENT", not outdated)
    matches = db.execute(select(MatchCandidate, CatalogPosition).join(
        CatalogPosition, CatalogPosition.id == MatchCandidate.position_id).where(
        MatchCandidate.run_id == run.id, MatchCandidate.work_item_id == str(work_item_id),
        CatalogPosition.code == item["candidate_code"]).limit(2)).all()
    check("M4_CANDIDATE_UNIQUE", len(matches) == 1, identity=True)
    if len(matches) != 1:
        return finish()
    candidate, position = matches[0]
    check("M4_POSITION_VERSION_MATCH", position.version_id == version.id, identity=True)
    detail = candidate_detail(str(project_id), candidate.id, user, db)
    proof = detail["evidence"] or {}
    snapshot = db.scalar(select(MatchRunItemSnapshot).where(
        MatchRunItemSnapshot.run_id == run.id, MatchRunItemSnapshot.work_item_id == str(work_item_id)))
    check("M4_REVISION_MATCH", snapshot is not None and
          snapshot.revision_id == item["identity"]["revision_id"] and
          snapshot.description == item["effective_description"], identity=True)
    refs = proof.get("source_refs", {})
    expected_metraj = {"import_id": record.import_id,
        "import_sha256": saved["report"]["import_source"]["sha256"],
        "source_row": item["identity"]["source_row"], "work_item_id": str(work_item_id),
        "revision_id": item["identity"]["revision_id"]}
    expected_catalog = {"version_id": version.id, "version_sha256": version.sha256,
                        "position_id": position.id, "position_code": position.code}
    check("M4_EVIDENCE_REFERENCES_MATCH", refs.get("metraj") == expected_metraj and
          refs.get("catalog") == expected_catalog, identity=True)
    proof_sources = proof.get("sources", {})
    check("M4_EVIDENCE_TEXT_MATCH", proof_sources.get("metraj", {}).get("sha256") ==
          text_hash(item["effective_description"]) and
          proof_sources.get("catalog", {}).get("sha256") == text_hash(position.description), identity=True)
    # Same code is insufficient: require the verified PDF's full technical text.
    analysis = None
    try:
        analysis = read_analysis(os.environ.get("ARKEMX_ANALYSIS_PDF", ""))
        price = item["source_price"] or {}
        if (analysis["source"]["sha256"] != price["source"]["sha256"] or
            analysis["position_code"] != item["candidate_code"] or
            analysis["approval_allowed"] is not False or analysis["read_only"] is not True):
            analysis = None
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        analysis = None
    check("PDF_SOURCE_REVALIDATED", analysis is not None, identity=True)
    if analysis:
        check("CATALOG_PDF_TEXT_MATCH", position.description == analysis["technical_description"]["quote"], identity=True)
        unit, issues = normalize_unit(position.unit)
        check("CATALOG_PDF_UNIT_MATCH", not issues and unit == analysis["unit"], identity=True)
        try:
            source_year = date.fromisoformat(analysis["source"]["price_date"]).year
        except (ValueError, KeyError, TypeError):
            source_year = None
        check("CATALOG_PDF_YEAR_MATCH", source_year == version.year, identity=True)
    check("M4_EVIDENCE_CURRENT", detail["stale"] is False)
    check("M4_EXISTING_GATES_PASS", detail["can_approve"] is True)
    decision = db.scalar(select(MatchDecision).where(MatchDecision.candidate_id == candidate.id)
        .order_by(MatchDecision.created_at.desc(), MatchDecision.id.desc()).limit(1))
    check("M4_CANDIDATE_UNDECIDED", decision is None)
    assessment = db.scalar(select(TechnicalReviewAssessment).where(
        TechnicalReviewAssessment.record_id == record.id,
        TechnicalReviewAssessment.work_item_id == str(work_item_id)).order_by(
            TechnicalReviewAssessment.created_at.desc(), TechnicalReviewAssessment.id.desc()).limit(1))
    check("A3_ASSESSMENT_REQUIRES_REVIEW", assessment is None)
    result["m4_candidate"] = {"run_id": run.id, "candidate_id": candidate.id,
        "position_id": position.id, "code": position.code, "catalog_version_id": version.id,
        "catalog_year": version.year, "catalog_period": version.period,
        "catalog_institution": source.institution, "catalog_sha256": version.sha256,
        "evidence_sha256": proof.get("evidence_sha256"), "evidence_status": proof.get("status"),
        "existing_gate_can_approve": detail["can_approve"],
        "latest_decision": decision.action if decision else None,
        "latest_assessment": assessment.action if assessment else None}
    return finish()
