"""Executor letters. The packet is one PDF: the letter, then the certificates."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fpdf import FPDF
from pypdf import PdfWriter

from app.config import data_dir
from app.db import setting
from app.pipeline.letter_copy import compose, detect_language

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


def write_packet(job_id: int, finding: dict, action: str, source_text: str = "") -> tuple[str, str]:
    if not needs_letter(action):
        return "", "Noted. This step does not send a letter."
    letter = outbox_dir() / f"job-{job_id}-letter.pdf"
    _write_letter(letter, finding, action, source_text)
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


def _write_letter(path: Path, finding: dict, action: str, source_text: str = "") -> None:
    contact = executor_contact()
    provider = finding.get("provider") or ""
    label = finding.get("label") or ""
    asset = label or provider or "the relationship"
    lang = detect_language(source_text)
    letter = compose(
        action,
        lang,
        {
            "deceased": setting("deceased_name"),
            "died": setting("date_of_death"),
            "provider": provider or "the organisation",
            "asset": asset,
            "identifiers": finding.get("identifiers") or [],
            "estate_bank": setting("estate_bank"),
            "estate_iban": setting("estate_iban"),
            "estate_swift": setting("estate_swift"),
        },
    )
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()
    family = _use_font(pdf)
    pdf.set_font(family, size=11)
    for line in contact["lines"]:
        pdf.multi_cell(pdf.epw, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font(family, size=11)
    pdf.multi_cell(pdf.epw, 6, provider or " ", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.cell(pdf.epw, 6, _date_line(lang), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font(family, "B", 12)
    pdf.multi_cell(pdf.epw, 7, letter["subject"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font(family, size=11)
    pdf.multi_cell(pdf.epw, 6, letter["salutation"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for paragraph in letter["paragraphs"]:
        pdf.multi_cell(pdf.epw, 6, paragraph, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
    pdf.ln(4)
    pdf.multi_cell(pdf.epw, 6, letter["closing"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.multi_cell(pdf.epw, 6, contact["signature"], new_x="LMARGIN", new_y="NEXT")
    if contact["company"]:
        pdf.multi_cell(pdf.epw, 6, contact["company"], new_x="LMARGIN", new_y="NEXT")
    pdf.output(path)


def executor_contact() -> dict:
    company = setting("executor_company").strip()
    first = setting("executor_firstname").strip()
    last = setting("executor_lastname").strip()
    name = " ".join(part for part in (first, last) if part) or setting("executor_name").strip() or "Executor"
    street = " ".join(
        part
        for part in (setting("executor_street").strip(), setting("executor_street_no").strip())
        if part
    )
    city = " ".join(
        part for part in (setting("executor_zip").strip(), setting("executor_city").strip()) if part
    )
    country = setting("executor_country").strip()
    lines = [line for line in (company, name, street, city, country) if line]
    if not lines:
        legacy = setting("executor_address").strip()
        lines = [name] + ([legacy] if legacy else [])
    return {"lines": lines, "signature": name, "company": company}


def _date_line(lang: str) -> str:
    today = date.today()
    months = {
        "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"),
        "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"),
        "it": ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"),
        "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    }
    names = months.get(lang) or months["en"]
    if lang == "en":
        return f"{today.day} {names[today.month - 1]} {today.year}"
    return f"{today.day}. {names[today.month - 1]} {today.year}"


def _use_font(pdf: FPDF) -> str:
    regular = Path(__file__).resolve().parent.parent / "fonts" / "DejaVuSans.ttf"
    bold = regular.with_name("DejaVuSans-Bold.ttf")
    if regular.is_file() and bold.is_file():
        pdf.add_font("DejaVu", "", str(regular))
        pdf.add_font("DejaVu", "B", str(bold))
        return "DejaVu"
    return "Helvetica"
