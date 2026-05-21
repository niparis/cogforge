"""Unit tests for markdown_builder.py."""
import tempfile
from pathlib import Path

import pytest

from cogforge.pdf_preprocess.manifest import (
    DocumentManifest,
    PageManifest,
    TableArtifact,
    VisualArtifact,
    VisualSignals,
)
from cogforge.pdf_preprocess.markdown_builder import build_enriched_markdown


def _signals() -> VisualSignals:
    return VisualSignals(
        page_width=595.0, page_height=842.0, page_area=500990.0,
        text_blocks=5, image_blocks=0, image_xobjects=0, drawing_count=0,
        table_count=0, text_area_ratio=0.4, image_area_ratio=0.0,
        drawing_area_ratio=0.0, visual_area_ratio=0.0,
        has_visual_hint=False, visual_hints=[],
    )


def _manifest(pages) -> DocumentManifest:
    return DocumentManifest(
        document_id="my-doc",
        source_path="raw/my-doc.pdf",
        source_sha256="abc123",
        file_name="my-doc.pdf",
        page_count=len(pages),
        pipeline_version="pdf-preprocess-0.1",
        created_at="2026-05-15T00:00:00+00:00",
        config={},
        pages=pages,
    )


def test_includes_document_header():
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _manifest([
            PageManifest(page_number=1, route="TEXT_ONLY", text_chars=100,
                         text_path=None, visual_signals=_signals()),
        ])
        out_path = build_enriched_markdown(Path(tmp), manifest)
        content = out_path.read_text()
        assert "# my-doc" in content
        assert "document_id: my-doc" in content


def test_includes_every_page():
    pages = [
        PageManifest(page_number=i, route="TEXT_ONLY", text_chars=100,
                     text_path=None, visual_signals=_signals())
        for i in range(1, 5)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _manifest(pages)
        out_path = build_enriched_markdown(Path(tmp), manifest)
        content = out_path.read_text()
        for i in range(1, 5):
            assert f"## Page {i}" in content


def test_includes_table_markdown(tmp_path):
    # Create a fake table markdown file
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    md_file = tables_dir / "page-001-table-001.md"
    md_file.write_text(
        "---\ndocument_id: my-doc\npage: 1\nartifact_type: table\ntable_id: page-001-table-001\n---\n"
        "# Table page-001-table-001\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    table = TableArtifact(
        table_id="page-001-table-001",
        page_number=1,
        csv_path=str(tables_dir / "page-001-table-001.csv"),
        markdown_path=str(md_file),
        rows=1, columns=2,
        extraction_status="SUCCESS",
    )
    page = PageManifest(
        page_number=1, route="TABLE_PAGE", text_chars=200,
        text_path=None, visual_signals=_signals(), tables=[table],
    )
    manifest = _manifest([page])
    out_path = build_enriched_markdown(tmp_path, manifest)
    content = out_path.read_text()
    assert "| A | B |" in content
    assert "TABLE_PAGE" in content


def test_includes_visual_summary(tmp_path):
    visuals_dir = tmp_path / "visuals"
    visuals_dir.mkdir()
    vis_md = visuals_dir / "page-009.visual.md"
    vis_md.write_text(
        "---\ndocument_id: my-doc\npage: 9\nartifact_type: visual_summary\n"
        "source_image: visuals/page-009.png\nvlm_model: mock\n---\n"
        "# Visual Summary — Page 9\n\n## Visual type\nMock visual.\n",
        encoding="utf-8",
    )
    va = VisualArtifact(
        page_number=9,
        image_path=str(visuals_dir / "page-009.png"),
        visual_markdown_path=str(vis_md),
        vlm_model="mock",
        vlm_status="SUCCESS",
        reason=[],
    )
    sig = VisualSignals(
        page_width=595, page_height=842, page_area=500990,
        text_blocks=2, image_blocks=1, image_xobjects=1, drawing_count=0,
        table_count=0, text_area_ratio=0.1, image_area_ratio=0.3,
        drawing_area_ratio=0.0, visual_area_ratio=0.3,
        has_visual_hint=False, visual_hints=[],
    )
    page = PageManifest(
        page_number=9, route="VISUAL_PAGE", text_chars=100,
        text_path=None, visual_signals=sig, visual_artifact=va,
    )
    manifest = _manifest([page])
    out_path = build_enriched_markdown(tmp_path, manifest)
    content = out_path.read_text()
    assert "## Visual type" in content
    assert "Mock visual." in content


def test_includes_provenance():
    page = PageManifest(
        page_number=1, route="TEXT_ONLY", text_chars=100,
        text_path="pages/page-001.text.md", visual_signals=_signals(),
    )
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _manifest([page])
        out_path = build_enriched_markdown(Path(tmp), manifest)
        content = out_path.read_text()
        assert "### Provenance" in content
        assert "pages/page-001.text.md" in content


def test_handles_missing_vlm_summary():
    va = VisualArtifact(
        page_number=5,
        image_path="visuals/page-005.png",
        visual_markdown_path=None,
        vlm_model="mock",
        vlm_status="SKIPPED_DISABLED",
        reason=[],
    )
    page = PageManifest(
        page_number=5, route="VISUAL_PAGE", text_chars=50,
        text_path=None, visual_signals=_signals(), visual_artifact=va,
    )
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _manifest([page])
        out_path = build_enriched_markdown(Path(tmp), manifest)
        content = out_path.read_text()
        assert "SKIPPED_DISABLED" in content


def test_handles_page_errors():
    page = PageManifest(
        page_number=3, route="TEXT_ONLY", text_chars=0,
        text_path=None, visual_signals=_signals(),
        errors=["Text extraction failed: corrupt page"],
    )
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _manifest([page])
        out_path = build_enriched_markdown(Path(tmp), manifest)
        content = out_path.read_text()
        assert "corrupt page" in content


def test_low_text_visual_note_present():
    page = PageManifest(
        page_number=2, route="LOW_TEXT_VISUAL_PAGE", text_chars=100,
        text_path=None, visual_signals=_signals(),
    )
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _manifest([page])
        out_path = build_enriched_markdown(Path(tmp), manifest)
        content = out_path.read_text()
        assert "low extractable text" in content
