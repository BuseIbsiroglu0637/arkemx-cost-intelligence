"""A3.24: one meaningful ceramic-finish question; never silent approval."""
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from openpyxl import Workbook

from app import a318_pdf_api
from app.a318_pdf_engine import PdfPosition
from app.a320_smart_matching import find_pdf_candidates
from app.a324_ceramic_features import ceramic_features, ceramic_finish_conflict, ceramic_question

METRAJ = "60x60 cm porselen seramik zemin kaplaması"
FINISHES = [
    ("15.390.1008", "60 x 60 cm rektifiyeli, I.kalite, mat, sırsız porselen karo ile 3 mm derz aralıklı döşeme kaplaması", 683),
    ("15.385.1008", "60 x 60 cm I.kalite, beyaz, sırlı porselen karo ile 3 mm derz aralıklı döşeme kaplaması", 659),
    ("15.385.1028", "60 x 60 cm I.kalite, renkli, sırlı porselen karo ile 3 mm derz aralıklı döşeme kaplaması", 665),
]


def pdf_positions():
    return tuple(PdfPosition(
        id=code, description=description, unit="m²", price=Decimal("100"),
        price_verified=True, pdf_page=page, ingredients=(), scope=description,
    ) for code, description, page in FINISHES)


def _candidates():
    return [
        {"code": code, "description": text, "source_page": page,
         "technical_status": "review"} for code, text, page in FINISHES
    ]


def test_pdf_finish_features_are_distinct():
    assert ceramic_features(FINISHES[0][1]) == {
        "glaze": "sirsiz", "color": None,
        "surface": "mat", "rectified": "rektifiyeli",
    }
    assert ceramic_features(FINISHES[1][1])["color"] == "beyaz"
    assert ceramic_features(FINISHES[1][1])["glaze"] == "sirli"
    assert ceramic_features(FINISHES[2][1])["color"] == "renkli"


def test_question_has_three_real_pdf_codes_and_no_approval():
    question = ceramic_question(METRAJ, _candidates())
    assert question is not None
    assert question["prompt"] == "Projede hangi porselen seramik türü belirtiliyor?"
    assert question["approval_allowed"] is False
    assert question["cost_allowed"] is False
    assert {o["code"] for o in question["options"]} == {p[0] for p in FINISHES}
    assert len({o["label"] for o in question["options"]}) == 3
    assert all(o["source_page"] in (659, 665, 683) for o in question["options"])


def test_explicit_glazed_white_excludes_opposing_finishes():
    metraj = "60x60 cm beyaz sırlı porselen karo zemin kaplaması"
    assert ceramic_finish_conflict(metraj, FINISHES[0][1])
    assert ceramic_finish_conflict(metraj, FINISHES[2][1])
    assert not ceramic_finish_conflict(metraj, FINISHES[1][1])
    item = SimpleNamespace(raw_description=metraj, normalized_unit="m²",
                           quantity=Decimal("42.75"), review_required=False)
    suggestions = find_pdf_candidates(item, pdf_positions())
    assert [s["position_id"] for s in suggestions] == ["15.385.1008"]


def test_unknown_finish_must_not_be_made_up():
    assert ceramic_question(METRAJ, []) is None
    assert ceramic_question(METRAJ, [_candidates()[0]]) is None
    twice = [_candidates()[0], {**_candidates()[1], "description": FINISHES[0][1]}]
    assert ceramic_question(METRAJ, twice) is None


def test_one_explicit_choice_does_not_create_engineering_approval():
    selected = ceramic_question(METRAJ, _candidates())["options"][0]
    assert selected["code"] in {p[0] for p in FINISHES}
    assert "approval_allowed" not in selected
    assert "cost_allowed" not in selected


def test_api_serves_one_question_and_persists_only_candidate(client, auth, monkeypatch):
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: pdf_positions())
    project = client.post("/api/projects", headers=auth, json={"name": "A324 clarification"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    wb = Workbook()
    ws = wb.active
    ws.append(["İmalat", "Miktar", "Birim"])
    ws.append([METRAJ, 42.75, "m²"])
    out = BytesIO()
    wb.save(out)
    imp = client.post(f"/api/projects/{pid}/imports", headers=auth,
                      files={"file": ("metraj.xlsx", out.getvalue())})
    assert imp.status_code == 201, imp.text
    iid = imp.json()["id"]
    uploaded = client.post(f"/api/projects/{pid}/a318/source", headers=auth,
                           data={"rights_confirmed": "true"},
                           files={"file": ("analiz.pdf", b"%PDF-" + b"A" * 1700, "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    url = f"/api/projects/{pid}/a318/imports/{iid}/suggestions"
    response = client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["approval_allowed"] is False and data["cost_allowed"] is False
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    question = row["clarification"]
    assert question is not None, row
    assert len(question["options"]) == 3
    assert row["saved_selection"] is None
    assert row["triage"]["group"] == "needs_info"
    assert row["triage"]["engineering_approved"] is False
    assert row["triage"]["cost_allowed"] is False
    chosen = question["options"][1]["code"]
    saved = client.post(
        f"/api/projects/{pid}/a318/imports/{iid}/items/{row['work_item_id']}/candidate",
        headers=auth,
        json={"position_code": chosen,
              "expected_revision_id": row["revision_id"],
              "expected_pdf_sha256": uploaded.json()["sha256"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["engineering_approved"] is False
    assert saved.json()["cost_allowed"] is False
    again = client.get(url, headers=auth).json()["rows"][0]
    assert again["saved_selection"]["current"] is True
    assert again["saved_selection"]["code"] == chosen
    assert again["clarification"] is not None
    assert again["clarification"]["approval_allowed"] is False
    assert again["triage"]["group"] == "needs_info"
    assert "Seramik türü (mimari şartname)" in again["triage"]["missing_fields"]
