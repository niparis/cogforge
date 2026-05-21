"""Page text extraction from PyMuPDF."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


def extract_page_text(page: fitz.Page) -> str:
    return page.get_text("text", sort=True).strip()


def write_page_text(document_id: str, page_number: int, text: str, pages_dir: Path) -> Path:
    path = pages_dir / f"page-{page_number:03d}.text.md"
    frontmatter = (
        f"---\n"
        f"document_id: {document_id}\n"
        f"page: {page_number}\n"
        f"artifact_type: extracted_text\n"
        f"---\n"
    )
    heading = f"# Page {page_number} — Extracted Text\n\n"
    path.write_text(frontmatter + heading + text, encoding="utf-8")
    return path
