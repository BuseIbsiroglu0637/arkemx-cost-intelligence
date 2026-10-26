"""M4.2.2 acceptance: meaningful rationales and current/historical event scopes."""
import pytest
from app.decision_reason import valid_decision_reason, require_decision_reason
from test_m42 import ready, queue
from test_m421_controlled import review, detail


@pytest.mark.parametrize("value", [
    "....................", "????????????????????", "..................!",
    "Kendi gerekçem", "Kontrol edildi", "Uygun bulundu",
    "test gerekçesi", "abc abc abc abc abc", "123456789012345678",
    "          ", "\t.\n.\t.\n.",
])
def test_m422_rejects_vacuous_rationale_in_validator(value):
    assert valid_decision_reason(value) is False


@pytest.mark.parametrize("value", [
    "C25/30 beton sınıfı ve nakliye dahil kapsamı doğrulandı.",
    "Poz kimliği 004, kapsamı ve beton sınıfı eşleşiyor.",
    "Technical and rights checks performed, synthetic pilot",
])
def test_m422_accepts_specific_rationale(value):
    assert valid_decision_reason(value) is True
    assert require_decision_reason(value) == value


def test_m422_rejects_garbage_in_both_single_and_serial_endpoints(client,monkeypatch):
    head,pid,cat,run=ready(client,monkeypatch)
    candidate=queue(client,pid,head,status="compatible").json()["rows"][0]
    cid=candidate["candidate_id"]
    digest=detail(client,pid,head,cid).json()["evidence"]["evidence_sha256"]
    before=queue(client,pid,head).json()["summary"]["decisions"]
    for reason in [".....................","Kendi gerekçem","Kontrol edildi"]:
        single=client.post(f"/api/projects/{pid}/m2/decisions",headers=head,
             json={"run_id":run,"candidate_id":cid,"action":"approve","reason":reason})
        assert single.status_code==422,single.text
        serial=review(client,pid,head,run,cid,digest,reason=reason)
        assert serial.status_code==422,serial.text
    assert queue(client,pid,head).json()["summary"]["decisions"] == before
    record=detail(client,pid,head,cid).json()
    assert record["history"] == []


def test_m422_current_counts_ignore_historical_review_events(client,monkeypatch):
    head,pid,cat,old=ready(client,monkeypatch)
    original=queue(client,pid,head,status="compatible").json()["rows"][0]
    cid=original["candidate_id"]
    reason="Teknik katalog ve metraj kanıtı bu pilot için eşleşmektedir"
    action=client.post(f"/api/projects/{pid}/m2/decisions",headers=head,
        json={"run_id":old,"candidate_id":cid,"action":"approve","reason":reason})
    assert action.status_code==201,action.text
    assert queue(client,pid,head).json()["summary"]["decisions"]["approved"]==1
    newer=client.post(f"/api/projects/{pid}/m41/run",headers=head)
    assert newer.status_code==201,newer.text
    new_run=newer.json()["id"]
    assert new_run!=old
    latest=queue(client,pid,head,status="compatible")
    assert latest.status_code==200
    assert latest.json()["summary"]["decisions"]["approved"]==0
    current=latest.json()["rows"][0]
    history=detail(client,pid,head,current["candidate_id"])
    assert history.status_code==200,history.text
    records=history.json()["history"]
    assert records and records[0]["current_run"] is False
    assert records[0]["run_id"] == old
    assert records[0]["reason"] == reason
    newapprove=client.post(f"/api/projects/{pid}/m2/decisions",headers=head,
        json={"run_id":new_run,"candidate_id":current["candidate_id"],
              "action":"approve","reason":"Güncel çalışmada poz, metraj ve nakliye şartları uyumlu"})
    assert newapprove.status_code==201,newapprove.text
    history2=detail(client,pid,head,current["candidate_id"]).json()["history"]
    assert any(r["current_run"] and r["run_id"] == new_run for r in history2)
    assert any(not r["current_run"] and r["run_id"] == old for r in history2)
    assert queue(client,pid,head).json()["summary"]["decisions"]["approved"]==1
