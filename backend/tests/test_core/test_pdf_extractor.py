from pathlib import Path

import pytest
from app.core.resume_agent.tools.pdf_text_extractor import (
    _extract_pdf_text,
    pdf_text_extractor,
)

MINIMAL_PDF = b"""\
%PDF-1.0
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 100 700 Td (Hello Resume) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
434
%%EOF"""


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_file = tmp_path / "test_resume.pdf"
    pdf_file.write_bytes(MINIMAL_PDF)
    return pdf_file


def test_extract_returns_non_empty_text(sample_pdf: Path):
    result = _extract_pdf_text(str(sample_pdf))
    assert isinstance(result["raw_text"], str)
    assert len(result["raw_text"]) > 0
    assert "Hello" in result["raw_text"] or "Resume" in result["raw_text"]


def test_extract_page_count(sample_pdf: Path):
    result = _extract_pdf_text(str(sample_pdf))
    assert result["page_count"] == 1


def test_extract_truncation(tmp_path: Path):
    pdf_file = tmp_path / "test_resume.pdf"
    pdf_file.write_bytes(MINIMAL_PDF)
    result = _extract_pdf_text(str(pdf_file), max_chars=5)
    assert len(result["raw_text"]) <= 5
    assert result["truncated"] is True


def test_extract_no_truncation(sample_pdf: Path):
    result = _extract_pdf_text(str(sample_pdf), max_chars=100000)
    assert result["truncated"] is False


def test_extract_file_not_found():
    with pytest.raises(FileNotFoundError):
        _extract_pdf_text("/nonexistent/path/resume.pdf")


@pytest.mark.asyncio
async def test_tool_ainvoke(sample_pdf: Path):
    result = await pdf_text_extractor.ainvoke({"file_path": str(sample_pdf)})
    assert isinstance(result, dict)
    assert "raw_text" in result
    assert "page_count" in result
    assert result["page_count"] == 1
