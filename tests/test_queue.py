from fpdf import FPDF
from pypdf import PdfReader

from app.db import enqueue_job, get_job, init_db, save_finding, set_setting
from app.pipeline.letters import estate_file, needs_letter, packet_filename, save_estate_file
from app.pipeline.queue import run_job


def test_cancel_subscription_builds_letter_packet(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_DB", str(tmp_path / "life.db"))
    init_db()
    set_setting("deceased_name", "Ada Example")
    set_setting("executor_name", "Pat Example")
    certificate = FPDF()
    certificate.add_page()
    certificate.set_font("Helvetica", size=16)
    certificate.cell(40, 10, "DEATH CERTIFICATE")
    raw = bytes(certificate.output())
    save_estate_file("death_certificate", "certificate.pdf", raw)
    assert estate_file("death_certificate") is not None
    finding_id = save_finding(
        {
            "category": "subscriptions",
            "provider": "Example News",
            "asset_kind": "subscription",
            "label": "Example News",
            "identifiers": [{"type": "email", "value": "reader@example.com"}],
            "confidence": 0.8,
            "status": "confirmed",
            "merge_key": "subscriptions|examplenews|reader",
        },
        [],
    )
    action = "Cancel the subscription"
    job_id = enqueue_job(finding_id, action)
    run_job(get_job(job_id))
    done = get_job(job_id)
    assert done["status"] == "done"
    assert needs_letter(action)
    assert packet_filename({"provider": "Example News"}, action).endswith(".pdf")
    reader = PdfReader(done["packet_path"])
    assert len(reader.pages) == 2
    text = reader.pages[0].extract_text() or ""
    assert "Example News" in text
    assert "reader@example.com" in text
    assert "Ada Example" in text
    assert "Pat Example" in text
