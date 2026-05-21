"""Render PDF pages to PNG for VLM processing."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


def render_page(page: fitz.Page, output_path: Path, zoom: float = 2.0) -> Path:
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(output_path))
    return output_path
