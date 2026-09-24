from app.db import init_db, save_finding
from app.pipeline.letters import needs_letter, write_packet
from app.pipeline.queue import run_job
from app.db import enqueue_job, get_job
import zipfile


def test_cancel_subscription_builds_letter_packet():
    init_db()
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
    job_id = enqueue_job(finding_id, "Cancel the subscription")
    run_job(get_job(job_id))
    done = get_job(job_id)
    assert done["status"] == "done"
    assert needs_letter("Cancel the subscription")
    with zipfile.ZipFile(done["packet_path"]) as archive:
        assert "letter.pdf" in archive.namelist()
