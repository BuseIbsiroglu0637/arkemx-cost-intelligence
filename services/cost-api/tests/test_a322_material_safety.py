"""A3.22: reject wrong material surface finishes before selection or costing."""
from io import BytesIO
from decimal import Decimal
from types import SimpleNamespace

from openpyxl import Workbook
from sqlalchemy import select

from app import a318_pdf_api
from app.a318_pdf_engine import PdfPosition
from app.a320_smart_matching import find_pdf_candidates
from app.database import get_db
from app.matching import evaluate, family
from app.models import PdfCandidateSelection
from app.technical import compare

CERAMIC = "60x60 cm porselen seramik zemin kaplaması"
POLYURETHANE = "2,5 mm kalınlıkta self leveling Poliüretan esaslı zemin kaplaması imalatı"
TILE = "60x60 cm porselen seramik karo ile zemin kaplaması"


def pdf_position(code: str, description: str, page: int) -> PdfPosition:
    return PdfPosition(
        id=code, description=description, unit="m²",
        price=Decimal("100"), price_verified=True, pdf_page=page,
        ingredients=(), scope="Sentetik test kapsamı",
    )


def source_row():
    return SimpleNamespace(
        id="test-row", source_row=2, raw_description=CERAMIC,
        quantity=Decimal("42.75"), normalized_unit="m²", review_required=False,
    )


def test_polyurethane_is_not_a_ceramic_candidate_even_with_shared_floor_words():
    metraj = source_row()
    wrong = pdf_position("15.190.1012", POLYURETHANE, 275)
    right = pdf_position("15.385.1008", TILE, 412)
    assert family(CERAMIC) == "seramik"
    assert family("porselen karo") == "seramik"
    assert family(POLYURETHANE) == "poliuretan"
    assert evaluate(metraj, wrong) is None
    assert compare(CERAMIC, "m²", POLYURETHANE, "m²")["status"] == "blocked"
    result = find_pdf_candidates(metraj, [wrong, right])
    assert [row["position_id"] for row in result] == [right.id]


def test_generic_floor_finish_does_not_pass_as_ceramic():
    metraj = source_row()
    unspecified = pdf_position("15.190.1013", "Zemin kaplaması yapılması", 275)
    assert evaluate(metraj, unspecified) is None
    assert find_pdf_candidates(metraj, [unspecified]) == []


def test_wrong_tile_size_is_not_accepted():
    metraj = source_row()
    other = pdf_position("15.385.1007", "30x30 cm porselen seramik karo zemin kaplama", 412)
    assert compare(CERAMIC, "m²", other.description, "m²")["status"] == "blocked"


def _prepared_pdf(client, auth, monkeypatch):
    choices = (
        pdf_position("15.190.1012", POLYURETHANE, 275),
        pdf_position("15.385.1008", TILE, 412),
    )
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: choices)
    project = client.post("/api/projects", headers=auth, json={"name": "Material gate pilot"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["İmalat", "Miktar", "Birim"])
    sheet.append([CERAMIC, 42.75, "m²"])
    stream = BytesIO()
    workbook.save(stream)
    imported = client.post(
        f"/api/projects/{pid}/imports", headers=auth,
        files={"file": ("seramik.xlsx", stream.getvalue())},
    )
    assert imported.status_code == 201, imported.text
    iid = imported.json()["id"]
    uploaded = client.post(
        f"/api/projects/{pid}/a318/source", headers=auth,
        data={"rights_confirmed": "true"},
        files={"file": ("analiz.pdf", b"%PDF-" + b"A" * 1600, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    path = f"/api/projects/{pid}/a318/imports/{iid}"
    suggested = client.get(f"{path}/suggestions", headers=auth)
    assert suggested.status_code == 200, suggested.text
    return path, suggested.json(), uploaded.json()["sha256"]


def test_api_eliminates_polyurethane_and_blocks_unsafe_save(client, auth, monkeypatch):
    path, data, digest = _prepared_pdf(client, auth, monkeypatch)
    assert data["approval_allowed"] is False and data["cost_allowed"] is False
    assert len(data["rows"]) == 1
    item = data["rows"][0]
    assert [candidate["code"] for candidate in item["suggestions"]] == ["15.385.1008"]
    url = f"{path}/items/{item['work_item_id']}/candidate"
    payload = {
        "expected_revision_id": item["revision_id"],
        "expected_pdf_sha256": digest,
    }
    wrong = client.post(url, headers=auth, json={**payload, "position_code": "15.190.1012"})
    assert wrong.status_code == 422
    assert client.get(f"{path}/suggestions", headers=auth).json()["rows"][0]["saved_selection"] is None
    allowed = client.post(url, headers=auth, json={**payload, "position_code": "15.385.1008"})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["engineering_approved"] is False
    assert allowed.json()["cost_allowed"] is False


def test_legacy_unsafe_saved_choice_becomes_stale_without_deletion(client, auth, monkeypatch):
    path, data, digest = _prepared_pdf(client, auth, monkeypatch)
    item = data["rows"][0]
    url = f"{path}/items/{item['work_item_id']}/candidate"
    ok = client.post(url, headers=auth, json={
        "position_code": "15.385.1008",
        "expected_revision_id": item["revision_id"],
        "expected_pdf_sha256": digest,
    })
    assert ok.status_code == 200
    # Simulate an older release where the wrong poz was already saved.
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    saved = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.work_item_id == item["work_item_id"],
    ))
    saved.position_code = "15.190.1012"
    db.commit()
    gen.close()
    refreshed = client.get(f"{path}/suggestions", headers=auth)
    assert refreshed.status_code == 200
    choice = refreshed.json()["rows"][0]["saved_selection"]
    assert choice["current"] is False
    assert choice["stale"] is True
    assert choice["stale_reason"] == "TECHNICAL_CONFLICT"
    assert choice["code"] is None
    # Saved history still exists for evidence; old code cannot become active.
