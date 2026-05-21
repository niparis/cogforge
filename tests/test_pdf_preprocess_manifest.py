"""Unit tests for manifest.py."""
import json
import tempfile
from pathlib import Path

import pytest

from cogforge.pdf_preprocess.manifest import (
    DocumentManifest,
    PageManifest,
    TableArtifact,
    VisualArtifact,
    VisualSignals,
    write_manifest,
)


def _minimal_signals() -> VisualSignals:
    return VisualSignals(
        page_width=595.0, page_height=842.0, page_area=500990.0,
        text_blocks=5, image_blocks=0, image_xobjects=0, drawing_count=0,
        table_count=0, text_area_ratio=0.4, image_area_ratio=0.0,
        drawing_area_ratio=0.0, visual_area_ratio=0.0,
        has_visual_hint=False, visual_hints=[],
    )


def _minimal_manifest(pages=None) -> DocumentManifest:
    if pages is None:
        pages = [
            PageManifest(
                page_number=1,
                route="TEXT_ONLY",
                text_chars=1000,
                text_path="pages/page-001.text.md",
                visual_signals=_minimal_signals(),
            )
        ]
    return DocumentManifest(
        document_id="test-doc",
        source_path="raw/test-doc.pdf",
        source_sha256="abc123",
        file_name="test-doc.pdf",
        page_count=len(pages),
        pipeline_version="pdf-preprocess-0.1",
        created_at="2026-05-15T00:00:00+00:00",
        config={"render_zoom": 2.0},
        pages=pages,
    )


def test_manifest_serializes_valid_json():
    manifest = _minimal_manifest()
    d = manifest.to_dict()
    serialized = json.dumps(d)
    assert json.loads(serialized)["document_id"] == "test-doc"


def test_manifest_contains_page_count():
    manifest = _minimal_manifest()
    d = manifest.to_dict()
    assert d["page_count"] == 1


def test_manifest_contains_all_page_routes():
    pages = []
    for i, route in enumerate(("TEXT_ONLY", "TABLE_PAGE", "VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE"), 1):
        pages.append(PageManifest(
            page_number=i, route=route, text_chars=100,
            text_path=None, visual_signals=_minimal_signals(),
        ))
    manifest = _minimal_manifest(pages=pages)
    routes = {p["route"] for p in manifest.to_dict()["pages"]}
    assert routes == {"TEXT_ONLY", "TABLE_PAGE", "VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE"}


def test_manifest_records_errors():
    page = PageManifest(
        page_number=1, route="TEXT_ONLY", text_chars=0,
        text_path=None, visual_signals=_minimal_signals(),
        errors=["Text extraction failed: something went wrong"],
    )
    manifest = _minimal_manifest(pages=[page])
    d = manifest.to_dict()
    assert d["pages"][0]["errors"] == ["Text extraction failed: something went wrong"]


def test_write_manifest_creates_file():
    manifest = _minimal_manifest()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        path = write_manifest(out, manifest)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["document_id"] == "test-doc"


def test_visual_signals_to_dict():
    sig = _minimal_signals()
    d = sig.to_dict()
    assert d["page_width"] == 595.0
    assert d["has_visual_hint"] is False
    assert isinstance(d["visual_hints"], list)


def test_table_artifact_to_dict():
    t = TableArtifact(
        table_id="page-001-table-001",
        page_number=1,
        csv_path="tables/page-001-table-001.csv",
        markdown_path="tables/page-001-table-001.md",
        rows=3,
        columns=2,
        extraction_status="SUCCESS",
    )
    d = t.to_dict()
    assert d["extraction_status"] == "SUCCESS"
    assert d["rows"] == 3


def test_visual_artifact_to_dict():
    va = VisualArtifact(
        page_number=9,
        image_path="visuals/page-009.png",
        visual_markdown_path="visuals/page-009.visual.md",
        vlm_model="mock",
        vlm_status="SUCCESS",
        reason=["image_area_ratio=0.25"],
    )
    d = va.to_dict()
    assert d["vlm_status"] == "SUCCESS"
    assert d["vlm_model"] == "mock"
