from fastapi.testclient import TestClient

from app.db import (
    analysed_counts,
    create_source,
    drop_analysed_mail,
    init_db,
    list_sources,
    save_finding,
    set_setting,
    setting,
    upsert_message,
)
from app.main import app


def test_pages_render():
    init_db()
    save_finding(
        {
            "category": "banking",
            "provider": "Example Bank",
            "asset_kind": "current_account",
            "label": "Example current account",
            "identifiers": [{"type": "iban", "value": "CH00EXAMPLE"}],
            "confidence": 0.82,
            "status": "candidate",
            "merge_key": "banking|examplebank|ch00example",
        },
        [],
    )
    client = TestClient(app)
    home = client.get("/")
    mailboxes = client.get("/mailboxes")
    settings = client.get("/settings")
    assert home.status_code == 200
    assert "Assets" in home.text
    assert "Example current account" in home.text
    assert mailboxes.status_code == 200
    assert "Connect IMAP" in mailboxes.text
    assert "Apertus API key" not in mailboxes.text
    documents = client.get("/documents")
    assert documents.status_code == 200
    assert "Documents" in documents.text
    assert client.get("/documents/99999").status_code == 404
    log = client.get("/settings/log")
    assert log.status_code == 200
    assert "No model calls yet" in log.text
    assert settings.status_code == 200
    assert "Apertus API key" in settings.text
    assert "Drop analysed emails" in settings.text
    missing = client.get("/scans/99999.json")
    assert missing.status_code == 404


def test_drop_clears_mail_and_keeps_logins():
    init_db()
    set_setting("llm_provider", "apertus")
    create_source("imap", "Inbox", {"host": "imap.example.com", "username": "a"}, {"password": "secret"})
    file_id = create_source("file", "demo.csv", {"filename": "demo.csv", "count": 1}, {})
    upsert_message(file_id, "m1", "2024-01-01", "a@b.c", "Hi", "body", True, 0, recipient="c@d.e", body="body")
    save_finding(
        {
            "category": "subscriptions",
            "provider": "News",
            "asset_kind": "subscription",
            "label": "News",
            "identifiers": [],
            "confidence": 0.5,
            "status": "candidate",
            "merge_key": "subscriptions|news|",
        },
        [],
    )
    dropped = drop_analysed_mail()
    assert dropped["messages"] == 1
    assert analysed_counts() == {"messages": 0, "findings": 0, "files": 0}
    assert [item["kind"] for item in list_sources()] == ["imap"]
    assert setting("llm_provider") == "apertus"


def test_source_message_for_finding():
    init_db()
    source_id = create_source("file", "demo.csv", {"filename": "demo.csv", "count": 1}, {})
    message_id = upsert_message(
        source_id,
        "m-source",
        "2024-05-01",
        "bank@example.com",
        "Your statement",
        "short",
        True,
        0,
        recipient="you@example.com",
        body="Account CH00 is yours.",
    )
    finding_id = save_finding(
        {
            "category": "banking",
            "provider": "Example",
            "asset_kind": "current_account",
            "label": "Example account",
            "identifiers": [],
            "confidence": 0.9,
            "status": "candidate",
            "merge_key": "banking|example|source",
        },
        [
            {
                "message_id": message_id,
                "source_id": source_id,
                "external_id": "m-source",
                "message_date": "2024-05-01",
                "subject": "Your statement",
                "excerpt": "Account CH00",
            }
        ],
    )
    client = TestClient(app)
    page = client.get("/")
    assert 'data-source="' + str(finding_id) + '"' in page.text
    payload = client.get(f"/findings/{finding_id}/messages")
    assert payload.status_code == 200
    body = payload.json()["messages"][0]
    assert body["from"] == "bank@example.com"
    assert "CH00" in body["body"]
    assert body["subject"] == "Your statement"
