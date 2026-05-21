"""PageIndex integration: detect long documents and run page indexing."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from cogforge.config import Config
from cogforge.paths import Paths
from cogforge.state import load_state, PageIndexInfo, SourceState, encode_source_id


@dataclass
class PageIndexResult:
    """Result of a PageIndex run."""
    required: bool
    status: str  # pending | running | complete | failed
    artifact_path: str | None = None
    error: str | None = None
    page_count: int | None = None
    estimated_pages: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PageIndexResult":
        if data is None:
            return cls(required=False, status="pending")
        return cls(
            required=data.get("required", False),
            status=data.get("status", "pending"),
            artifact_path=data.get("artifact_path"),
            error=data.get("error"),
            page_count=data.get("page_count"),
            estimated_pages=data.get("estimated_pages"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "status": self.status,
            "artifact_path": self.artifact_path,
            "error": self.error,
            "page_count": self.page_count,
            "estimated_pages": self.estimated_pages,
        }


def detect_long_document(
    source_state: SourceState,
    config: Config,
    char_override: int | None = None,
    page_override: int | None = None,
) -> bool:
    """Detect whether a source requires PageIndex based on config thresholds.

    A source requires PageIndex if its estimated_chars exceeds the
    character threshold OR its content size suggests it exceeds the
    page threshold.
    """
    long_doc_config = config.long_document
    char_threshold = char_override if char_override is not None else long_doc_config.char_threshold
    page_threshold = page_override if page_override is not None else long_doc_config.page_threshold

    estimated_chars = source_state.content.estimated_chars or 0

    # If we have page count from content info, use it
    estimated_pages = source_state.content.estimated_pages
    if estimated_pages is not None and estimated_pages >= page_threshold:
        return True

    # Fall back to character threshold
    if estimated_chars >= char_threshold:
        return True

    return False


def _ensure_artifacts_dir(paths: Paths, connector: str, source_id: str) -> Path:
    """Get and create the PageIndex artifact directory."""
    artifact_dir = paths.connector_pageindex(connector, source_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def run_pageindex(
    source_state: SourceState,
    paths: Paths,
    config: Config,
    *,
    force: bool = False,
    char_override: int | None = None,
    page_override: int | None = None,
) -> PageIndexResult:
    """Run PageIndex for a source, producing artifact files.

    Args:
        source_state: The source state to index.
        paths: Resolved wiki paths.
        config: Loaded config for thresholds.
        force: Re-run even if artifacts already exist.
        char_override: Override character threshold.
        page_override: Override page threshold.

    Returns:
        PageIndexResult with status and artifact info.
    """
    is_required = detect_long_document(source_state, config, char_override, page_override)

    if not is_required and not force:
        return PageIndexResult(
            required=False,
            status="complete",
            artifact_path=None,
        )

    connector_dir = source_state.connector
    source_id_encoded = encode_source_id(source_state.id)
    artifact_dir = _ensure_artifacts_dir(paths, connector_dir, source_id_encoded)
    tree_path = artifact_dir / "tree.yaml"
    pages_path = artifact_dir / "pages.yaml"
    metadata_path = artifact_dir / "metadata.yaml"

    # Check if already complete
    if not force and tree_path.is_file() and pages_path.is_file() and metadata_path.is_file():
        return PageIndexResult(
            required=is_required,
            status="complete",
            artifact_path=str(artifact_dir),
        )

    try:
        # Create skeleton artifacts
        # In a real implementation, this would call an actual PageIndex tool
        # that parses the document into structured pages

        # --- pages.yaml: structured page breakdown ---
        estimated_chars = source_state.content.estimated_chars or 0
        estimated_pages = max(1, estimated_chars // 2000) if estimated_chars else 1

        pages_data = []
        chars_per_page = estimated_chars // estimated_pages if estimated_pages > 0 else 0
        for i in range(estimated_pages):
            start_char = i * chars_per_page
            end_char = min((i + 1) * chars_per_page, estimated_chars) if i < estimated_pages - 1 else estimated_chars
            pages_data.append({
                "page": i + 1,
                "start_char": start_char,
                "end_char": end_char,
                "heading": f"Page {i + 1}",
                "summary": "",
            })

        pages_yaml = yaml.dump({"pages": pages_data, "total_pages": estimated_pages}, default_flow_style=False, sort_keys=False)
        pages_path.write_text(pages_yaml, encoding="utf-8")

        # --- tree.yaml: document structure ---
        tree_data = {
            "version": 1,
            "source_id": source_state.id,
            "connector": source_state.connector,
            "root": {
                "title": source_state.origin.title or source_state.id,
                "children": [
                    {"title": f"Section {i + 1}", "page": i + 1}
                    for i in range(min(estimated_pages, 50))
                ],
            },
        }
        tree_yaml = yaml.dump(tree_data, default_flow_style=False, sort_keys=False)
        tree_path.write_text(tree_yaml, encoding="utf-8")

        # --- metadata.yaml: indexing metadata ---
        now = source_state.runs.last_sync or "unknown"
        metadata_data = {
            "version": 1,
            "source_id": source_state.id,
            "connector": source_state.connector,
            "indexed_at": now,
            "char_threshold": char_override or config.long_document.char_threshold,
            "page_threshold": page_override or config.long_document.page_threshold,
            "estimated_chars": estimated_chars,
            "estimated_pages": estimated_pages,
            "status": "complete",
        }
        metadata_yaml = yaml.dump(metadata_data, default_flow_style=False, sort_keys=False)
        metadata_path.write_text(metadata_yaml, encoding="utf-8")

        return PageIndexResult(
            required=is_required,
            status="complete",
            artifact_path=str(artifact_dir),
            page_count=estimated_pages,
            estimated_pages=estimated_pages,
        )

    except Exception as e:
        return PageIndexResult(
            required=is_required,
            status="failed",
            artifact_path=str(artifact_dir),
            error=str(e),
        )


def get_pageindex_status(
    paths: Paths,
    source_state: SourceState,
) -> PageIndexInfo:
    """Get current PageIndex status for a source by reading artifacts."""
    connector_dir = source_state.connector
    source_id_encoded = encode_source_id(source_state.id)
    artifact_dir = paths.connector_pageindex(connector_dir, source_id_encoded)

    if not artifact_dir.is_dir():
        return PageIndexInfo(
            required=False,
            status=None,
            artifact_path=None,
        )

    metadata_path = artifact_dir / "metadata.yaml"
    if metadata_path.is_file():
        try:
            data = yaml.safe_load(metadata_path.read_text())
            if isinstance(data, dict):
                return PageIndexInfo(
                    required=data.get("required", False) if not detect_long_document(source_state, Config()) else True,
                    status="complete",
                    artifact_path=str(artifact_dir),
                    error=data.get("error"),
                )
        except Exception:
            pass

    # Check for partial artifacts
    tree_path = artifact_dir / "tree.yaml"
    pages_path = artifact_dir / "pages.yaml"
    if tree_path.is_file() or pages_path.is_file():
        return PageIndexInfo(
            required=True,
            status="running",
            artifact_path=str(artifact_dir),
        )

    return PageIndexInfo(
        required=False,
        status=None,
        artifact_path=str(artifact_dir),
    )