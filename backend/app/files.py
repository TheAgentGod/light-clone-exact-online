from __future__ import annotations

import re
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
NEUTRAL_MIME = {"", "application/octet-stream", "binary/octet-stream"}
ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def check_upload(filename: str, content_type: str | None, size: int) -> str | None:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        return "formato no permitido (solo PNG, JPG, JPEG, WEBP)"
    mime = (content_type or "").lower().split(";")[0].strip()
    if mime not in NEUTRAL_MIME and mime not in ALLOWED_MIME:
        return f"tipo de contenido no permitido ({mime})"
    if size > MAX_FILE_BYTES:
        return "supera el limite de 25 MB"
    if size == 0:
        return "archivo vacio"
    return None


def sanitize_name(filename: str, taken: set[str]) -> str:
    stem = Path(filename or "imagen").stem
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "imagen"
    stem = stem[:80]
    candidate = f"{stem}__processed.jpg"
    n = 2
    while candidate in taken:
        candidate = f"{stem}_{n}__processed.jpg"
        n += 1
    taken.add(candidate)
    return candidate
