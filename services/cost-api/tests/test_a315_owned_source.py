"""Owned fixtures never promote real catalog rights or invent official prices."""
import json
from uuid import UUID

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select

from app import a3_m4_bridge as bridge
from app.a3_batch_review import BatchReviewRequest, SelectedRow, preview_batch_review
from app.a3_owned_pilot import setup_owned_pilot
from app.a3_review_records import view
from app.a3_review_store import TechnicalReviewRecord
from app.database import get_db
from app.models import (
    CatalogImport,
    CatalogPosition,
    CatalogReviewEvent,
    CatalogSource,
    CatalogVersion,
    MatchDecision,
    Project,
    User,
    WorkItem,
)
from app.technical_analysis import batch_technical_review as pilot
from app.technical_analysis.owned_synthetic_source import CODE, TEXT, fixture_sha256


def prepare(client, auth, monkeypatch):
    monkeypatch.delenv("ARKEMX_ANALYSIS_PDF", raising=False)
    def no_pdf(*_args):
        raise AssertionError("Owned fixture must not read a real PDF")
    monkeypatch.setattr(pilot, "read_analysis", no_pdf)
    monkeypatch.setattr(bridge, "read_analysis", no_pdf)
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    user = db.scalar(select(User))
    result = setup_owned_pilot(db, user)
    return gen, db, user, result


def test_owned_pilot_end_to_end_without_pdf_or_price(client, auth, monkeypatch):
    gen, db, user, result = prepare(client, auth, monkeypatch)
    record = db.get(TechnicalReviewRecord, result["record_id"])
    saved = view(record, db)
    row = saved["report"]["rows"][0]
    assert row["candidate_code"] == CODE
    assert row["technical_status"] == "checked_features_match"
    assert row["price_source_status"] == "not_applicable"
    assert row["source_price"] is None
    assert row["technical_source"]["kind"] == "synthetic_owned"
    assert row["technical_source"]["official"] is False
    assert row["technical_source"]["sha256"] == fixture_sha256()
    assert row["source_verification_status"] == "verified"
    assert row["source_rights_status"] == "owned_synthetic_fixture"
    assert row["engineering_status"] == "not_approved"
    assert saved["currentness"]["status"] == "unchanged"
    response = bridge.inspect_link(UUID(result["project_id"]), UUID(record.id),
        UUID(row["identity"]["work_item_id"]), Response(), user, db)
    assert response["link_status"] == "linked"
    assert response["source_kind"] == "synthetic_owned"
    assert response["ready_for_m4_review"] is False
    assert "M4_EXISTING_GATES_PASS" in response["flags"]
    assert response["approval_allowed"] is False
    assert db.scalar(select(MatchDecision)) is None
    gen.close()


def test_setup_rerun_reuses_same_isolated_project_import_and_review(client, auth, monkeypatch):
    gen, db, user, first = prepare(client, auth, monkeypatch)
    second = setup_owned_pilot(db, user)
    assert second == first
    assert len(db.scalars(select(Project)).all()) == 1
    assert len(db.scalars(select(TechnicalReviewRecord)).all()) == 1
    assert db.scalar(select(CatalogImport)) is None
    gen.close()


def test_real_pending_catalog_and_existing_project_are_untouched(client, auth, monkeypatch):
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    user = db.scalar(select(User))
    project = Project(organization_id=user.organization_id, created_by_id=user.id, name="Keep existing project")
    src = CatalogSource(organization_id=user.organization_id, institution="CSB", license_status="pending")
    db.add_all([project, src]); db.flush()
    ver = CatalogVersion(source_id=src.id, year=2026, period="2026-01-PDF-PILOT", sha256="b" * 64)
    db.add(ver); db.flush()
    pos = CatalogPosition(version_id=ver.id, code="15.275.1111", description="Real source stays pending", unit="m²", price=744.50)
    imported = CatalogImport(organization_id=user.organization_id, source_id=src.id, version_id=ver.id,
        sha256=ver.sha256, filename="real.csv", year=2026, period=ver.period, row_count=1,
        status="pending", created_by_id=user.id)
    db.add_all([pos, imported]); db.commit()
    real_id, project_id = imported.id, project.id
    setup_owned_pilot(db, user)
    db.expire_all()
    assert db.get(CatalogImport, real_id).status == "pending"
    assert db.get(CatalogImport, real_id).approval_evidence is None
    assert db.get(CatalogSource, src.id).license_status == "pending"
    assert db.get(Project, project_id).name == "Keep existing project"
    assert db.scalar(select(CatalogReviewEvent)) is None
    assert db.scalar(select(CatalogPosition).where(CatalogPosition.code == "15.275.1111")).description == "Real source stays pending"
    gen.close()


def test_real_candidate_is_not_relabelled_as_owned_fixture(client, auth, monkeypatch):
    gen, db, user, result = prepare(client, auth, monkeypatch)
    item = db.scalar(select(WorkItem))
    report = preview_batch_review(UUID(result["project_id"]), UUID(result["import_id"]),
        BatchReviewRequest(rows=[SelectedRow(work_item_id=UUID(item.id), candidate_code="15.275.1111")]),
        Response(), user, db)
    row = report["rows"][0]
    assert row["technical_source"] is None
    assert row["source_rights_status"] == "not_assessed"
    assert row["price_source_status"] == "not_configured"
    assert row["technical_status"] == "review_required"
    assert row["approval_allowed"] is False
    gen.close()


def test_synthetic_source_tampering_invalidates_history_even_with_consistent_checksum(client, auth, monkeypatch):
    from app.a3_review_records import canonical, digest
    gen, db, user, result = prepare(client, auth, monkeypatch)
    row = db.get(TechnicalReviewRecord, result["record_id"])
    payload = json.loads(row.snapshot_json)
    payload["report"]["rows"][0]["technical_source"]["description"] = TEXT.replace("320 kg", "330 kg")
    row.snapshot_json = canonical(payload); row.snapshot_sha256 = digest(payload)
    db.commit()
    data = view(row, db)
    assert data["currentness"]["status"] == "changed"
    assert "SYNTHETIC_SOURCE_CHANGED" in data["currentness"]["flags"]
    gen.close()


@pytest.mark.parametrize("change", ["description", "price", "rights"])
def test_setup_never_overwrites_changed_fixture(client, auth, monkeypatch, change):
    gen, db, user, result = prepare(client, auth, monkeypatch)
    position = db.scalar(select(CatalogPosition).where(CatalogPosition.code == CODE))
    if change == "description": position.description = "Changed test description"
    elif change == "price": position.price = 123
    else:
        ver = db.get(CatalogVersion, position.version_id)
        db.get(CatalogSource, ver.source_id).license_status = "rejected"
    db.commit()
    with pytest.raises(ValueError): setup_owned_pilot(db, user)
    db.expire_all()
    if change == "description": assert db.get(CatalogPosition, position.id).description == "Changed test description"
    if change == "price": assert db.get(CatalogPosition, position.id).price == 123
    gen.close()


def test_non_admin_cannot_create_owned_pilot(client, auth):
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    user = db.scalar(select(User)); user.role = "viewer"; db.commit()
    with pytest.raises(HTTPException) as exc: setup_owned_pilot(db, user)
    assert exc.value.status_code == 403
    assert db.scalar(select(Project)) is None
    gen.close()


def test_real_pdf_verification_does_not_imply_usage_permission(client, auth, monkeypatch, tmp_path):
    import hashlib

    from test_a312_review_records import saved
    path = tmp_path / "synthetic-real-pdf-adapter-fixture.pdf"
    path.write_bytes(b"synthetic document fixture")
    monkeypatch.setenv("ARKEMX_ANALYSIS_PDF", str(path))
    monkeypatch.setattr(pilot, "read_analysis", lambda _path: {
        "position_code": "15.275.1111", "unit": "m²", "read_only": True, "approval_allowed": False,
        "technical_description": {"quote": "250 kg cimento dozlu 20 mm kaba siva uzerine 350 kg cimento dozlu 8 mm ince siva"},
        "totals": {"total": "744.50", "currency": "TRY"},
        "source": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pdf_page": 423}})
    _data, record = saved(client, auth)
    row = record["report"]["rows"][0]
    assert row["technical_source"]["kind"] == "analysis_pdf"
    assert row["source_verification_status"] == "verified"
    assert row["source_rights_status"] == "not_assessed"
    assert row["engineering_status"] == "not_approved"
    assert row["source_price"]["value"] == "744.50"
    assert row["approval_allowed"] is False


def test_owned_plaster_preserves_existing_builtin_demo_catalog(client, auth):
    from app.m2 import seed_demo, synthetic_version
    gen = client.app.dependency_overrides[get_db](); db = next(gen)
    user = db.scalar(select(User))
    original = seed_demo(user, db)
    setup_owned_pilot(db, user)
    assert synthetic_version(db, user.organization_id).id == original["version_id"]
    assert len(db.scalars(select(CatalogPosition).where(CatalogPosition.version_id == original["version_id"])).all()) == 5
    assert len(db.scalars(select(CatalogSource)).all()) == 1
    gen.close()
