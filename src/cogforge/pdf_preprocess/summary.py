"""Human-readable ingestion summary."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from cogforge.pdf_preprocess.manifest import DocumentManifest


def write_summary(out_dir: Path, manifest: DocumentManifest) -> Path:
    routes = [p.route for p in manifest.pages]
    route_counts = Counter(routes)

    total_tables = sum(len(p.tables) for p in manifest.pages)
    table_failures = sum(
        1 for p in manifest.pages for t in p.tables if t.extraction_status == "FAILED"
    )

    visual_pages = [p for p in manifest.pages if p.visual_artifact is not None]
    rendered = len(visual_pages)
    vlm_successes = sum(1 for p in visual_pages if p.visual_artifact.vlm_status == "SUCCESS")
    vlm_failures = sum(1 for p in visual_pages if p.visual_artifact.vlm_status == "FAILED")
    vlm_skipped = sum(
        1 for p in visual_pages
        if p.visual_artifact.vlm_status in ("SKIPPED_LIMIT", "SKIPPED_DISABLED")
    )

    attention_rows: list[str] = []
    for p in manifest.pages:
        if p.visual_artifact and p.visual_artifact.vlm_status == "FAILED":
            attention_rows.append(f"| {p.page_number} | VLM failed |")
        for err in p.errors:
            attention_rows.append(f"| {p.page_number} | {err} |")

    route_table = "\n".join(
        f"| {r} | {route_counts.get(r, 0)} |"
        for r in ("TEXT_ONLY", "TABLE_PAGE", "VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE")
    )

    if attention_rows:
        attention_section = "| Page | Reason |\n|---:|---|\n" + "\n".join(attention_rows)
    else:
        attention_section = "_None_"

    lines = [
        f"# Ingestion Summary — {manifest.file_name}",
        "## Document",
        f"- Pages: {manifest.page_count}",
        f"- Source SHA256: `{manifest.source_sha256}`",
        f"- Pipeline version: `{manifest.pipeline_version}`",
        "## Page routing",
        "| Route | Count |",
        "|---|---:|",
        route_table,
        "## Tables",
        f"- Tables extracted: {total_tables}",
        f"- Table extraction failures: {table_failures}",
        "## VLM",
        f"- Pages rendered: {rendered}",
        f"- VLM successes: {vlm_successes}",
        f"- VLM failures: {vlm_failures}",
        f"- VLM skipped due to cap: {vlm_skipped}",
        "## Pages requiring attention",
        attention_section,
    ]

    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
