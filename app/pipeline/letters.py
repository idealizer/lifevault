"""Executor letters. The packet is one PDF: the letter, then the certificates."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fpdf import FPDF
from pypdf import PdfWriter

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
    if not raw:
        raise ValueError("That file is empty.")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        if raw.startswith(b"%PDF"):
            suffix = ".pdf"
        elif raw.startswith(b"\x89PNG"):
            suffix = ".png"
        elif raw.startswith(b"\xff\xd8"):
            suffix = ".jpg"
        else:
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


def packet_filename(finding: dict, action: str) -> str:
    provider = finding.get("provider") or finding.get("label") or "estate"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{provider}-{action}").strip("-")
    return (slug[:80] or "estate-letter") + ".pdf"


def write_packet(job_id: int, finding: dict, action: str) -> tuple[str, str]:
    if not needs_letter(action):
        return "", "Noted. This step does not send a letter."
    letter = outbox_dir() / f"job-{job_id}-letter.pdf"
    _write_letter(letter, finding, action)
    packet = outbox_dir() / f"job-{job_id}-{packet_filename(finding, action)}"
    attached = _merge_packet(letter, packet)
    if attached:
        note = "Letter ready, with " + " and ".join(attached) + "."
    else:
        note = "Letter ready. Add the death certificate and executor authorisation in Settings to include them."
    return str(packet), note


def _merge_packet(letter: Path, packet: Path) -> list[str]:
    writer = PdfWriter()
    writer.append(str(letter))
    attached = []
    for kind, label in (
        ("death_certificate", "death certificate"),
        ("executor_authorisation", "executor authorisation"),
    ):
        path = estate_file(kind)
        if not path:
            continue
        if path.suffix.lower() == ".pdf":
            writer.append(str(path))
        else:
            image_pdf = packet.with_name(packet.stem + f"-{kind}.pdf")
            _image_page(image_pdf, path, label)
            writer.append(str(image_pdf))
            image_pdf.unlink(missing_ok=True)
        attached.append(label)
    with packet.open("wb") as handle:
        writer.write(handle)
    return attached


def _image_page(path: Path, image: Path, title: str) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(pdf.epw, 10, _latin(title), new_x="LMARGIN", new_y="NEXT")
    pdf.image(str(image), x=pdf.l_margin, y=pdf.get_y() + 4, w=pdf.epw)
    pdf.output(path)


def _write_letter(path: Path, finding: dict, action: str) -> None:
    deceased = setting("deceased_name") or "the deceased"
    died = setting("date_of_death") or ""
    executor = setting("executor_name") or "Executor"
    address = setting("executor_address") or ""
    provider = finding.get("provider") or "the organisation"
    label = finding.get("label") or "the asset"
    kind = finding.get("asset_kind") or ""
    identifiers = finding.get("identifiers") or []
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
        "Estate of " + deceased + (f", died {died}" if died else ""),
        "",
        "Dear Sir or Madam,",
        "",
        f"I am acting as executor of the estate of {deceased}.",
        "Please " + action[:1].lower() + action[1:] + ".",
        f"Organisation: {provider}.",
        f"Asset: {label}.",
    ]
    if kind:
        lines.append(f"Kind: {kind}.")
    for item in identifiers:
        value = str(item.get("value") or "").strip()
        if value:
            lines.append(f"{item.get('type') or 'Reference'}: {value}.")
    lines.extend(
        [
            "",
            "The death certificate and my authorisation as executor follow this letter.",
            "Please confirm in writing when this has been done, and send any closing balance or refund to the estate.",
            "",
            "Yours faithfully,",
            executor,
        ]
    )
    for line in lines:
        pdf.multi_cell(pdf.epw, 8, _latin(line) or " ", new_x="LMARGIN", new_y="NEXT")
    pdf.output(path)


def _latin(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")
