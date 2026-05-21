"""Integration test for ingest_pdf() using a synthetically created PDF."""
import json
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from cogforge.pdf_preprocess import PDFPreprocessConfig, ingest_pdf
from cogforge.pdf_preprocess.config import VLMConfig


def _make_test_pdf(path: Path) -> None:
    """Create a minimal 3-page PDF: text-only, table-like, image."""
    doc = fitz.open()

    # Page 1: dense text
    page = doc.new_page()
    page.insert_text((72, 72), "This is a text-only page. " * 40, fontsize=11)

    # Page 2: text with a simple rectangle grid (table-like layout)
    page = doc.new_page()
    page.insert_text((72, 72), "Header row with table data below.", fontsize=11)
    # Draw a simple 2x2 grid
    for row in range(3):
        for col in range(2):
            rect = fitz.Rect(72 + col * 200, 100 + row * 30, 260 + col * 200, 128 + row * 30)
            page.draw_rect(rect, color=(0, 0, 0), width=1)

    # Page 3: very little text, large rectangle (simulates diagram)
    page = doc.new_page()
    page.insert_text((72, 72), "Fig.", fontsize=11)
    # Large filled rect covering most of page — drives up drawing_area_ratio
    rect = fitz.Rect(50, 100, 545, 700)
    page.draw_rect(rect, color=(0.2, 0.4, 0.8), fill=(0.2, 0.4, 0.8), width=0)

    doc.save(str(path))
    doc.close()


@pytest.fixture
def test_pdf(tmp_path):
    pdf_path = tmp_path / "test-doc.pdf"
    _make_test_pdf(pdf_path)
    return pdf_path


def test_pipeline_creates_all_outputs(test_pdf, tmp_path):
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    manifest = ingest_pdf(test_pdf, out_dir, cfg)

    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "summary.md").exists()
    enriched = list((out_dir / "enriched").glob("*.enriched.md"))
    assert len(enriched) == 1


def test_pipeline_page_count(test_pdf, tmp_path):
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    manifest = ingest_pdf(test_pdf, out_dir, cfg)
    assert manifest.page_count == 3


def test_pipeline_creates_page_text_files(test_pdf, tmp_path):
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    ingest_pdf(test_pdf, out_dir, cfg)
    pages_dir = out_dir / "pages"
    assert (pages_dir / "page-001.text.md").exists()
    assert (pages_dir / "page-002.text.md").exists()
    assert (pages_dir / "page-003.text.md").exists()


def test_pipeline_manifest_valid_json(test_pdf, tmp_path):
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    ingest_pdf(test_pdf, out_dir, cfg)
    data = json.loads((out_dir / "manifest.json").read_text())
    assert data["page_count"] == 3
    assert len(data["pages"]) == 3
    assert all("route" in p for p in data["pages"])


def test_pipeline_enriched_markdown_readable(test_pdf, tmp_path):
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    ingest_pdf(test_pdf, out_dir, cfg)
    enriched = list((out_dir / "enriched").glob("*.enriched.md"))[0]
    content = enriched.read_text()
    assert "## Page 1" in content
    assert "## Page 2" in content
    assert "## Page 3" in content
    assert "### Provenance" in content


def test_pipeline_page3_routed_visual_or_low_text(test_pdf, tmp_path):
    """Page 3 has a large filled rectangle — should classify as visual or low-text-visual."""
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    manifest = ingest_pdf(test_pdf, out_dir, cfg)
    page3 = manifest.pages[2]
    assert page3.route in ("VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE"), f"Unexpected route: {page3.route}"


def test_pipeline_mock_vlm_produces_visual_summaries(test_pdf, tmp_path):
    out_dir = tmp_path / "out"
    # VLM enabled, mock model — should write visual.md for visual pages
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=True, model="mock"))
    manifest = ingest_pdf(test_pdf, out_dir, cfg)
    visual_pages = [p for p in manifest.pages if p.visual_artifact is not None]
    for p in visual_pages:
        assert p.visual_artifact.vlm_status in ("SUCCESS", "SKIPPED_DISABLED", "SKIPPED_LIMIT")
        if p.visual_artifact.vlm_status == "SUCCESS":
            assert p.visual_artifact.visual_markdown_path is not None
            assert Path(p.visual_artifact.visual_markdown_path).exists()


def test_pipeline_caching_skips_existing(test_pdf, tmp_path):
    """Running twice without --force should not re-extract text files."""
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    ingest_pdf(test_pdf, out_dir, cfg)
    # Record mtime of page-001
    mtime = (out_dir / "pages" / "page-001.text.md").stat().st_mtime
    ingest_pdf(test_pdf, out_dir, cfg)
    assert (out_dir / "pages" / "page-001.text.md").stat().st_mtime == mtime


def test_pipeline_force_rerenders(test_pdf, tmp_path):
    """--force should rewrite text files."""
    out_dir = tmp_path / "out"
    cfg = PDFPreprocessConfig(vlm=VLMConfig(enabled=False, model="mock"))
    ingest_pdf(test_pdf, out_dir, cfg)
    mtime1 = (out_dir / "pages" / "page-001.text.md").stat().st_mtime

    import time
    time.sleep(0.05)

    cfg_force = PDFPreprocessConfig(force=True, vlm=VLMConfig(enabled=False, model="mock"))
    ingest_pdf(test_pdf, out_dir, cfg_force)
    mtime2 = (out_dir / "pages" / "page-001.text.md").stat().st_mtime
    assert mtime2 >= mtime1
