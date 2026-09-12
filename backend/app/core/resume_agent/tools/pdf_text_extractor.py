from __future__ import annotations

import asyncio
from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

from app.config import get_settings


def _extract_pdf_text(file_path: str, max_chars: int | None = None) -> dict:
    import pdfplumber

    settings = get_settings()
    limit = max_chars or settings.resume_max_text_chars

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    pages_text: list[str] = []
    page_count = 0

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    raw_text = "\n".join(pages_text)
    truncated = len(raw_text) > limit
    if truncated:
        raw_text = raw_text[:limit]
        logger.warning(
            "PDF text truncated: {} chars -> {} chars | file={}",
            len("\n".join(pages_text)), limit, file_path,
        )

    return {
        "raw_text": raw_text,
        "page_count": page_count,
        "truncated": truncated,
    }


@tool
async def pdf_text_extractor(file_path: str) -> dict:
    """Extract text from a PDF resume file using pdfplumber.

    Args:
        file_path: Absolute or relative path to the PDF file.

    Returns:
        Dict with keys: raw_text (str), page_count (int), truncated (bool).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract_pdf_text, file_path)
