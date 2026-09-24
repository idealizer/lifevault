import json
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app.db import init_db, save_finding
from app.main import app
from app.vault_store import list_entries, lock, save_entry, setup, unlock, vault_ready


class _EditParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "js-edit" in values.get("class", ""):
            self.fields = values.get("data-fields", "")


def _edit_fields(html: str) -> str:
    parser = _EditParser()
    parser.feed(html)
    return parser.fields


def test_credential_round_trip_and_locked_page(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    lock()
    setup("correct-horse", "correct-horse")
    assert vault_ready()
    save_entry(
        "logins",
        {"title": "Mail", "url": "https://mail.example", "username": "ada", "password": 's3cret"value', "notes": ""},
    )
    rows = list_entries()
    assert rows[0]["fields"]["password"] == 's3cret"value'
    lock()
    assert unlock("wrong-password") is False
    assert unlock("correct-horse") is True
    client = TestClient(app)
    lock()
    locked = client.get("/vault")
    assert locked.status_code == 200
    assert 's3cret"value' not in locked.text
    assert unlock("correct-horse") is True
    opened = client.get("/vault")
    found = _edit_fields(opened.text)
    assert json.loads(found)["password"] == 's3cret"value'
    lock()
    assert "Unlock" in locked.text


def test_online_account_saves_an_empty_login(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "vault.db"))
    init_db()
    lock()
    setup("correct-horse", "correct-horse")
    finding_id = save_finding(
        {
            "category": "online_accounts",
            "provider": "Example",
            "asset_kind": "account",
            "label": "Example mail",
            "identifiers": [
                {"type": "email", "value": "ada@example.com"},
                {"type": "domain", "value": "example.com"},
            ],
            "confidence": 0.9,
            "status": "candidate",
            "merge_key": "online|example|ada",
        },
        [],
    )
    bank_id = save_finding(
        {
            "category": "banking",
            "provider": "Bank",
            "asset_kind": "current_account",
            "label": "Bank",
            "identifiers": [],
            "confidence": 0.5,
            "status": "candidate",
            "merge_key": "banking|bank|",
        },
        [],
    )
    client = TestClient(app)
    home = client.get("/")
    assert 'aria-label="Save to vault"' in home.text
    lock()
    locked = client.post(f"/findings/{finding_id}/vault-login")
    assert locked.status_code == 400
    assert "Unlock" in locked.json()["detail"]
    assert unlock("correct-horse") is True
    assert client.post(f"/findings/{bank_id}/vault-login").status_code == 400
    created = client.post(f"/findings/{finding_id}/vault-login")
    assert created.status_code == 200
    assert created.json()["already"] is False
    rows = list_entries()
    assert len(rows) == 1
    assert rows[0]["fields"]["password"] == ""
    assert rows[0]["fields"]["username"] == "ada@example.com"
    assert rows[0]["fields"]["url"] == "https://example.com"
    assert rows[0]["fields"]["notes"] == "Example mail"
    save_entry("logins", {**rows[0]["fields"], "password": "typed-later"}, rows[0]["id"])
    again = client.post(f"/findings/{finding_id}/vault-login")
    assert again.json()["already"] is True
    kept = list_entries()
    assert len(kept) == 1
    assert kept[0]["fields"]["password"] == "typed-later"
