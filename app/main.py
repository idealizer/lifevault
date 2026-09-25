"""Local web UI. Binds to loopback and keeps the mailbox on this machine."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from pathlib import Path
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.categories import CATEGORIES, CATEGORY_ICONS, CATEGORY_LABELS
from app.config import access_password, default_token_budget, google_secret_path, host, oauth_redirect_uri, port
from app.connectors.base import ConnectorError
from app.connectors.imap import check_login
from app.db import (
    analysed_counts,
    enqueue_job,
    evidence_messages,
    create_run,
    drop_analysed_mail,
    create_source,
    delete_source,
    finding_counts,
    get_finding,
    get_job,
    get_run,
    jobs_for_finding,
    list_case_documents,
    list_case_events,
    list_estate_events,
    get_source,
    has_active_run,
    init_db,
    interrupt_stale_runs,
    list_api_logs,
    list_findings,
    list_jobs,
    list_runs,
    list_sources,
    record_case_event,
    update_finding_case,
    mask_secret,
    save_action_choice,
    save_finding_guide,
    set_job_reply,
    set_setting,
    setting,
    update_run,
    upsert_message,
)
from app.llm.client import ModelError, resolve_llm
from app.pipeline.cases import (
    STAGE_LABELS,
    CaseError,
    add_note,
    add_reply,
    advance,
    awaiting_reply,
    close_estate,
    estate_blockers,
    mark_sent,
    on_action_queued,
    visible_events,
    save_estate_checklist,
    worklist,
)
from app.pipeline.guides import build_guide, openai_ready
from app.pipeline.estate_actions import ESTATE_ACTIONS, actions_for
from app.pipeline.import_mail import ImportError, parse_mail_file
from app.pipeline.letters import estate_file, reply_path, save_estate_file, save_reply_file
from app.pipeline.pitch import (
    pitch_display_mode,
    pitch_file,
    pitch_filename,
    pitch_video_file,
    pitch_video_filename,
    save_pitch_file,
    save_pitch_video,
    set_pitch_mode,
)
from app.pipeline.queue import start_queue
from app.pipeline.scan import backfill_signals, execute_scan, message_body, window_start
from app.vault_store import KINDS, VaultError, counts as vault_counts
from app.vault_store import delete_entry, list_entries, lock as vault_lock
from app.vault_store import save_entry, save_login_for_finding, setup as vault_setup, unlock as vault_unlock
from app.vault_store import unlocked as vault_unlocked, vault_ready

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
_oauth_states: dict[str, str] = {}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    interrupt_stale_runs()
    backfill_signals()
    start_queue()
    yield


app = FastAPI(title="Lifevault", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")

ACCESS_COOKIE = "lifevault_access"


def _access_token(password: str) -> str:
    return hmac.new(b"lifevault-access-v1", password.encode(), hashlib.sha256).hexdigest()


def _password_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(given.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def _safe_next(target: str) -> str:
    if target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


class AccessGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        password = access_password()
        path = request.url.path
        if not password or path.startswith("/static") or path in {"/access", "/robots.txt"}:
            return await call_next(request)
        token = request.cookies.get(ACCESS_COOKIE, "")
        expected = _access_token(password)
        if len(token) == len(expected) and hmac.compare_digest(token, expected):
            return await call_next(request)
        nxt = path
        if request.url.query:
            nxt += "?" + request.url.query
        return RedirectResponse("/access?next=" + quote(nxt, safe="/"), status_code=303)


app.add_middleware(AccessGate)


def _redirect(path: str, notice: str, kind: str = "success") -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}notice={notice}&kind={kind}", status_code=303)


def _render(request: Request, name: str, **context):
    context.setdefault("page", "")
    context["request"] = request
    return templates.TemplateResponse(request, name, context)


def _vault_context(status: str, category: str) -> dict:
    allowed = {"active", "candidate", "confirmed", "dismissed", "all", "discovered", "identified", "secured", "processing", "closed"}
    if status not in allowed:
        status = "active"
    findings = list_findings(status)
    grouped: dict[str, list] = {key: [] for key, _label in CATEGORIES}
    for finding in findings:
        grouped.setdefault(finding["category"], []).append(finding)
    tiles = [
        {"key": key, "label": label, "count": len(grouped.get(key, [])), "icon": CATEGORY_ICONS.get(key, "")}
        for key, label in CATEGORIES
    ]
    selected = category if category in CATEGORY_LABELS else ""
    sections = [
        {"key": key, "label": label, "findings": grouped.get(key, [])}
        for key, label in CATEGORIES
        if grouped.get(key) and (not selected or key == selected)
    ]
    counts = finding_counts()
    return {
        "tiles": tiles,
        "sections": sections,
        "counts": counts,
        "status": status,
        "category": selected,
        "total": len(findings),
        "risks": len(grouped.get("risks", [])),
        "scanning": has_active_run(),
        "page": "assets",
        "estate_actions": ESTATE_ACTIONS,
        "stage_labels": STAGE_LABELS,
        "estate_closed": setting("estate_closed") == "1",
        "estate_blockers": estate_blockers(),
        "estate_debts": setting("estate_debts"),
        "estate_debts_note": setting("estate_debts_note"),
        "estate_taxes": setting("estate_taxes"),
        "estate_taxes_note": setting("estate_taxes_note"),
        "estate_final_note": setting("estate_final_note"),
        "estate_discharge_note": setting("estate_discharge_note"),
        "estate_events": list_estate_events(),
    }


@app.get("/robots.txt")
def robots_txt():
    return PlainTextResponse("User-agent: *\nDisallow: /\n", media_type="text/plain")


@app.get("/access")
def access_page(request: Request, next: str = "/"):
    password = access_password()
    token = request.cookies.get(ACCESS_COOKIE, "")
    expected_token = _access_token(password) if password else ""
    if password and len(token) == len(expected_token) and hmac.compare_digest(token, expected_token):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _render(request, "access.html", page="access", next=_safe_next(next))


@app.post("/access")
def access_login(request: Request, password: str = Form(""), next: str = Form("/")):
    expected = access_password()
    if not expected or not _password_matches(password, expected):
        return _redirect("/access", "That password is not right.", "error")
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        ACCESS_COOKIE,
        _access_token(expected),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        max_age=60 * 60 * 12,
        path="/",
    )
    return response


@app.get("/")
def vault(request: Request, status: str = "active", category: str = ""):
    return _render(request, "vault.html", **_vault_context(status, category))


@app.get("/vault")
def credentials_page(request: Request, kind: str = ""):
    selected = kind if kind in {row["key"] for row in KINDS} else ""
    open_vault = vault_unlocked()
    return _render(
        request,
        "credentials.html",
        page="vault",
        ready=vault_ready(),
        unlocked=open_vault,
        kinds=KINDS,
        kind=selected,
        counts=vault_counts() if open_vault else {},
        total=sum(vault_counts().values()) if open_vault else 0,
        entries=list_entries(selected) if open_vault else [],
    )


@app.post("/vault/setup")
def credentials_setup(password: str = Form(""), confirm: str = Form("")):
    try:
        vault_setup(password, confirm)
    except VaultError as exc:
        return _redirect("/vault", str(exc), "error")
    return _redirect("/vault", "Vault ready.")


@app.post("/vault/unlock")
def credentials_unlock(password: str = Form("")):
    if not vault_unlock(password):
        return _redirect("/vault", "That password did not open the vault.", "error")
    return _redirect("/vault", "Vault unlocked.")


@app.post("/findings/{finding_id}/vault-login")
def finding_vault_login(finding_id: int):
    row = _finding_row(finding_id)
    if row.get("category") != "online_accounts":
        raise HTTPException(400, "Only an online account can be saved as a login.")
    if not vault_unlocked():
        raise HTTPException(400, "Unlock the vault first.")
    try:
        created = save_login_for_finding(row)
    except VaultError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "already": not created,
        "message": "Already in the vault." if not created else "Saved to the vault.",
    }


@app.post("/vault/lock")
def credentials_lock():
    vault_lock()
    return _redirect("/vault", "Vault locked.")


@app.post("/vault/entries")
def credentials_save(
    kind: str = Form(""),
    entry_id: str = Form(""),
    title: str = Form(""),
    url: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    network: str = Form(""),
    bank: str = Form(""),
    user_id: str = Form(""),
    holder: str = Form(""),
    address: str = Form(""),
    secret: str = Form(""),
    notes: str = Form(""),
):
    fields = {
        "title": title,
        "url": url,
        "username": username,
        "password": password,
        "network": network,
        "bank": bank,
        "user_id": user_id,
        "holder": holder,
        "address": address,
        "secret": secret,
        "notes": notes,
    }
    try:
        number = int(entry_id) if entry_id.strip().isdigit() else None
        save_entry(kind, fields, number)
    except VaultError as exc:
        return _redirect("/vault", str(exc), "error")
    return _redirect("/vault?kind=" + kind, "Saved.")


@app.post("/vault/entries/{entry_id}/delete")
def credentials_delete(entry_id: int):
    try:
        delete_entry(entry_id)
    except VaultError as exc:
        return _redirect("/vault", str(exc), "error")
    return _redirect("/vault", "Removed.")


@app.get("/actions")
def actions_page():
    return RedirectResponse("/", status_code=302)


@app.get("/documents")
def documents_page(request: Request, stage: str = ""):
    rows = worklist()
    counts = {key: 0 for key in STAGE_LABELS}
    awaiting = 0
    for row in rows:
        key = row.get("stage") or "discovered"
        if key in counts:
            counts[key] += 1
        if row.get("awaiting"):
            awaiting += 1
    pills = [{"key": "awaiting", "label": "Awaiting reply", "count": awaiting}]
    pills += [{"key": key, "label": label, "count": counts[key]} for key, label in STAGE_LABELS.items()]
    allowed = {pill["key"] for pill in pills}
    if stage not in allowed:
        if awaiting:
            stage = "awaiting"
        else:
            stage = next((pill["key"] for pill in pills if pill["count"]), "discovered")
    if stage == "awaiting":
        cases = [row for row in rows if row.get("awaiting")]
        label = "Awaiting reply"
    else:
        cases = [row for row in rows if (row.get("stage") or "discovered") == stage]
        label = STAGE_LABELS.get(stage, stage)
    return _render(
        request,
        "documents.html",
        page="documents",
        pills=pills,
        stage=stage,
        label=label,
        cases=cases,
    )


@app.get("/cases/{finding_id}")
def case_page(request: Request, finding_id: int):
    row = get_finding(finding_id)
    if not row:
        raise HTTPException(404, "That asset is not in the vault.")
    jobs = jobs_for_finding(finding_id)
    preview = ""
    for job in reversed(jobs):
        if job.get("packet_path"):
            preview = f"/documents/{job['id']}/letter.pdf"
            break
    return _render(
        request,
        "case.html",
        page="documents",
        finding=row,
        stage_label=STAGE_LABELS.get(row.get("stage") or "", "Discovered"),
        events=visible_events(list_case_events(finding_id), jobs),
        documents=list_case_documents(finding_id),
        jobs=jobs,
        preview_src=preview,
        awaiting=awaiting_reply(finding_id),
        actions=actions_for(row.get("category") or "other"),
    )


@app.post("/cases/{finding_id}/stage")
def case_stage(
    finding_id: int,
    target: str = Form(""),
    note: str = Form(""),
    disposition: str = Form(""),
    override: str = Form(""),
):
    try:
        advance(finding_id, target, note, disposition, override == "1")
    except CaseError as exc:
        return _redirect(f"/cases/{finding_id}", str(exc), "error")
    return _redirect(f"/cases/{finding_id}", "Stage updated.")


@app.post("/cases/{finding_id}/note")
def case_note(finding_id: int, note: str = Form("")):
    try:
        add_note(finding_id, note)
    except CaseError as exc:
        return _redirect(f"/cases/{finding_id}", str(exc), "error")
    return _redirect(f"/cases/{finding_id}", "Note added.")


@app.post("/cases/{finding_id}/reply")
async def case_reply(
    finding_id: int,
    reply_note: str = Form(""),
    job_id: str = Form(""),
    reply_file: UploadFile | None = File(None),
):
    stored = ""
    number = int(job_id) if job_id.strip().isdigit() else None
    try:
        if reply_file and reply_file.filename:
            stored = save_reply_file(number or finding_id, reply_file.filename, await reply_file.read())
        add_reply(finding_id, reply_note, stored, number)
    except (CaseError, ValueError) as exc:
        return _redirect(f"/cases/{finding_id}", str(exc), "error")
    if number:
        set_job_reply(number, "received", reply_note.strip(), stored or None)
    return _redirect(f"/cases/{finding_id}", "Response added.")


@app.post("/cases/{finding_id}/sent")
def case_sent(finding_id: int, job_id: int = Form(...)):
    try:
        mark_sent(finding_id, job_id)
    except CaseError as exc:
        return _redirect(f"/cases/{finding_id}", str(exc), "error")
    return _redirect(f"/cases/{finding_id}", "Marked sent.")


@app.get("/cases/{finding_id}/files/{document_id}")
def case_file(finding_id: int, document_id: int):
    match = next((row for row in list_case_documents(finding_id) if row["id"] == document_id), None)
    if not match or not match.get("path"):
        raise HTTPException(404, "That file is not stored.")
    path = Path(match["path"])
    if match.get("direction") == "in":
        stored = reply_path(path.name)
        path = stored or path
    if not path.is_file():
        raise HTTPException(404, "That file is not stored.")
    media = "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif path.suffix.lower() == ".png":
        media = "image/png"
    return FileResponse(path, media_type=media, content_disposition_type="inline", filename=path.name)


@app.post("/estate/checklist")
def estate_checklist(
    debts: str = Form(""),
    debts_note: str = Form(""),
    taxes: str = Form(""),
    taxes_note: str = Form(""),
    final_note: str = Form(""),
    discharge_note: str = Form(""),
):
    save_estate_checklist(debts, debts_note, taxes, taxes_note, final_note, discharge_note)
    return _redirect("/", "Checklist saved.")


@app.post("/estate/close")
def estate_close():
    try:
        close_estate()
    except CaseError as exc:
        return _redirect("/", str(exc), "error")
    return _redirect("/", "Estate closed.")


@app.get("/documents/{job_id}")
def document_page(request: Request, job_id: int, print: int = 0):
    job = get_job(job_id)
    if not job or not job.get("packet_path"):
        raise HTTPException(404, "That document is not ready.")
    path = Path(job["packet_path"])
    if not path.is_file():
        raise HTTPException(404, "That document is not ready.")
    if print:
        return queue_packet(job_id, inline=1)
    return RedirectResponse(f"/cases/{job['finding_id']}#letter-{job_id}", status_code=302)


@app.post("/documents/{job_id}/reply")
async def document_reply(
    job_id: int,
    reply_status: str = Form("awaiting"),
    reply_note: str = Form(""),
    reply_file: UploadFile | None = File(None),
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "That document is not ready.")
    status = "received" if reply_status == "received" else "awaiting"
    note = reply_note.strip()
    stored = None
    try:
        if reply_file and reply_file.filename:
            stored = save_reply_file(job_id, reply_file.filename, await reply_file.read())
    except ValueError as exc:
        return _redirect(f"/documents/{job_id}", str(exc), "error")
    has_file = bool(stored or job.get("reply_file"))
    if status == "received" and not has_file and not note:
        return _redirect(
            f"/documents/{job_id}",
            "Add the response file or a note before marking it received.",
            "error",
        )
    if status == "received":
        try:
            add_reply(int(job["finding_id"]), note, stored or "", job_id)
        except CaseError as exc:
            return _redirect(f"/cases/{job['finding_id']}", str(exc), "error")
    set_job_reply(job_id, status, note, stored)
    return _redirect(f"/cases/{job['finding_id']}", "Status saved.")


@app.get("/documents/{job_id}/reply-file")
def document_reply_file(job_id: int):
    job = get_job(job_id)
    path = reply_path((job or {}).get("reply_file") or "")
    if not path:
        raise HTTPException(404, "No response file is stored.")
    media = "application/pdf" if path.suffix.lower() == ".pdf" else "image/" + path.suffix.lower().lstrip(".")
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    return FileResponse(path, media_type=media, content_disposition_type="inline", filename=path.name)


@app.get("/queue.json")
def queue_json():
    rows = []
    for job in list_jobs():
        packet = job.get("packet_path") or ""
        filename = Path(packet).name.split("-", 2)[-1] if packet else ""
        rows.append(
            {
                "id": job["id"],
                "finding_id": job["finding_id"],
                "label": job.get("label") or "Asset",
                "provider": job.get("provider") or "",
                "action": job["action"],
                "status": job["status"],
                "note": job["note"],
                "created": (job.get("created_at") or "")[:16].replace("T", " "),
                "filename": filename,
                "ready": bool(packet),
                "reply_status": job.get("reply_status") or "awaiting",
            }
        )
    return {"jobs": rows}


@app.get("/documents/{job_id}/{filename}")
def document_file(job_id: int, filename: str):
    return queue_packet(job_id, inline=1)


@app.get("/queue/{job_id}/packet")
def queue_packet(job_id: int, inline: int = 0):
    job = get_job(job_id)
    if not job or not job.get("packet_path"):
        raise HTTPException(404, "That packet is not ready.")
    path = Path(job["packet_path"])
    if not path.is_file():
        raise HTTPException(404, "That packet is not ready.")
    return FileResponse(
        path,
        filename=path.name.split("-", 2)[-1],
        media_type="application/pdf",
        content_disposition_type="inline" if inline else "attachment",
    )


@app.post("/findings/{finding_id}/queue")
def queue_finding(
    finding_id: int,
    action: list[str] = Form(default=[]),
    note: list[str] = Form(default=[]),
    redirect: str = Form(""),
):
    rows = [row for row in list_findings("all") if row["id"] == finding_id]
    if not rows:
        raise HTTPException(404, "That asset is not in the vault.")
    options = actions_for(rows[0]["category"])
    chosen = []
    for item in action:
        text = item.strip()
        if text in options and text not in chosen:
            chosen.append(text)
    for item in note:
        text = item.strip()
        if text and text not in chosen:
            chosen.append(text)
    if not chosen:
        raise HTTPException(400, "Choose a listed step or write your own.")
    try:
        on_action_queued(finding_id, chosen[0])
    except CaseError as exc:
        raise HTTPException(400, str(exc)) from exc
    save_action_choice(finding_id, chosen[0], " · ".join(chosen[1:])[:500])
    job_ids = [enqueue_job(finding_id, item) for item in chosen]
    if redirect == "1":
        return _redirect(f"/cases/{finding_id}", "Letter queued.")
    row = get_finding(finding_id)
    return {
        "ok": True,
        "status": (row or {}).get("stage") or "processing",
        "job_id": job_ids[0],
        "job_ids": job_ids,
        "counts": finding_counts(),
    }


def _finding_row(finding_id: int) -> dict:
    rows = [row for row in list_findings("all") if row["id"] == finding_id]
    if not rows:
        raise HTTPException(404, "That asset is not in the vault.")
    return rows[0]


def _stored_guide(row: dict) -> dict | None:
    raw = row.get("guide_json") or ""
    if not raw:
        return None
    try:
        guide = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return guide if isinstance(guide, dict) and guide.get("steps") else None


@app.get("/findings/{finding_id}/guide")
def finding_guide(finding_id: int):
    row = _finding_row(finding_id)
    return {"ok": True, "has_key": openai_ready(), "guide": _stored_guide(row)}


@app.post("/findings/{finding_id}/guide")
def finding_guide_search(finding_id: int):
    row = _finding_row(finding_id)
    try:
        guide = build_guide(row)
    except ModelError as exc:
        raise HTTPException(400, str(exc)) from exc
    save_finding_guide(finding_id, guide)
    return {"ok": True, "has_key": True, "guide": guide}


@app.get("/inventory")
def inventory_redirect(status: str = "active", category: str = ""):
    query = f"status={status}"
    if category:
        query += f"&category={category}"
    return RedirectResponse(f"/?{query}", status_code=302)


@app.get("/mailboxes")
def mailboxes(request: Request):
    llm = resolve_llm()
    return _render(
        request,
        "mailboxes.html",
        page="mailboxes",
        sources=list_sources(),
        runs=list_runs(),
        counts=finding_counts(),
        redirect_uri=oauth_redirect_uri(),
        provider=llm["provider"],
        key_hint=mask_secret(llm["api_key"]),
        apertus_model=setting("apertus_model") or "swiss-ai/Apertus-v1.5-70B",
        grok_model=setting("xai_model") or "grok-4",
        token_budget=setting("token_budget") or str(default_token_budget()),
        google_ready=google_secret_path().exists(),
        scanning=has_active_run(),
    )


@app.get("/settings/log")
def settings_log_page(request: Request):
    return _render(request, "settings_log.html", page="settings", logs=list_api_logs())


@app.get("/settings")
def settings_page(request: Request):
    llm = resolve_llm()
    return _render(
        request,
        "settings.html",
        page="settings",
        provider=llm["provider"],
        key_hint=mask_secret(llm["api_key"]),
        apertus_model=setting("apertus_model") or "swiss-ai/Apertus-v1.5-70B",
        grok_model=setting("xai_model") or "grok-4",
        openai_hint=mask_secret(setting("openai_api_key")),
        openai_model=setting("openai_model") or "gpt-4.1",
        token_budget=setting("token_budget") or str(default_token_budget()),
        analysed=analysed_counts(),
        scanning=has_active_run(),
        deceased_name=setting("deceased_name"),
        date_of_death=setting("date_of_death"),
        executor_company=setting("executor_company"),
        executor_firstname=setting("executor_firstname"),
        executor_lastname=setting("executor_lastname"),
        executor_street=setting("executor_street"),
        executor_street_no=setting("executor_street_no"),
        executor_zip=setting("executor_zip"),
        executor_city=setting("executor_city"),
        executor_country=setting("executor_country"),
        estate_bank=setting("estate_bank"),
        estate_iban=setting("estate_iban"),
        estate_swift=setting("estate_swift"),
        has_death_certificate=estate_file("death_certificate") is not None,
        has_authorisation=estate_file("executor_authorisation") is not None,
        death_certificate_name=(estate_file("death_certificate").name if estate_file("death_certificate") else ""),
        authorisation_name=(estate_file("executor_authorisation").name if estate_file("executor_authorisation") else ""),
        pitch_name=pitch_filename() if pitch_file() else "",
        pitch_video_name=pitch_video_filename() if pitch_video_file() else "",
        pitch_mode=pitch_display_mode(),
    )


@app.post("/admin/drop-mail")
def drop_mail():
    if has_active_run():
        return _redirect("/settings", "Stop the running scan before dropping analysed emails.", "alert")
    counts = drop_analysed_mail()
    return _redirect(
        "/settings",
        f"Dropped {counts['messages']} emails and {counts['findings']} vault items.",
        "success",
    )


@app.post("/settings")
def save_settings(
    llm_provider: str = Form("apertus"),
    apertus_api_key: str = Form(""),
    xai_api_key: str = Form(""),
    apertus_model: str = Form(""),
    xai_model: str = Form(""),
    openai_api_key: str = Form(""),
    openai_model: str = Form(""),
    token_budget: str = Form(""),
):
    provider = "grok" if llm_provider == "grok" else "apertus"
    set_setting("llm_provider", provider)
    if apertus_api_key.strip():
        set_setting("apertus_api_key", apertus_api_key.strip())
    if xai_api_key.strip():
        set_setting("xai_api_key", xai_api_key.strip())
    if apertus_model.strip():
        set_setting("apertus_model", apertus_model.strip())
    if xai_model.strip():
        set_setting("xai_model", xai_model.strip())
    if openai_api_key.strip():
        set_setting("openai_api_key", openai_api_key.strip())
    if openai_model.strip():
        set_setting("openai_model", openai_model.strip())
    if token_budget.strip().isdigit():
        set_setting("token_budget", str(min(10_000_000, max(10_000, int(token_budget)))))
    return _redirect("/settings", "Settings saved")


@app.post("/settings/estate")
async def save_estate(
    deceased_name: str = Form(""),
    date_of_death: str = Form(""),
    executor_company: str = Form(""),
    executor_firstname: str = Form(""),
    executor_lastname: str = Form(""),
    executor_street: str = Form(""),
    executor_street_no: str = Form(""),
    executor_zip: str = Form(""),
    executor_city: str = Form(""),
    executor_country: str = Form(""),
    estate_bank: str = Form(""),
    estate_iban: str = Form(""),
    estate_swift: str = Form(""),
    death_certificate: UploadFile | None = File(None),
    executor_authorisation: UploadFile | None = File(None),
):
    set_setting("deceased_name", deceased_name.strip()[:200])
    set_setting("date_of_death", date_of_death.strip()[:40])
    set_setting("executor_company", executor_company.strip()[:200])
    set_setting("executor_firstname", executor_firstname.strip()[:120])
    set_setting("executor_lastname", executor_lastname.strip()[:120])
    set_setting("executor_street", executor_street.strip()[:200])
    set_setting("executor_street_no", executor_street_no.strip()[:40])
    set_setting("executor_zip", executor_zip.strip()[:20])
    set_setting("executor_city", executor_city.strip()[:120])
    set_setting("executor_country", executor_country.strip()[:120])
    set_setting("estate_bank", estate_bank.strip()[:200])
    set_setting("estate_iban", re.sub(r"\s+", " ", estate_iban).strip()[:64])
    set_setting("estate_swift", estate_swift.strip().upper()[:16])
    full_name = " ".join(part for part in (executor_firstname.strip(), executor_lastname.strip()) if part)
    set_setting("executor_name", full_name[:200])
    try:
        for kind, upload in (
            ("death_certificate", death_certificate),
            ("executor_authorisation", executor_authorisation),
        ):
            if upload and upload.filename:
                save_estate_file(kind, upload.filename, await upload.read())
    except ValueError as exc:
        return _redirect("/settings", str(exc), "error")
    return _redirect("/settings", "Estate documents saved.")


@app.get("/pitch")
def pitch_page(request: Request):
    mode = pitch_display_mode()
    has_pdf = pitch_file() is not None
    has_video = pitch_video_file() is not None
    show_video = mode == "video" and has_video
    return _render(
        request,
        "pitch.html",
        page="pitch",
        has_pitch=has_pdf or has_video,
        show_video=show_video,
        pitch_name=(pitch_video_filename() if show_video else pitch_filename()) or "Pitch",
    )


@app.get("/pitch/deck")
def pitch_deck():
    stored = pitch_file()
    if not stored:
        raise HTTPException(404, "No pitch deck is stored.")
    return FileResponse(
        stored,
        media_type="application/pdf",
        content_disposition_type="inline",
        filename=pitch_filename() or "deck.pdf",
    )


@app.get("/pitch/video")
def pitch_video():
    stored = pitch_video_file()
    if not stored:
        raise HTTPException(404, "No pitch video is stored.")
    return FileResponse(
        stored,
        media_type="video/mp4",
        content_disposition_type="inline",
        filename=pitch_video_filename() or "deck.mp4",
    )


@app.post("/settings/pitch")
async def save_pitch(
    pitch_mode: str = Form("pdf"),
    pitch_pdf: UploadFile | None = File(None),
    pitch_video: UploadFile | None = File(None),
):
    try:
        if pitch_pdf and pitch_pdf.filename:
            save_pitch_file(pitch_pdf.filename, await pitch_pdf.read())
        if pitch_video and pitch_video.filename:
            save_pitch_video(pitch_video.filename, await pitch_video.read())
    except ValueError as exc:
        return _redirect("/settings", str(exc), "error")
    mode = "video" if pitch_mode == "video" else "pdf"
    if mode == "video" and pitch_video_file() is None:
        return _redirect("/settings", "Upload an MP4 before showing the video.", "alert")
    if mode == "pdf" and pitch_file() is None:
        return _redirect("/settings", "Upload a PDF before showing the deck.", "alert")
    set_pitch_mode(mode)
    return _redirect("/settings", "Pitch saved.")


@app.post("/sources/imap")
def add_imap(
    label: str = Form(""),
    host_name: str = Form(...),
    port_number: int = Form(993),
    username: str = Form(...),
    password: str = Form(...),
    mailbox: str = Form("INBOX"),
):
    host_name = host_name.strip()
    username = username.strip()
    mailbox = (mailbox or "INBOX").strip() or "INBOX"
    if not host_name or not username or not password:
        return _redirect("/mailboxes", "Host, username, and password are required", "error")
    if port_number < 1 or port_number > 65535:
        return _redirect("/mailboxes", "Port must be between 1 and 65535", "error")
    try:
        check_login(host_name, port_number, username, password, mailbox)
    except ConnectorError as exc:
        return _redirect("/mailboxes", str(exc), "error")
    create_source(
        "imap",
        label.strip() or username,
        {"host": host_name, "port": port_number, "username": username, "mailbox": mailbox},
        {"password": password},
    )
    return _redirect("/mailboxes", "IMAP mailbox connected")


@app.post("/sources/gmail/secret")
async def upload_google_secret(client_secret: UploadFile = File(...)):
    raw = await client_secret.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _redirect("/mailboxes", "That file is not valid Google client JSON", "error")
    if "installed" not in payload and "web" not in payload:
        return _redirect("/mailboxes", "Use a Google OAuth client JSON (web or desktop)", "error")
    path = google_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return _redirect("/mailboxes", "Google client saved. You can connect Gmail now.")


@app.get("/sources/gmail/start")
def gmail_start():
    path = google_secret_path()
    if not path.exists():
        return _redirect("/mailboxes", "Upload a Google OAuth client JSON first", "error")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        str(path),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        redirect_uri=oauth_redirect_uri(),
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    _oauth_states[state] = "pending"
    return RedirectResponse(auth_url, status_code=302)


@app.get("/oauth/google/callback")
def gmail_callback(request: Request):
    state = request.query_params.get("state", "")
    if state not in _oauth_states:
        return _redirect("/mailboxes", "Gmail connection expired. Start it again.", "error")
    _oauth_states.pop(state, None)
    if request.query_params.get("error"):
        return _redirect("/mailboxes", "Gmail connection was cancelled", "alert")
    path = google_secret_path()
    from google_auth_oauthlib.flow import Flow

    from app.connectors.gmail import profile_email, secret_from_credentials

    flow = Flow.from_client_secrets_file(
        str(path),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        redirect_uri=oauth_redirect_uri(),
        state=state,
    )
    try:
        flow.fetch_token(authorization_response=str(request.url))
        creds = flow.credentials
        email = profile_email(creds)
    except Exception:
        return _redirect("/mailboxes", "Gmail connection failed. Check the redirect URI in Google Cloud.", "error")
    create_source("gmail", email, {"email": email}, secret_from_credentials(creds))
    return _redirect("/mailboxes", "Gmail connected")


@app.post("/sources/{source_id}/delete")
def remove_source(source_id: int):
    if not get_source(source_id):
        return _redirect("/mailboxes", "Mailbox not found", "error")
    delete_source(source_id)
    return _redirect("/mailboxes", "Mailbox removed")


@app.post("/sources/file")
async def import_file(label: str = Form(""), mail_file: UploadFile = File(...)):
    raw = await mail_file.read()
    try:
        records = parse_mail_file(mail_file.filename or "", raw)
    except ImportError as exc:
        return _redirect("/mailboxes", str(exc), "error")
    filename = mail_file.filename or "messages"
    source_id = create_source(
        "file",
        (label or "").strip() or filename,
        {"filename": filename, "count": len(records)},
        {},
    )
    for record in records:
        upsert_message(
            source_id,
            record["external_id"],
            record["senddate"],
            record["sender"],
            record["subject"],
            record["message"],
            True,
            0,
            recipient=record["recipient"],
            body=record["message"],
        )
    if not resolve_llm()["api_key"]:
        return _redirect("/settings", f"Imported {len(records)} messages. Add an API key to analyse them.", "alert")
    if has_active_run():
        return _redirect("/mailboxes", f"Imported {len(records)} messages. A scan is already running.", "alert")
    budget = int(setting("token_budget") or default_token_budget())
    run_id = create_run(source_id, "import", budget)
    threading.Thread(
        target=execute_scan,
        args=(run_id, 1, len(records), False),
        daemon=True,
        name=f"scan-{run_id}",
    ).start()
    return _redirect(f"/mailboxes?run={run_id}", f"Imported {len(records)} messages", "info")


@app.post("/scans")
def start_scan(
    source_id: int = Form(...),
    years: int = Form(3),
    max_messages: int = Form(3000),
    token_budget: int = Form(0),
    force: str = Form(""),
):
    source = get_source(source_id)
    if not source:
        return _redirect("/mailboxes", "Choose a mailbox", "error")
    if has_active_run():
        return _redirect("/mailboxes", "A scan is already running", "alert")
    if not resolve_llm()["api_key"]:
        return _redirect("/settings", "Add an API key in settings before scanning", "error")
    years = min(15, max(1, years))
    max_messages = min(20000, max(1, max_messages))
    budget = token_budget or int(setting("token_budget") or default_token_budget())
    budget = min(10_000_000, max(10_000, budget))
    run_id = create_run(source_id, window_start(years), budget)
    thread = threading.Thread(
        target=execute_scan,
        args=(run_id, years, max_messages, bool(force)),
        daemon=True,
        name=f"scan-{run_id}",
    )
    thread.start()
    return _redirect(f"/mailboxes?run={run_id}", "Scan started", "info")


@app.post("/scans/{run_id}/stop")
def stop_scan(run_id: int):
    run = get_run(run_id)
    if not run:
        raise HTTPException(404)
    if run["status"] in {"queued", "running"}:
        update_run(run_id, status="stopping", note="Stopping")
    return _redirect("/mailboxes", "Stopping the scan", "info")


@app.get("/scans/{run_id}.json")
def scan_status(run_id: int):
    run = get_run(run_id)
    if not run:
        raise HTTPException(404)
    return {
        "id": run["id"],
        "status": run["status"],
        "messages_seen": run["messages_seen"],
        "messages_screened": run["messages_screened"],
        "batches_done": run["batches_done"],
        "tokens_used": run["tokens_used"],
        "token_budget": run["token_budget"],
        "note": run["note"] or "",
        "error": run["error"] or "",
        "findings": finding_counts()["all"],
    }


@app.get("/findings/{finding_id}/messages")
def finding_messages(finding_id: int):
    rows = evidence_messages(finding_id)
    if not rows:
        raise HTTPException(404, "No source message is stored for this asset.")
    messages = []
    for row in rows:
        text = message_body(row)
        messages.append(
            {
                "date": (row.get("message_date") or row.get("evidence_date") or "")[:16],
                "from": row.get("from_addr") or "",
                "to": row.get("recipient") or "",
                "subject": row.get("subject") or row.get("evidence_subject") or "",
                "body": text,
            }
        )
    return {"messages": messages}


@app.post("/findings/{finding_id}/status")
def update_finding_status(
    request: Request,
    finding_id: int,
    status: str = Form(...),
    back: str = Form("active"),
):
    if status not in {"candidate", "confirmed", "dismissed"}:
        raise HTTPException(400)
    if back not in {"active", "candidate", "confirmed", "dismissed", "all", "discovered", "identified", "secured", "processing", "closed"}:
        back = "active"
    row = get_finding(finding_id)
    if not row:
        raise HTTPException(404, "That asset is not in the vault.")
    try:
        if status == "dismissed":
            advance(finding_id, "dismissed", "Dismissed from the asset list.")
            stage = "dismissed"
        elif status == "confirmed" and row.get("stage") == "discovered":
            advance(finding_id, "identified")
            stage = "identified"
        elif status == "candidate" and row.get("stage") == "dismissed":
            update_finding_case(finding_id, "discovered", "candidate")
            record_case_event(finding_id, "restored", "Restored", "Returned to Discovered.")
            stage = "discovered"
        else:
            stage = row.get("stage") or "discovered"
    except CaseError as exc:
        raise HTTPException(400, str(exc)) from exc
    if request.headers.get("x-requested-with") == "fetch":
        counts = finding_counts()
        return {"ok": True, "status": stage, "counts": counts}
    return _redirect(f"/?status={back}", "Inventory updated")
