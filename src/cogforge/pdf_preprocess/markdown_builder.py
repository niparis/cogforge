"""Build the enriched Markdown document from all page artifacts."""
from __future__ import annotations

from pathlib import Path

from cogforge.pdf_preprocess.manifest import DocumentManifest, PageManifest


def _read_body(path: str) -> str:
    """Read a frontmatter-prefixed file and return only the body."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        parts = raw.split("---\n", 2)
        return parts[2].strip() if len(parts) >= 3 else raw.strip()
    except Exception:
        return ""


def _page_section(page: PageManifest) -> str:
    lines: list[str] = []

    lines.append("---")
    lines.append(f"## Page {page.page_number}")
    lines.append("")
    lines.append("### Page route")
    lines.append(f"`{page.route}`")

    if page.route == "LOW_TEXT_VISUAL_PAGE":
        lines.append("")
        lines.append(
            "> **Note:** This page had low extractable text and significant visual content. "
            "The visual summary may carry most of the page meaning."
        )

    # Extracted text
    lines.append("")
    lines.append("### Extracted text")
    lines.append("")
    if page.text_path:
        body = _read_body(page.text_path)
        # Strip the leading heading that write_page_text adds
        body_lines = body.splitlines()
        start = 1 if (body_lines and body_lines[0].startswith("# Page")) else 0
        content = "\n".join(body_lines[start:]).strip()
        lines.append(content or "_No text extracted._")
    else:
        lines.append("_No text extracted._")

    # Tables
    if page.tables:
        lines.append("")
        lines.append("### Extracted tables")
        for table in page.tables:
            lines.append("")
            lines.append(f"#### Table {table.table_id}")
            if table.extraction_status == "SUCCESS" and table.markdown_path:
                body = _read_body(table.markdown_path)
                # Strip the heading line added by extract_tables
                body_lines = body.splitlines()
                start = 1 if (body_lines and body_lines[0].startswith("# Table")) else 0
                lines.append("\n".join(body_lines[start:]).strip())
            else:
                lines.append(f"_Table extraction status: {table.extraction_status}_")
            lines.append(f"Source: page {table.page_number}.")

    # Visual summary
    if page.visual_artifact:
        va = page.visual_artifact
        lines.append("")
        lines.append("### Visual summary")
        lines.append("")
        if va.vlm_status == "SUCCESS" and va.visual_markdown_path:
            body = _read_body(va.visual_markdown_path)
            # Strip leading heading
            body_lines = body.splitlines()
            start = 1 if (body_lines and body_lines[0].startswith("# Visual Summary")) else 0
            lines.append("\n".join(body_lines[start:]).strip())
        else:
            lines.append(f"_Visual summary status: {va.vlm_status}_")

    # Provenance
    lines.append("")
    lines.append("### Provenance")
    lines.append(f"- Source page: {page.page_number}")
    if page.text_path:
        lines.append(f"- Text artifact: `{page.text_path}`")
    for table in page.tables:
        lines.append(f"- Table artifact: `{table.markdown_path}`")
        lines.append(f"- Table CSV: `{table.csv_path}`")
    if page.visual_artifact:
        lines.append(f"- Rendered page image: `{page.visual_artifact.image_path}`")
        if page.visual_artifact.visual_markdown_path:
            lines.append(f"- Visual summary artifact: `{page.visual_artifact.visual_markdown_path}`")

    if page.errors:
        lines.append("")
        lines.append("### Errors")
        for err in page.errors:
            lines.append(f"- {err}")

    return "\n".join(lines)


def build_enriched_markdown(out_dir: Path, manifest: DocumentManifest) -> Path:
    enriched_dir = out_dir / "enriched"
    enriched_dir.mkdir(parents=True, exist_ok=True)
    output_path = enriched_dir / f"{manifest.document_id}.enriched.md"

    header_fm = (
        f"---\n"
        f"document_id: {manifest.document_id}\n"
        f"source_file: {Path(manifest.source_path).name}\n"
        f"source_sha256: {manifest.source_sha256}\n"
        f"page_count: {manifest.page_count}\n"
        f"pipeline_version: {manifest.pipeline_version}\n"
        f"---\n"
    )
    header_body = (
        f"# {manifest.document_id}\n\n"
        "This document was generated from a native PDF by the PDF preprocessing pipeline.\n"
        "It contains:\n"
        "- Extracted text by page\n"
        "- Extracted tables\n"
        "- Visual summaries for selected pages\n"
        "- Page-level provenance\n"
    )

    page_sections = "\n\n".join(_page_section(p) for p in manifest.pages)
    full_doc = header_fm + header_body + "\n\n" + page_sections + "\n"
    output_path.write_text(full_doc, encoding="utf-8")
    return output_path
