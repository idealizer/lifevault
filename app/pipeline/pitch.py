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


def pitch_video_file() -> Path | None:
    path = pitch_dir() / "deck.mp4"
    return path if path.is_file() else None


def pitch_video_filename() -> str:
    return setting("pitch_video_filename")


def pitch_display_mode() -> str:
    chosen = setting("pitch_mode")
    has_pdf = pitch_file() is not None
    has_video = pitch_video_file() is not None
    if chosen == "video" and has_video:
        return "video"
    if chosen == "pdf" and has_pdf:
        return "pdf"
    if has_video and not has_pdf:
        return "video"
    return "pdf"


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


def save_pitch_video(filename: str, raw: bytes) -> None:
    if not raw:
        raise ValueError("That file is empty.")
    suffix = Path(filename or "").suffix.lower()
    if suffix != ".mp4" or b"ftyp" not in raw[:32]:
        raise ValueError("Upload an MP4 video.")
    if len(raw) > 200_000_000:
        raise ValueError("That video is larger than 200 MB.")
    name = Path(filename or "deck.mp4").name
    (pitch_dir() / "deck.mp4").write_bytes(raw)
    set_setting("pitch_video_filename", name[:180])


def set_pitch_mode(mode: str) -> None:
    set_setting("pitch_mode", "video" if mode == "video" else "pdf")
