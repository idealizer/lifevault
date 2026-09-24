"""Executor case stages. Events are append-only."""

from __future__ import annotations

from app.db import (
    add_case_document,
    get_finding,
    jobs_for_finding,
    list_case_documents,
    list_findings,
    record_case_event,
    set_setting,
    setting,
    stage_counts,
    update_finding_case,
)
from app.pipeline.letters import estate_file

STAGES = ("discovered", "identified", "secured", "processing", "closed", "dismissed")

STAGE_LABELS = {
    "discovered": "Discovered",
    "identified": "Identified",
    "secured": "Secured",
    "processing": "Processing",
    "closed": "Closed",
    "dismissed": "Dismissed",
}

SECURE_CATEGORIES = {
    "banking",
    "investments_pensions",
    "crypto",
    "property_utilities",
    "domains_hosting",
}

DISPOSITIONS = ("sell", "transfer", "split", "payout", "claim", "cancel", "close", "keep")


class CaseError(Exception):
    pass


def disposition_for(action: str) -> str:
    text = (action or "").lower()
    rules = (
        ("payout", ("move the balance", "pay the proceeds", "pay the closing", "refund", "unpaid")),
        ("sell", ("sell",)),
        ("split", ("split",)),
        ("claim", ("claim",)),
        ("cancel", ("cancel", "end the contract")),
        ("transfer", ("transfer",)),
        ("keep", ("keep ", "leave ", "renew", "record")),
        ("close", ("close",)),
    )
    for name, phrases in rules:
        if any(phrase in text for phrase in phrases):
            return name
    return "close"


def status_for(stage: str) -> str:
    if stage == "dismissed":
        return "dismissed"
    if stage == "discovered":
        return "candidate"
    return "confirmed"


def needs_secure(category: str) -> bool:
    return category in SECURE_CATEGORIES


def awaiting_reply(finding_id: int) -> bool:
    documents = list_case_documents(finding_id)
    for job in jobs_for_finding(finding_id):
        if not job.get("packet_path") or job.get("status") != "done":
            continue
        if any(doc.get("job_id") == job["id"] and doc.get("direction") == "in" for doc in documents):
            continue
        if (job.get("reply_status") or "") == "received":
            continue
        return True
    return False


def _require(finding_id: int) -> dict:
    row = get_finding(finding_id)
    if not row:
        raise CaseError("That asset is not in the vault.")
    return row


def advance(finding_id: int, target: str, note: str = "", disposition: str = "", override: bool = False) -> str:
    row = _require(finding_id)
    stage = row.get("stage") or "discovered"
    note = (note or "").strip()
    if target not in STAGES or target == stage:
        raise CaseError("Choose the next stage for this asset.")
    if target == "dismissed":
        if stage == "closed":
            raise CaseError("Reopen the case before dismissing it.")
        if not note:
            raise CaseError("Give a reason for dismissing this asset.")
        update_finding_case(finding_id, "dismissed", "dismissed")
        record_case_event(finding_id, "dismissed", "Dismissed", note)
        return "dismissed"
    if target == "identified" and stage == "discovered":
        update_finding_case(finding_id, "identified", "confirmed")
        record_case_event(finding_id, "identified", "Accepted as an estate asset", note)
        return "identified"
    if target == "secured" and stage == "identified":
        if not note:
            raise CaseError("Record how the asset was secured, or why nothing needs securing.")
        update_finding_case(finding_id, "secured", "confirmed")
        record_case_event(finding_id, "secured", "Secured", note)
        return "secured"
    if target == "processing" and stage == "identified":
        if needs_secure(row.get("category") or "") and not override:
            raise CaseError("Secure this asset first, or record why securing is skipped.")
        if not note:
            raise CaseError("Record why securing is skipped.")
        chosen = _disposition(disposition, row)
        update_finding_case(finding_id, "processing", "confirmed", chosen, note)
        record_case_event(finding_id, "override", "Securing skipped", note)
        record_case_event(finding_id, "processing", "Disposition set", f"{chosen}. {note}".strip())
        return "processing"
    if target == "processing" and stage == "secured":
        chosen = _disposition(disposition, row)
        update_finding_case(finding_id, "processing", "confirmed", chosen, note)
        record_case_event(finding_id, "processing", "Disposition set", chosen if not note else f"{chosen}. {note}")
        return "processing"
    if target == "processing" and stage == "closed":
        if not note:
            raise CaseError("Record why the case is reopened.")
        update_finding_case(finding_id, "processing", "confirmed")
        record_case_event(finding_id, "reopened", "Reopened", note)
        set_setting("estate_closed", "")
        return "processing"
    if target == "closed" and stage == "processing":
        incoming = [doc for doc in list_case_documents(finding_id) if doc.get("direction") == "in"]
        if not incoming and not note:
            raise CaseError("Add the reply, or a note that nothing remains due, before closing.")
        update_finding_case(finding_id, "closed", "confirmed")
        record_case_event(finding_id, "closed", "Closed", note or "A written result is on the file.")
        return "closed"
    raise CaseError("That stage does not follow the current one.")


def on_action_queued(finding_id: int, action: str) -> None:
    row = _require(finding_id)
    stage = row.get("stage") or "discovered"
    if stage == "dismissed":
        raise CaseError("Restore the asset before queuing a step.")
    chosen = disposition_for(action)
    if stage == "discovered":
        update_finding_case(finding_id, "identified", "confirmed")
        record_case_event(finding_id, "identified", "Accepted as an estate asset", action)
        stage = "identified"
    if stage == "identified" and needs_secure(row.get("category") or ""):
        record_case_event(finding_id, "override", "Securing skipped", f"A step was queued before securing: {action}")
    if stage in {"identified", "secured", "closed"}:
        update_finding_case(finding_id, "processing", "confirmed", chosen, action)
        if stage == "closed":
            record_case_event(finding_id, "reopened", "Reopened", action)
            set_setting("estate_closed", "")
        record_case_event(finding_id, "processing", "Disposition set", f"{chosen}: {action}")
    elif stage == "processing" and chosen != (row.get("disposition") or ""):
        update_finding_case(finding_id, "processing", "confirmed", chosen, action)
        record_case_event(finding_id, "processing", "Disposition set", f"{chosen}: {action}")


def add_reply(finding_id: int, note: str, path: str = "", job_id: int | None = None, title: str = "Response") -> None:
    _require(finding_id)
    text = (note or "").strip()
    if not text and not path:
        raise CaseError("Add the response file or a note before marking it received.")
    add_case_document(finding_id, "in", title, path, text, job_id)
    record_case_event(finding_id, "reply", "Response received", text, job_id, path)


def add_note(finding_id: int, note: str) -> None:
    text = (note or "").strip()
    if not text:
        raise CaseError("Write the note first.")
    _require(finding_id)
    record_case_event(finding_id, "note", "Note", text)


def mark_sent(finding_id: int, job_id: int) -> None:
    _require(finding_id)
    jobs = [job for job in jobs_for_finding(finding_id) if job["id"] == job_id and job.get("packet_path")]
    if not jobs:
        raise CaseError("That letter is not ready to send.")
    record_case_event(finding_id, "marked_sent", "Marked sent", jobs[0].get("action") or "", job_id, jobs[0].get("packet_path") or "")


def _disposition(chosen: str, row: dict) -> str:
    if chosen in DISPOSITIONS:
        return chosen
    existing = row.get("disposition") or ""
    if existing in DISPOSITIONS:
        return existing
    if row.get("chosen_action"):
        return disposition_for(row["chosen_action"])
    raise CaseError("Choose what will happen to this asset.")


def estate_blockers() -> list[str]:
    blockers = []
    if estate_file("death_certificate") is None:
        blockers.append("Upload the death certificate in Settings.")
    if estate_file("executor_authorisation") is None:
        blockers.append("Upload the executor authorisation in Settings.")
    counts = stage_counts()
    if counts["open"]:
        blockers.append(f"{counts['open']} assets are still open.")
    if setting("estate_debts") not in {"paid", "reserved"}:
        blockers.append("Mark debts as paid or reserved.")
    if setting("estate_taxes") not in {"paid", "reserved"}:
        blockers.append("Mark taxes as paid or reserved.")
    if not setting("estate_final_note").strip():
        blockers.append("Record the final account.")
    if not setting("estate_discharge_note").strip():
        blockers.append("Record the discharge.")
    return blockers


def save_estate_checklist(debts: str, debts_note: str, taxes: str, taxes_note: str, final_note: str, discharge_note: str) -> None:
    if debts in {"paid", "reserved"}:
        set_setting("estate_debts", debts)
    if taxes in {"paid", "reserved"}:
        set_setting("estate_taxes", taxes)
    set_setting("estate_debts_note", debts_note.strip()[:500])
    set_setting("estate_taxes_note", taxes_note.strip()[:500])
    set_setting("estate_final_note", final_note.strip()[:2000])
    set_setting("estate_discharge_note", discharge_note.strip()[:2000])
    record_case_event(0, "checklist", "Estate checklist updated", "")


def close_estate() -> None:
    blockers = estate_blockers()
    if blockers:
        raise CaseError(blockers[0])
    set_setting("estate_closed", "1")
    record_case_event(0, "estate_closed", "Estate closed", setting("estate_discharge_note"))


def worklist() -> list[dict]:
    rows = []
    for row in list_findings("all"):
        row["awaiting"] = awaiting_reply(int(row["id"]))
        row["stage_label"] = STAGE_LABELS.get(row.get("stage") or "", "Discovered")
        rows.append(row)
    order = {name: index for index, name in enumerate(STAGES)}
    rows.sort(key=lambda row: (order.get(row.get("stage") or "", 9), 0 if row["awaiting"] else 1, row.get("provider") or ""))
    return rows
