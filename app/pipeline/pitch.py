"""Pitch deck shown on the /pitch page."""

from __future__ import annotations

from pathlib import Path

from app.config import data_dir
from app.db import set_setting, setting


def pitch_dir() -> Path:
    path = data_dir() / "pitch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pitch_file() -> Path | None:
    path = pitch_dir() / "deck.pdf"
    return path if path.is_file() else None


def pitch_filename() -> str:
    return setting("pitch_filename")


def save_pitch_file(filename: str, raw: bytes) -> None:
    if not raw:
        raise ValueError("That file is empty.")
    suffix = Path(filename or "").suffix.lower()
    if suffix != ".pdf" and not raw.startswith(b"%PDF"):
        raise ValueError("Upload a PDF.")
    if len(raw) > 40_000_000:
        raise ValueError("That file is larger than 40 MB.")
    name = Path(filename or "deck.pdf").name
    (pitch_dir() / "deck.pdf").write_bytes(raw)
    set_setting("pitch_filename", name[:180])
