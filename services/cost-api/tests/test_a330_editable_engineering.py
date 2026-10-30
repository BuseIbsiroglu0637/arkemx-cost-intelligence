"""A3.30 editable *proposals* and separate human engineering role checks."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app import a330_editable_analysis as service
from app.a318_pdf_engine import PdfPosition
from app.a330_review_store import (
    EngineeringSignoff, ProposedAnalysisRevision, VerifiedEngineeringReviewer,
)
from app.database import get_db
from app.models import User
from test_a327_decisions import recorded_project


def setup_project(client, auth, monkeypatch):
    pid, iid, items = recorded_project(client, auth, monkeypatch)
    source = PdfPosition(
        id="15.225.1004",
        description="10 cm gazbeton duvar 2,50 N/mm2 400 kg/m3",
        unit="m²", price=Decimal("723.73"), price_verified=True,
        pdf_page=255, scope="Gercek PDF sabit kaynak, degistirilemez",
        ingredients=(
            {"code": "10.100.01", "description": "Gazbeton", "unit": "m²",
             "quantity": "1,03", "unit_price": "231,10", "amount": "238,03"},
            {"code": "10.100.02", "description": "Isci", "unit": "sa",
             "quantity": "0,63", "unit_price": "205,00", "amount": "129,15"},
        ),
    )
    monkeypatch.setattr(service, "read_analysis", lambda user: ("a" * 64, (source,)))
    url = f"/api/projects/{pid}/a330/imports/{iid}/items/{items[0]}"
    return pid, iid, items[0], url


def state(client, auth, url):
    result = client.get(url + "/analysis", headers=auth)
    assert result.status_code == 200, result.text
    return result.json()


def proposal(before, items=None, **changes):
    data = {
        "items": items or [
            {"code": "10.100.01", "description": "Gazbeton", "unit": "m²",
             "quantity": "1,03", "unit_price": "231,10"},
            {"code": "10.100.02", "description": "Isci", "unit": "sa",
             "quantity": "0,63", "unit_price": "205,00"},
        ],
        "reason": "Kapsami ve girilen fiyatlari proje teklifinde tekrar inceleyecegiz.",
        "expected_source_fingerprint": before["source_fingerprint"],
        "expected_previous_revision_id": (before["latest_revision"] or {}).get("id"),
        "request_key": str(uuid4()),
    }
    return {**data, **changes}


def test_original_pdf_read_only_and_proposal_add_remove_persists(client, auth, monkeypatch):
    pid, iid, item, url = setup_project(client, auth, monkeypatch)
    before = state(client, auth, url)
    assert before["read_only_source"] is True
    assert before["engineering"]["engineering_approved"] is False
    assert before["engineering"]["reviewer_eligible"] is False
    original = before["source_inputs"]
    saved = client.post(url + "/analysis/revisions", headers=auth, json=proposal(before, [
        {"code": "10.100.01", "description": "Gazbeton", "unit": "m²",
         "quantity": "1,03", "unit_price": "231,10"},
        {"code": "15.100.99", "description": "El ile eklenen iscilik", "unit": "sa",
         "quantity": "2", "unit_price": "50,00"},
    ]))
    assert saved.status_code == 201, saved.text
    recorded = saved.json()
    assert recorded["version"] == 1
    assert recorded["proposed_amount"] == "422.54"
    refreshed = state(client, auth, url)
    assert refreshed["source_inputs"] == original
    assert refreshed["latest_revision"]["id"] == recorded["id"]
    assert refreshed["latest_revision"]["items"][1]["code"] == "15.100.99"
    assert refreshed["latest_revision"]["items"][1]["amount"] == "100.00"
    assert refreshed["engineering"]["engineering_approved"] is False
    assert refreshed["engineering"]["cost_allowed"] is False


def test_admin_cannot_engineer_approve_even_with_source_evidence(client, auth, monkeypatch):
    _, _, _, url = setup_project(client, auth, monkeypatch)
    before = state(client, auth, url)
    saved = client.post(url + "/analysis/revisions", headers=auth, json=proposal(before))
    assert saved.status_code == 201
    actual = state(client, auth, url)
    attempt = {
        "action": "approve", "reason": "Kaynak, poz, iscilik ve malzeme kapsamlarini inceledim.",
        "expected_source_fingerprint": actual["source_fingerprint"],
        "expected_analysis_revision_id": actual["latest_revision"]["id"],
        "expected_previous_signoff_id": None, "request_key": str(uuid4()),
        "attestation": "I_AM_VERIFIED_ENGINEER_AND_REVIEWED_EVIDENCE",
    }
    denied = client.post(url + "/engineering/signoff", headers=auth, json=attempt)
    assert denied.status_code == 403
    assert state(client, auth, url)["engineering"]["engineering_approved"] is False


def test_qualified_engineer_can_sign_current_revision_without_cost_unlock(
    client, auth, monkeypatch,
):
    _, _, _, url = setup_project(client, auth, monkeypatch)
    before = state(client, auth, url)
    assert client.post(url + "/analysis/revisions", headers=auth,
                       json=proposal(before)).status_code == 201
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    admin = db.scalar(select(User))
    engineer = User(
        organization_id=admin.organization_id, email="verified-eng@example.com",
        password_hash=admin.password_hash, role="engineer",
    )
    db.add(engineer)
    db.flush()
    db.add(VerifiedEngineeringReviewer(
        user_id=engineer.id, verified_by_id=admin.id,
        verification_reference="Independently checked professional license",
        verified_at=datetime.now(timezone.utc),
    ))
    db.commit()
    gen.close()
    login = client.post("/api/auth/login", json={
        "email": engineer.email, "password": "secure-pilot-password",
    })
    assert login.status_code == 200, login.text
    engineer_auth = {"Authorization": "Bearer " + login.json()["access_token"]}
    actual = state(client, engineer_auth, url)
    assert actual["engineering"]["reviewer_eligible"] is True
    request = {
        "action": "approve", "reason": "Dayanim yogunluk, poz kapsami ve degisiklikleri inceledim.",
        "expected_source_fingerprint": actual["source_fingerprint"],
        "expected_analysis_revision_id": actual["latest_revision"]["id"],
        "expected_previous_signoff_id": None, "request_key": str(uuid4()),
        "attestation": "I_AM_VERIFIED_ENGINEER_AND_REVIEWED_EVIDENCE",
    }
    signed = client.post(url + "/engineering/signoff", headers=engineer_auth, json=request)
    assert signed.status_code == 201, signed.text
    assert signed.json()["engineering_approved"] is True
    assert signed.json()["cost_allowed"] is False
    assert state(client, auth, url)["engineering"]["engineering_approved"] is True

    # Any later edit invalidates an approval for the previous analysis revision.
    current = state(client, auth, url)
    updated = client.post(url + "/analysis/revisions", headers=auth, json=proposal(
        current, reason="Teknik analiz degistirildi, yeni muhendis imzasi gerekir.",
    ))
    assert updated.status_code == 201, updated.text
    assert state(client, auth, url)["engineering"]["engineering_approved"] is False
    assert state(client, auth, url)["engineering"]["cost_allowed"] is False


def test_stale_source_and_bad_decimals_rejected_without_db_changes(client, auth, monkeypatch):
    _, _, _, url = setup_project(client, auth, monkeypatch)
    before = state(client, auth, url)
    malformed = client.post(url + "/analysis/revisions", headers=auth, json=proposal(
        before, items=[{"code": "15.999.1111", "description": "Bilinmeyen girdi",
                        "unit": "sa", "quantity": "1", "unit_price": "-50"}],
    ))
    assert malformed.status_code == 422
    stale = client.post(url + "/analysis/revisions", headers=auth, json=proposal(
        before, expected_source_fingerprint="b" * 64,
    ))
    assert stale.status_code == 409
    assert state(client, auth, url)["latest_revision"] is None
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    assert db.scalar(select(ProposedAnalysisRevision)) is None
    assert db.scalar(select(EngineeringSignoff)) is None
    gen.close()
