"""Code equality alone cannot connect A3 evidence to M4 approval."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from test_a312_review_records import revise, saved, source  # noqa: F401
from test_a392_batch_review_api import TEXT
from test_m41 import auth as make_auth

from app import a3_m4_bridge as bridge
from app.database import get_db
from app.evidence_v41 import ALGORITHM, analyze
from app.m2 import DEMO_INSTITUTION, DEMO_SCOPE
from app.models import (
    CatalogPosition,
    CatalogSource,
    CatalogVersion,
    MatchCandidate,
    MatchRun,
    TechnicalEvidence,
    User,
    WorkItem,
)
from app.revisions import effective_item, frozen_snapshot
from app.technical_analysis import batch_technical_review as pilot


def setup(client, auth, monkeypatch, m4=True):
    (pid, iid, _base, rows, _body), record = saved(client, auth)
    monkeypatch.setattr(bridge, "read_analysis", pilot.read_analysis)
    item_id = rows[0]["work_item_id"]
    url = f"/api/projects/{pid}/a3/reviews/{record['record']['id']}/m4-link?work_item_id={item_id}"
    ids = {}
    if m4:
        gen = client.app.dependency_overrides[get_db]()
        db = next(gen)
        user = db.scalar(select(User))
        src = CatalogSource(organization_id=user.organization_id, institution=DEMO_INSTITUTION,
            license_status="verified", permission_scope=DEMO_SCOPE, license_evidence="Synthetic bridge fixture")
        db.add(src); db.flush()
        ver = CatalogVersion(source_id=src.id, year=2026, period="synthetic", sha256="c" * 64)
        db.add(ver); db.flush()
        pos = CatalogPosition(version_id=ver.id, code="15.275.1111", description=TEXT, unit="m²", price=744.50)
        db.add(pos); db.flush()
        run = MatchRun(project_id=pid, import_id=iid, version_id=ver.id, created_by_id=user.id,
            algorithm=ALGORITHM, row_count=2, candidate_count=1)
        db.add(run); db.flush()
        item = db.get(WorkItem, item_id)
        db.add(frozen_snapshot(run.id, effective_item(db, item)))
        candidate = MatchCandidate(run_id=run.id, work_item_id=item_id, position_id=pos.id,
            rank=1, similarity=1, approvable=False)
        db.add(candidate); db.flush()
        proof = analyze(TEXT, "m²", TEXT, "m²", quantity_known=True, review_required=False,
            source_refs={"metraj": {"import_id": iid, "import_sha256": record["report"]["import_source"]["sha256"],
                "source_row": item.source_row, "work_item_id": item_id, "revision_id": None},
                "catalog": {"version_id": ver.id, "version_sha256": ver.sha256,
                    "position_id": pos.id, "position_code": pos.code}})
        db.add(TechnicalEvidence(candidate_id=candidate.id, schema_version=proof["schema"],
            status=proof["status"], evidence_sha256=proof["evidence_sha256"], payload_json=json.dumps(proof)))
        db.commit()
        ids = {"version": ver.id, "position": pos.id, "candidate": candidate.id, "run": run.id}
        gen.close()
    return pid, url, record, rows, ids


def test_identity_link_does_not_override_multilayer_m4_gate(client, auth, source, monkeypatch):
    _pid, url, record, rows, ids = setup(client, auth, monkeypatch)
    response = client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["link_status"] == "linked"
    assert data["ready_for_m4_review"] is False
    assert "M4_EXISTING_GATES_PASS" in data["flags"]
    assert data["m4_candidate"]["candidate_id"] == ids["candidate"]
    assert data["work_item_id"] == rows[0]["work_item_id"]
    assert data["snapshot_sha256"] == record["record"]["snapshot_sha256"]
    assert data["approval_allowed"] is False and data["engineering_approval"] is False
    assert response.headers["cache-control"] == "private, no-store"


def test_no_run_is_explicit_and_does_not_create_one(client, auth, source, monkeypatch):
    _pid, url, _record, _rows, _ids = setup(client, auth, monkeypatch, m4=False)
    data = client.get(url, headers=auth).json()
    assert data["link_status"] == "unresolved" and data["m4_candidate"] is None
    assert "M4_RUN_FOUND" in data["flags"]


@pytest.mark.parametrize("change,flag", [("description", "CATALOG_PDF_TEXT_MATCH"),
    ("unit", "CATALOG_PDF_UNIT_MATCH"), ("year", "CATALOG_PDF_YEAR_MATCH"),
    ("code", "M4_CANDIDATE_UNIQUE"), ("duplicate", "M4_CANDIDATE_UNIQUE")])
def test_same_code_is_not_enough(client, auth, source, monkeypatch, change, flag):
    _pid, url, _record, _rows, ids = setup(client, auth, monkeypatch)
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    pos = db.get(CatalogPosition, ids["position"])
    if change == "description": pos.description = TEXT.replace("350 kg", "300 kg")
    elif change == "unit": pos.unit = "m³"
    elif change == "year": db.get(CatalogVersion, ids["version"]).year = 2025
    elif change == "code": pos.code = "OTHER"
    else:
        db.add(MatchCandidate(run_id=ids["run"], position_id=pos.id, rank=2, similarity=1,
            work_item_id=db.get(MatchCandidate, ids["candidate"]).work_item_id, approvable=False))
    db.commit(); gen.close()
    response = client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    assert flag in response.json()["flags"]
    assert response.json()["link_status"] == "unresolved"
    assert response.json()["ready_for_m4_review"] is False


def test_tampered_m4_evidence_is_not_shown(client, auth, source, monkeypatch):
    _pid, url, _record, _rows, ids = setup(client, auth, monkeypatch)
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    entry = db.scalar(select(TechnicalEvidence).where(TechnicalEvidence.candidate_id == ids["candidate"]))
    entry.evidence_sha256 = "0" * 64
    db.commit(); gen.close()
    assert client.get(url, headers=auth).status_code == 409


def test_revision_invalidates_link_without_rewriting_saved_review(client, auth, source, monkeypatch):
    pid, url, _record, rows, _ids = setup(client, auth, monkeypatch)
    revise(client, auth, pid, rows[0])
    data = client.get(url, headers=auth).json()
    assert data["link_status"] == "unresolved"
    assert "A3_REVIEW_CURRENT" in data["flags"]
    assert "M4_EVIDENCE_CURRENT" in data["flags"]
    assert data["ready_for_m4_review"] is False


def test_source_missing_and_rights_revoked_block_readiness(client, auth, source, monkeypatch):
    _pid, url, _record, _rows, ids = setup(client, auth, monkeypatch)
    source.unlink()
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    ver = db.get(CatalogVersion, ids["version"])
    db.get(CatalogSource, ver.source_id).license_status = "rejected"
    db.commit(); gen.close()
    data = client.get(url, headers=auth).json()
    assert "A3_REVIEW_CURRENT" in data["flags"]
    assert "M4_CATALOG_RIGHTS_ACTIVE" in data["flags"]
    assert data["ready_for_m4_review"] is False


def test_auth_and_row_scope(client, auth, source, monkeypatch):
    pid, url, _record, _rows, _ids = setup(client, auth, monkeypatch)
    assert client.get(url).status_code == 401
    other = make_auth(client, "Bridge outsider", "bridge-other@example.com")
    assert client.get(url, headers=other).status_code == 404
    assert client.get(url.replace(pid, str(uuid4())), headers=auth).status_code == 404
    assert client.get(url.split('?')[0]+f'?work_item_id={uuid4()}', headers=auth).status_code == 404


def test_link_check_is_select_only(client, auth, source, monkeypatch):
    _pid, url, _record, _rows, _ids = setup(client, auth, monkeypatch)
    gen = client.app.dependency_overrides[get_db](); db = next(gen); engine = db.get_bind(); gen.close()
    writes = []
    def capture(_c, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")): writes.append(sql)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = client.get(url, headers=auth)
        assert result.status_code == 200, result.text
    finally: event.remove(engine, "before_cursor_execute", capture)
    assert writes == []
    assert client.post(url, headers=auth, json={"approval_allowed": True}).status_code == 405


def test_self_consistent_but_wrong_evidence_references_are_unresolved(client, auth, source, monkeypatch):
    _pid, url, _record, _rows, ids = setup(client, auth, monkeypatch)
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    entry = db.scalar(select(TechnicalEvidence).where(TechnicalEvidence.candidate_id == ids["candidate"]))
    proof = json.loads(entry.payload_json)
    proof["source_refs"]["catalog"]["position_id"] = str(uuid4())
    import hashlib
    proof.pop("evidence_sha256")
    proof["evidence_sha256"] = hashlib.sha256(json.dumps(proof, ensure_ascii=False, sort_keys=True,
                                                       separators=(",", ":")).encode()).hexdigest()
    entry.payload_json = json.dumps(proof)
    entry.evidence_sha256 = proof["evidence_sha256"]
    db.commit(); gen.close()
    data = client.get(url, headers=auth).json()
    assert "M4_EVIDENCE_REFERENCES_MATCH" in data["flags"]
    assert data["link_status"] == "unresolved" and data["ready_for_m4_review"] is False


def test_new_pdf_cannot_substitute_same_code_in_saved_source(client, auth, source, monkeypatch):
    _pid, url, _record, _rows, _ids = setup(client, auth, monkeypatch)
    original = bridge.read_analysis
    def changed(path):
        data = original(path)
        data["source"]["sha256"] = "e" * 64
        return data
    monkeypatch.setattr(bridge, "read_analysis", changed)
    data = client.get(url, headers=auth).json()
    assert "PDF_SOURCE_REVALIDATED" in data["flags"]
    assert data["link_status"] == "unresolved"


def test_prior_assessment_is_not_lost_or_promoted_to_m4_approval(client, auth, source, monkeypatch):
    from app.a3_assessment_store import TechnicalReviewAssessment
    _pid, url, record, rows, _ids = setup(client, auth, monkeypatch)
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    user = db.scalar(select(User))
    db.add(TechnicalReviewAssessment(organization_id=user.organization_id, project_id=_pid,
        record_id=record["record"]["id"], work_item_id=rows[0]["work_item_id"], created_by_id=user.id,
        candidate_code="15.275.1111", snapshot_sha256=record["record"]["snapshot_sha256"],
        action="reject_candidate", reason="Independent synthetic rejection", previous_key="initial",
        request_key=str(uuid4()), request_sha256="a" * 64))
    db.commit(); gen.close()
    data = client.get(url, headers=auth).json()
    assert "A3_ASSESSMENT_REQUIRES_REVIEW" in data["flags"]
    assert data["m4_candidate"]["latest_assessment"] == "reject_candidate"
    assert data["approval_allowed"] is False and data["ready_for_m4_review"] is False
