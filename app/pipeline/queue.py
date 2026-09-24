"""Background queue for the step an executor confirms."""

from __future__ import annotations

import logging
import threading
import time

from app.db import claim_job, finish_job, list_findings
from app.pipeline.letters import write_packet

log = logging.getLogger(__name__)
_started = False


def run_job(job: dict) -> None:
    finding = next((row for row in list_findings("all") if row["id"] == job["finding_id"]), None)
    if not finding:
        finish_job(job["id"], "error", "The asset is no longer in the vault.")
        return
    try:
        packet, note = write_packet(job["id"], finding, job["action"])
    except Exception:
        log.exception("job failed")
        finish_job(job["id"], "error", "The letter could not be prepared.")
        return
    finish_job(job["id"], "done", note, packet)


def _loop() -> None:
    while True:
        job = claim_job()
        if not job:
            time.sleep(1)
            continue
        run_job(job)


def start_queue() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="lifevault-queue", daemon=True).start()
