from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.vault_store import list_entries, lock, save_entry, setup, unlock, vault_ready


def test_credential_round_trip_and_locked_page(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    lock()
    setup("correct-horse", "correct-horse")
    assert vault_ready()
    save_entry(
        "logins",
        {"title": "Mail", "url": "https://mail.example", "username": "ada", "password": "s3cret-value", "notes": ""},
    )
    rows = list_entries()
    assert rows[0]["fields"]["password"] == "s3cret-value"
    lock()
    assert unlock("wrong-password") is False
    assert unlock("correct-horse") is True
    client = TestClient(app)
    lock()
    locked = client.get("/vault")
    assert locked.status_code == 200
    assert "s3cret-value" not in locked.text
    assert "Unlock" in locked.text
