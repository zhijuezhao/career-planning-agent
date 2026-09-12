from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.config import get_settings


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def save_upload_file(file_bytes: bytes, user_id: int, original_filename: str) -> tuple[str, str]:
    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / f"user_{user_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(original_filename).suffix.lower() or ".pdf"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / stored_name

    file_path.write_bytes(file_bytes)

    content_hash = compute_file_hash(file_bytes)
    return str(file_path), content_hash
