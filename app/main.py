"""Local web UI. Binds to loopback and keeps the mailbox on this machine."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.categories import CATEGORIES, CATEGORY_ICONS, CATEGORY_LABELS
from app.config import default_token_budget, google_secret_path, host, oauth_redirect_uri, port
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
    get_job,
    get_run,
    get_source,
    has_active_run,
    init_db,
    interrupt_stale_runs,
    list_findings,
    list_jobs,
    list_runs,
    list_sources,
    mask_secret,
    save_action_choice,
    set_finding_status,
    set_setting,
    setting,
    update_run,
    upsert_message,
)
from app.llm.client import resolve_llm
from app.pipeline.estate_actions import ESTATE_ACTIONS, actions_for
from app.pipeline.import_mail import ImportError, parse_mail_file
from app.pipeline.letters import estate_file, save_estate_file
from app.pipeline.queue import start_queue
from app.pipeline.scan import backfill_signals, execute_scan, message_body, window_start

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


def _redirect(path: str, notice: str, kind: str = "success") -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}notice={notice}&kind={kind}", status_code=303)


def _render(request: Request, name: str, **context):
    context.setdefault("page", "")
    context["request"] = request
    return templates.TemplateResponse(request, name, context)


def _vault_context(status: str, category: str) -> dict:
    if status not in {"active", "candidate", "confirmed", "dismissed", "all"}:
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
        "page": "vault",
        "estate_actions": ESTATE_ACTIONS,
    }


@app.get("/")
def vault(request: Request, status: str = "active", category: str = ""):
    return _render(request, "vault.html", **_vault_context(status, category))


@app.get("/actions")
def actions_page():
    return RedirectResponse("/", status_code=302)


@app.get("/documents")
def documents_page(request: Request):
    return _render(request, "documents.html", page="documents", jobs=list_jobs())


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
            }
        )
    return {"jobs": rows}


@app.get("/queue/{job_id}/packet")
def queue_packet(job_id: int):
    job = get_job(job_id)
    if not job or not job.get("packet_path"):
        raise HTTPException(404, "That packet is not ready.")
    path = Path(job["packet_path"])
    if not path.is_file():
        raise HTTPException(404, "That packet is not ready.")
    return FileResponse(path, filename=path.name.split("-", 2)[-1], media_type="application/pdf")


@app.post("/findings/{finding_id}/queue")
def queue_finding(finding_id: int, action: str = Form(""), note: str = Form("")):
    rows = [row for row in list_findings("all") if row["id"] == finding_id]
    if not rows:
        raise HTTPException(404, "That asset is not in the vault.")
    options = actions_for(rows[0]["category"])
    custom = note.strip()
    picked = action.strip()
    if custom:
        chosen = custom
    elif picked in options:
        chosen = picked
    else:
        raise HTTPException(400, "Choose a listed step or write your own.")
    set_finding_status(finding_id, "confirmed")
    save_action_choice(finding_id, chosen, custom)
    job_id = enqueue_job(finding_id, chosen)
    return {"ok": True, "status": "confirmed", "job_id": job_id, "counts": finding_counts()}


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
        token_budget=setting("token_budget") or str(default_token_budget()),
        analysed=analysed_counts(),
        scanning=has_active_run(),
        deceased_name=setting("deceased_name"),
        date_of_death=setting("date_of_death"),
        executor_name=setting("executor_name"),
        executor_address=setting("executor_address"),
        has_death_certificate=estate_file("death_certificate") is not None,
        has_authorisation=estate_file("executor_authorisation") is not None,
        death_certificate_name=(estate_file("death_certificate").name if estate_file("death_certificate") else ""),
        authorisation_name=(estate_file("executor_authorisation").name if estate_file("executor_authorisation") else ""),
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
    if token_budget.strip().isdigit():
        set_setting("token_budget", str(min(10_000_000, max(10_000, int(token_budget)))))
    return _redirect("/settings", "Settings saved")


@app.post("/settings/estate")
async def save_estate(
    deceased_name: str = Form(""),
    date_of_death: str = Form(""),
    executor_name: str = Form(""),
    executor_address: str = Form(""),
    death_certificate: UploadFile | None = File(None),
    executor_authorisation: UploadFile | None = File(None),
):
    set_setting("deceased_name", deceased_name.strip()[:200])
    set_setting("date_of_death", date_of_death.strip()[:40])
    set_setting("executor_name", executor_name.strip()[:200])
    set_setting("executor_address", executor_address.strip()[:500])
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
    if back not in {"active", "candidate", "confirmed", "dismissed", "all"}:
        back = "active"
    set_finding_status(finding_id, status)
    if request.headers.get("x-requested-with") == "fetch":
        counts = finding_counts()
        return {"ok": True, "status": status, "counts": counts}
    return _redirect(f"/?status={back}", "Inventory updated")
