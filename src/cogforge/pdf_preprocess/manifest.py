"""Data models and serialization for the PDF preprocessing pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class VisualSignals:
    page_width: float
    page_height: float
    page_area: float
    text_blocks: int
    image_blocks: int
    image_xobjects: int
    drawing_count: int
    table_count: int
    text_area_ratio: float
    image_area_ratio: float
    drawing_area_ratio: float
    visual_area_ratio: float
    has_visual_hint: bool
    visual_hints: list[str]

    def to_dict(self) -> dict:
        return {
            "page_width": self.page_width,
            "page_height": self.page_height,
            "page_area": self.page_area,
            "text_blocks": self.text_blocks,
            "image_blocks": self.image_blocks,
            "image_xobjects": self.image_xobjects,
            "drawing_count": self.drawing_count,
            "table_count": self.table_count,
            "text_area_ratio": self.text_area_ratio,
            "image_area_ratio": self.image_area_ratio,
            "drawing_area_ratio": self.drawing_area_ratio,
            "visual_area_ratio": self.visual_area_ratio,
            "has_visual_hint": self.has_visual_hint,
            "visual_hints": self.visual_hints,
        }


@dataclass
class TableArtifact:
    table_id: str
    page_number: int
    csv_path: str
    markdown_path: str
    rows: int
    columns: int
    extraction_status: str  # SUCCESS | EMPTY | FAILED | LOW_QUALITY

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id,
            "page_number": self.page_number,
            "csv_path": self.csv_path,
            "markdown_path": self.markdown_path,
            "rows": self.rows,
            "columns": self.columns,
            "extraction_status": self.extraction_status,
        }


@dataclass
class VisualArtifact:
    page_number: int
    image_path: str
    visual_markdown_path: Optional[str]
    vlm_model: Optional[str]
    vlm_status: str  # NOT_REQUIRED | SKIPPED_DISABLED | SKIPPED_LIMIT | SUCCESS | FAILED
    reason: list[str]

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "image_path": self.image_path,
            "visual_markdown_path": self.visual_markdown_path,
            "vlm_model": self.vlm_model,
            "vlm_status": self.vlm_status,
            "reason": self.reason,
        }


@dataclass
class PageManifest:
    page_number: int
    route: str
    text_chars: int
    text_path: Optional[str]
    visual_signals: VisualSignals
    tables: list[TableArtifact] = field(default_factory=list)
    visual_artifact: Optional[VisualArtifact] = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "route": self.route,
            "text_chars": self.text_chars,
            "text_path": self.text_path,
            "visual_signals": self.visual_signals.to_dict(),
            "tables": [t.to_dict() for t in self.tables],
            "visual_artifact": self.visual_artifact.to_dict() if self.visual_artifact else None,
            "errors": self.errors,
        }


@dataclass
class DocumentManifest:
    document_id: str
    source_path: str
    source_sha256: str
    file_name: str
    page_count: int
    pipeline_version: str
    created_at: str
    config: dict
    pages: list[PageManifest] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "file_name": self.file_name,
            "page_count": self.page_count,
            "pipeline_version": self.pipeline_version,
            "created_at": self.created_at,
            "config": self.config,
            "pages": [p.to_dict() for p in self.pages],
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_manifest(out_dir: Path, manifest: DocumentManifest) -> Path:
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return path
