"""A3.47 — source-bound suggestions; no inferred approval, edited Excel or cost."""
from decimal import Decimal
from dataclasses import replace

from app import a318_pdf_api
from app.a347_fact_completion import _matches, _compare_fields
from app.a318_pdf_engine import PdfPosition
from test_a326_project_evidence import (
    project_with_metraj, pdf, attach,
)
from test_a318_pdf_api import upload
from test_api import register


def url(pid, iid, row_id, code=None):
    path=f"/api/projects/{pid}/a347/imports/{iid}/items/{row_id}/completion"
    return path+(f"?position_code={code}" if code else "")


def gasbeton_poz(strength="2,50", density="400"):
    return PdfPosition(
        id="15.999.1001",
        description=f"10 cm gazbeton duvar {strength} N/mm2 {density} kg/m3 uygulamasi",
        unit="m²", price=Decimal("125.00"), price_verified=True,
        pdf_page=19,
        ingredients=({"code":"10.999.1001","description":"Malzeme", "unit":"m²",
                     "quantity":"1","unit_price":"100","amount":"100"},),
        scope="Sentetik test, malzeme ve iscilik dahil",
    )


def setup_source(client, auth, monkeypatch, *, position=None):
    pid, iid, ids=project_with_metraj(client,auth)
    monkeypatch.setattr(
        a318_pdf_api, "_parse", lambda *_: (position or gasbeton_poz(),)
    )
    result=upload(client,pid,auth)
    assert result.status_code == 201, result.text
    return pid,iid,ids,result.json()["sha256"]


def test_spec_fills_only_missing_fields_with_page_and_source_sha(client, auth, monkeypatch):
    pid,iid,ids,source_sha=setup_source(client,auth,monkeypatch)
    spec=attach(client,auth,pid,pdf(
        "Genel proje sartlari",
        "Gazbeton 10 cm duvar: 2,50 N/mm2 dayanim ve 400 kg/m3 yogunluk.",
    ))
    assert spec.status_code==201, spec.text
    result=client.get(url(pid,iid,ids[0],"15.999.1001"),headers=auth)
    assert result.status_code==200,result.text
    data=result.json()
    assert data["schema"]=="arkemx.a347.completion.v1"
    assert data["status"]=="documented_for_review", data
    assert data["pdf_sha256"]==source_sha
    assert data["spec_sha256"]==spec.json()["sha256"]
    assert data["candidate_found_in_pdf"] is True
    assert data["engineering_approved"] is False and data["cost_allowed"] is False
    facts={v["key"]:v for v in data["fields"]}
    assert facts["gazbeton_strength_n_mm2"]["status"]=="supported"
    assert facts["gazbeton_strength_n_mm2"]["suggested_from_spec"]==2.5
    assert facts["gazbeton_strength_n_mm2"]["page"]==2
    assert facts["gazbeton_density_kg_m3"]["suggested_from_spec"]==400
    assert "dayanim" in facts["gazbeton_strength_n_mm2"]["quote"].lower()
    assert data["technical_blockers"]==[]


def test_conflicting_spec_and_candidate_remain_blocked(client,auth,monkeypatch):
    pid,iid,ids,_=setup_source(client,auth,monkeypatch)
    assert attach(client,auth,pid,pdf(
        "Gazbeton 10 cm: 3,50 N/mm2 dayanim ve 500 kg/m3 yogunluk."
    )).status_code==201
    data=client.get(url(pid,iid,ids[0],"15.999.1001"),headers=auth).json()
    assert data["status"]=="conflicting",data
    strength=next(x for x in data["fields"] if x["key"]=="gazbeton_strength_n_mm2")
    assert strength["status"]=="conflict"
    assert strength["suggested_from_spec"] is None
    assert data["cost_allowed"] is False


def test_two_opposing_spec_pages_never_choose_last_fact(client,auth,monkeypatch):
    pid,iid,ids,_=setup_source(client,auth,monkeypatch)
    assert attach(client,auth,pid,pdf(
        "Gazbeton 10 cm duvar: 2,50 N/mm2 ve 400 kg/m3.",
        "Gazbeton 10 cm duvar: 3,50 N/mm2 ve 400 kg/m3.",
    )).status_code==201
    data=client.get(url(pid,iid,ids[0],"15.999.1001"),headers=auth).json()
    assert data["status"]=="conflicting"
    strength=next(x for x in data["fields"] if x["key"]=="gazbeton_strength_n_mm2")
    assert strength["status"]=="conflict"
    assert strength["suggested_from_spec"] is None
    assert len(strength["conflicting_values"])==2


def test_unknown_position_not_approved_and_no_document(client,auth,monkeypatch):
    pid,iid,ids,_=setup_source(client,auth,monkeypatch)
    data=client.get(url(pid,iid,ids[0],"15.999.1999"),headers=auth).json()
    assert data["status"]=="no_document",data
    assert data["candidate_found_in_pdf"] is False
    assert data["possible_special_analysis"] is True
    assert data["engineering_approved"] is False and data["cost_allowed"] is False


def test_cement_plaster_fallback_does_not_accept_gypsum_as_cement():
    description="2 cm cimento esasli ic siva yapilmasi malzeme ve iscilik dahil"
    evidence=_matches(description,[
        (1,"Duvarlara 2 cm cimento esasli siva yapilacak."),
        (2,"Tavanlara 2,5 cm alci esasli siva uygulanacak."),
    ])
    assert len(evidence)==1
    fields, conflict, missing=_compare_fields(
        "siva",description,evidence,
        replace(gasbeton_poz(),description="2,5 cm alci esasli siva uygulanmasi"),
    )
    assert conflict
    assert any(x["key"]=="binder_type" and x["status"]=="conflict" for x in fields)


def test_cross_tenant_read_is_hidden(client,monkeypatch):
    owner=register(client,"A347 owner","a347owner@example.com")
    other=register(client,"A347 outsider","a347outsider@example.com")
    pid,iid,ids,_=setup_source(client,owner,monkeypatch)
    assert client.get(url(pid,iid,ids[0]),headers=other).status_code==404
