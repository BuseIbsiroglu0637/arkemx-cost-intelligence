"""A3.45: no automatic approvals, no zero-TL pending lines or double markup."""
import json
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace

from sqlalchemy import select

from app import a318_pdf_api, a345_cost_preview
from app.a330_review_store import ProposedAnalysisRevision, EngineeringSignoff
from app.database import get_db
from app.models import User, WorkItem
from test_a318_pdf_api import setup, positions, upload
from test_api import register


def prepared(client, auth, monkeypatch):
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    pid, iid = setup(client, auth, "Safe partial-cost analysis")
    source = upload(client, pid, auth)
    assert source.status_code == 201, source.text
    return pid, iid, source.json()["sha256"]


def test_unsigned_pdf_matches_never_generate_cost(client, auth, monkeypatch):
    pid, iid, digest = prepared(client, auth, monkeypatch)
    url = f"/api/projects/{pid}/a345/imports/{iid}/cost-preview"
    res = client.get(url, headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["read_only"] is True and data["creates_estimate"] is False
    assert data["source_pdf_sha256"] == digest
    assert data["total_rows"] == 2
    assert data["included_count"] == 0
    assert data["pending_count"] == 2
    assert data["partial_total"] == "0.00"
    assert all(row["amount"] is None for row in data["pending"])
    assert res.headers["cache-control"] == "private, no-store"

    unauthorized = register(client, "Other company", "a345tenant@example.com")
    assert client.get(url, headers=unauthorized).status_code == 404


def test_valid_signed_one_of_two_rows_is_priced_once_and_others_remain_pending(
    client, auth, monkeypatch,
):
    pid, iid, digest = prepared(client, auth, monkeypatch)
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = db.scalar(select(User).where(User.email == "demo@example.com"))
    item = db.scalar(select(WorkItem).where(
        WorkItem.import_id == iid, WorkItem.source_row == 2
    ))
    assert Decimal(str(item.quantity)) == Decimal("245.5000")
    fp = "a" * 64
    revision = ProposedAnalysisRevision(
        organization_id=user.organization_id, project_id=pid, import_id=iid,
        work_item_id=item.id, version=1, candidate_code=positions()[0].id,
        analysis_pdf_sha256=digest, source_fingerprint=fp,
        items_json=json.dumps([{
            "code":"10.100.0001", "description":"Test malzemesi",
            "unit":"m²", "quantity":"1", "unit_price":"100",
            "amount":"100.00", "entry_type":"user_proposal",
        }]),
        proposed_amount="125.00", reason="Synthetic regression test",
        created_by_id=user.id, request_key=str(uuid4()), request_hash="b"*64,
    )
    db.add(revision)
    db.flush()
    signoff = EngineeringSignoff(
        organization_id=user.organization_id, project_id=pid, import_id=iid,
        work_item_id=item.id, analysis_revision_id=revision.id,
        source_fingerprint=fp, action="approve",
        reason="Synthetic qualified review",
        signed_by_id=user.id, request_key=str(uuid4()), request_hash="c"*64,
    )
    db.add(signoff)
    db.commit()
    db_gen.close()

    # Deterministic reviewed evidence fixture; the real endpoint normally
    # recalculates this from the saved source and independent specification.
    monkeypatch.setattr(a345_cost_preview, "_signed_review_current", lambda *a: True)
    monkeypatch.setattr(
        a345_cost_preview, "verified_source",
        lambda *args: (
            {"status": "documented_for_review"}, fp, positions()[0], digest
        ),
    )
    url = f"/api/projects/{pid}/a345/imports/{iid}/cost-preview"
    res = client.get(url, headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["included_count"] == 1
    assert data["pending_count"] == 1
    assert data["is_partial"] is True
    assert data["partial_total"] == "30687.50"
    assert data["included"][0]["unit_price"] == "125.00"
    assert data["included"][0]["amount"] == "30687.50"
    assert data["pending"][0]["amount"] is None
    assert data["included"][0]["analysis_revision_id"]

    # Revoke the reviewer's current qualification: the same record may no
    # longer silently generate a cost line.
    monkeypatch.setattr(a345_cost_preview, "_signed_review_current", lambda *a: False)
    revoked = client.get(url, headers=auth).json()
    assert revoked["included_count"] == 0
    assert revoked["pending_count"] == 2
    assert revoked["partial_total"] == "0.00"


def test_stored_analysis_price_tampering_is_detected_without_double_markup():
    correct = SimpleNamespace(
        items_json=json.dumps([{
            "code":"10.100.0001", "description":"Cimento", "unit":"kg",
            "quantity":"2.0000", "unit_price":"100.00",
            "amount":"200.00", "entry_type":"user_proposal",
        }]),
        proposed_amount="250.00",
    )
    assert a345_cost_preview._validated_analysis_price(correct) == Decimal("250.00")
    tampered = SimpleNamespace(
        items_json=correct.items_json, proposed_amount="251.00",
    )
    import pytest
    with pytest.raises(ValueError):
        a345_cost_preview._validated_analysis_price(tampered)
