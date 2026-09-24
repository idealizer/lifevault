"""Executor letters and the packet that goes with them."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

from fpdf import FPDF

from app.config import data_dir
from app.db import setting

ESTATE_FILES = {
    "death_certificate": "death-certificate",
    "executor_authorisation": "executor-authorisation",
}


def estate_dir() -> Path:
    path = data_dir() / "estate"
    path.mkdir(parents=True, exist_ok=True)
    return path


def outbox_dir() -> Path:
    path = data_dir() / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def estate_file(kind: str) -> Path | None:
    stem = ESTATE_FILES.get(kind)
    if not stem:
        return None
    matches = sorted(estate_dir().glob(stem + ".*"))
    return matches[0] if matches else None


def save_estate_file(kind: str, filename: str, raw: bytes) -> None:
    stem = ESTATE_FILES[kind]
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise ValueError("Upload a PDF or image.")
    if len(raw) > 15_000_000:
        raise ValueError("That file is larger than 15 MB.")
    folder = estate_dir()
    for old in folder.glob(stem + ".*"):
        old.unlink()
    (folder / f"{stem}{suffix}").write_bytes(raw)


def needs_letter(action: str) -> bool:
    text = action.lower()
    quiet = ("do not reply", "ignore", "leave the", "leave it", "record the", "record it", "keep ")
    return not any(phrase in text for phrase in quiet)


def write_packet(job_id: int, finding: dict, action: str) -> tuple[str, str]:
    if not needs_letter(action):
        return "", "Noted. This step does not send a letter."
    letter = outbox_dir() / f"job-{job_id}-letter.pdf"
    _write_letter(letter, finding, action)
    packet = outbox_dir() / f"job-{job_id}.zip"
    with zipfile.ZipFile(packet, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(letter, "letter.pdf")
        attached = []
        for kind, label in (
            ("death_certificate", "death-certificate"),
            ("executor_authorisation", "executor-authorisation"),
        ):
            path = estate_file(kind)
            if path:
                archive.write(path, f"{label}{path.suffix.lower()}")
                attached.append(label.replace("-", " "))
    if attached:
        note = "Letter ready, with " + " and ".join(attached) + "."
    else:
        note = "Letter ready. Add the death certificate and executor authorisation in Settings to include them."
    return str(packet), note


def _write_letter(path: Path, finding: dict, action: str) -> None:
    deceased = setting("deceased_name") or "the deceased"
    died = setting("date_of_death") or ""
    executor = setting("executor_name") or "Executor"
    address = setting("executor_address") or ""
    provider = finding.get("provider") or "the organisation"
    label = finding.get("label") or "the asset"
    identifiers = finding.get("identifiers") or []
    refs = ", ".join(f"{item.get('type', 'ref')} {item.get('value', '')}" for item in identifiers if item.get("value"))
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    lines = [
        executor,
        address,
        date.today().isoformat(),
        "",
        provider,
        "",
        f"Estate of {deceased}" + (f", died {died}" if died else ""),
        "",
        "Dear Sir or Madam,",
        "",
        f"I am acting as executor of the estate of {deceased}.",
        f"Please {action[0].lower() + action[1:]}.",
        f"Asset: {label}.",
    ]
    if refs:
        lines.append(f"Reference: {refs}.")
    lines.extend(
        [
            "",
            "A copy of the death certificate and my authorisation as executor are enclosed when they are on file.",
            "Please confirm in writing when this has been done, and send any closing balance or refund to the estate.",
            "",
            "Yours faithfully,",
            executor,
        ]
    )
    for line in lines:
        pdf.multi_cell(pdf.epw, 8, _latin(line) or " ")
    pdf.output(path)


def _latin(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")
