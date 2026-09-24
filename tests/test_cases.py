from fastapi.testclient import TestClient

from app.db import (
    enqueue_job,
    get_finding,
    init_db,
    list_case_documents,
    list_case_events,
    save_finding,
    set_setting,
    setting,
)
from app.main import app
from app.pipeline.cases import advance, close_estate, estate_blockers
from app.pipeline.letters import save_estate_file


def _asset(merge_key: str, status: str = "candidate", category: str = "subscriptions") -> int:
    return save_finding(
        {
            "category": category,
            "provider": "Example",
            "asset_kind": "account",
            "label": "Example asset",
            "identifiers": [],
            "confidence": 0.9,
            "status": status,
            "merge_key": merge_key,
        },
        [],
    )


def test_close_requires_a_written_result(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    finding_id = _asset("case|close")
    advance(finding_id, "identified")
    advance(finding_id, "secured", "Nothing to secure.")
    advance(finding_id, "processing", disposition="cancel")
    client = TestClient(app)
    blocked = client.post(f"/cases/{finding_id}/stage", data={"target": "closed", "note": "  "}, follow_redirects=False)
    assert blocked.status_code == 303
    assert "kind=error" in blocked.headers["location"]
    assert get_finding(finding_id)["stage"] == "processing"
    opened = client.post(
        f"/cases/{finding_id}/stage",
        data={"target": "closed", "note": "Nothing remains due."},
        follow_redirects=False,
    )
    assert opened.status_code == 303
    assert get_finding(finding_id)["stage"] == "closed"


def test_second_reply_keeps_the_first(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    finding_id = _asset("case|replies", status="confirmed")
    job_id = enqueue_job(finding_id, "Cancel the subscription")
    client = TestClient(app)
    first = client.post(
        f"/documents/{job_id}/reply",
        data={"reply_status": "received", "reply_note": "First reply."},
        follow_redirects=False,
    )
    second = client.post(
        f"/cases/{finding_id}/reply",
        data={"reply_note": "Second reply.", "job_id": str(job_id)},
        follow_redirects=False,
    )
    assert first.status_code == 303
    assert second.status_code == 303
    notes = [row["note"] for row in list_case_documents(finding_id) if row["direction"] == "in"]
    assert "First reply." in notes
    assert "Second reply." in notes
    assert len(notes) == 2


def test_new_mail_reopens_a_closed_case(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    finding_id = save_finding(
        {
            "category": "subscriptions",
            "provider": "Example",
            "asset_kind": "subscription",
            "label": "Example asset",
            "identifiers": [],
            "confidence": 0.4,
            "status": "confirmed",
            "merge_key": "case|reopen",
        },
        [{"message_id": None, "source_id": 1, "external_id": "m1", "message_date": "", "subject": "One", "excerpt": "One"}],
    )
    advance(finding_id, "secured", "Noted.")
    advance(finding_id, "processing", disposition="cancel")
    advance(finding_id, "closed", "Nothing remains due.")
    set_setting("estate_closed", "1")
    save_finding(
        {
            "category": "subscriptions",
            "provider": "Example",
            "asset_kind": "subscription",
            "label": "Example asset",
            "identifiers": [],
            "confidence": 0.9,
            "status": "confirmed",
            "merge_key": "case|reopen",
        },
        [{"message_id": None, "source_id": 1, "external_id": "m2", "message_date": "", "subject": "Two", "excerpt": "Two"}],
    )
    assert get_finding(finding_id)["stage"] == "identified"
    assert setting("estate_closed") == ""
    kinds = [row["kind"] for row in list_case_events(finding_id)]
    assert "reopened" in kinds


def test_estate_close_is_blocked_while_a_case_is_open(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    _asset("case|open")
    certificate = b"%PDF-1.4 estate"
    save_estate_file("death_certificate", "certificate.pdf", certificate)
    save_estate_file("executor_authorisation", "authority.pdf", certificate)
    set_setting("estate_debts", "paid")
    set_setting("estate_taxes", "reserved")
    set_setting("estate_final_note", "Final account filed.")
    set_setting("estate_discharge_note", "Heirs discharged the executor.")
    assert any("open" in item for item in estate_blockers())
    client = TestClient(app)
    blocked = client.post("/estate/close", follow_redirects=False)
    assert blocked.status_code == 303
    assert "kind=error" in blocked.headers["location"]
    assert setting("estate_closed") != "1"
    try:
        close_estate()
        raised = False
    except Exception:
        raised = True
    assert raised
