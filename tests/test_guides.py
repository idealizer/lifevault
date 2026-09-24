from fastapi.testclient import TestClient

from app.db import connect, init_db, list_api_logs, save_finding, set_setting
from app.main import app
from app.pipeline import guides
from app.pipeline.guides import parse_guide


def _finding() -> int:
    return save_finding(
        {
            "category": "banking",
            "provider": "Example Bank",
            "asset_kind": "current_account",
            "label": "Example current account",
            "identifiers": [{"type": "iban", "value": "CH00EXAMPLE"}],
            "confidence": 0.8,
            "status": "candidate",
            "merge_key": "banking|examplebank|guide",
        },
        [],
    )


def test_parse_keeps_official_links_and_catalogue_letters():
    allowed = [
        "Close the account after distribution",
        "Record the exchange or wallet in the estate inventory",
    ]
    guide = parse_guide(
        """```json
        {"summary":"Close online, then post if asked.",
         "steps":[
           {"title":"Form","detail":"Use the bank page.","url":"https://bank.example/close","needs_letter":false,"letter_action":""},
           {"title":"Post","detail":"Send the letter.","url":"javascript:alert(1)","needs_letter":true,"letter_action":"Close the account after distribution"},
           {"title":"Skip","detail":"Not a letter.","url":"","needs_letter":true,"letter_action":"Invent a call"}
         ]}
        ```""",
        allowed,
    )
    assert guide["steps"][0]["url"] == "https://bank.example/close"
    assert guide["steps"][1]["needs_letter"] is True
    assert guide["steps"][1]["url"] == ""
    assert guide["steps"][1]["letter_action"] == "Close the account after distribution"
    assert guide["steps"][2]["needs_letter"] is False


def test_missing_key_is_explained_and_stored_guide_is_reused(monkeypatch):
    init_db()
    finding_id = _finding()
    client = TestClient(app)
    missing = client.post(f"/findings/{finding_id}/guide")
    assert missing.status_code == 400
    assert "Settings" in missing.json()["detail"]

    calls = {"n": 0}

    def fake_build(row):
        calls["n"] += 1
        assert row["id"] == finding_id
        return {
            "summary": "Close it on the bank site.",
            "steps": [{"title": "Open", "detail": "Use the form.", "url": "https://bank.example/close", "needs_letter": False, "letter_action": ""}],
        }

    monkeypatch.setattr("app.main.build_guide", fake_build)
    set_setting("openai_api_key", "sk-test-secret")
    created = client.post(f"/findings/{finding_id}/guide")
    assert created.status_code == 200
    stored = client.get(f"/findings/{finding_id}/guide")
    assert stored.json()["guide"]["summary"] == "Close it on the bank site."
    assert calls["n"] == 1
    home = client.get("/")
    assert 'aria-label="Close instructions"' in home.text
    settings = client.get("/settings")
    assert "OpenAI API key" in settings.text
    assert "gpt-4.1" in settings.text
    assert "sk-test-secret" not in settings.text


def test_guide_log_omits_the_api_key(monkeypatch):
    init_db()
    set_setting("openai_api_key", "sk-live-secret")
    set_setting("openai_model", "gpt-4.1")

    class FakeResponse:
        output_text = '{"summary":"Done.","steps":[{"title":"Open","detail":"Use the page.","url":"https://bank.example","needs_letter":false,"letter_action":""}]}'

        def model_dump(self):
            return {"output_text": self.output_text}

    class FakeResponses:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "sk-live-secret"
            self.responses = FakeResponses()

    monkeypatch.setattr(guides, "OpenAI", FakeClient)
    guide = guides.build_guide(
        {
            "category": "banking",
            "provider": "Example Bank",
            "label": "Current account",
            "asset_kind": "current_account",
            "identifiers": [],
        }
    )
    assert guide["steps"][0]["url"] == "https://bank.example"
    logged = list_api_logs()
    assert logged
    blob = logged[0]["request_json"] + logged[0]["response_json"]
    assert "sk-live-secret" not in blob
    assert logged[0]["provider"] == "openai"
    conn = connect()
    try:
        conn.execute("DELETE FROM api_logs")
        conn.commit()
    finally:
        conn.close()
