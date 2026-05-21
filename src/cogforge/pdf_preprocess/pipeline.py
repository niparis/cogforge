"""Main pipeline orchestration: ingest_pdf()."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
from loguru import logger

from cogforge.pdf_preprocess.classify import classify_page
from cogforge.pdf_preprocess.config import PDFPreprocessConfig
from cogforge.pdf_preprocess.document import register_document
from cogforge.pdf_preprocess.extract_tables import extract_tables
from cogforge.pdf_preprocess.extract_text import extract_page_text, write_page_text
from cogforge.pdf_preprocess.manifest import (
    DocumentManifest,
    PageManifest,
    VisualSignals,
    now_iso,
    write_manifest,
)
from cogforge.pdf_preprocess.markdown_builder import build_enriched_markdown
from cogforge.pdf_preprocess.render import render_page
from cogforge.pdf_preprocess.summary import write_summary
from cogforge.pdf_preprocess.visual_signals import compute_visual_signals
from cogforge.pdf_preprocess.vlm import process_visual_page

_EMPTY_SIGNALS = VisualSignals(
    page_width=0, page_height=0, page_area=1,
    text_blocks=0, image_blocks=0, image_xobjects=0,
    drawing_count=0, table_count=0,
    text_area_ratio=0.0, image_area_ratio=0.0,
    drawing_area_ratio=0.0, visual_area_ratio=0.0,
    has_visual_hint=False, visual_hints=[],
)


def ingest_pdf(
    pdf_path: Path,
    out_dir: Path,
    config: PDFPreprocessConfig | None = None,
) -> DocumentManifest:
    """Convert a native PDF to enriched Markdown and write all artifacts.

    Fails only if the PDF cannot be opened or the output directory cannot be
    created. All per-page failures are recorded in the manifest and processing
    continues.
    """
    if config is None:
        config = PDFPreprocessConfig()

    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Opening PDF {pdf_path}")
    pdf = fitz.open(str(pdf_path))
    doc_meta = register_document(pdf_path, out_dir)
    logger.info(f"Page count: {len(pdf)}")

    pages: list[PageManifest] = []
    vlm_pages_used = 0

    for idx in range(len(pdf)):
        page = pdf[idx]
        page_number = idx + 1
        page_errors: list[str] = []

        # --- Text extraction ---
        try:
            text = extract_page_text(page)
        except Exception as e:
            logger.warning(f"Page {page_number} text extraction failed: {e}")
            page_errors.append(f"Text extraction failed: {e}")
            text = ""

        text_path: str | None = None
        cached_text = doc_meta.pages_dir / f"page-{page_number:03d}.text.md"
        if not config.force and cached_text.exists():
            text_path = str(cached_text)
        else:
            try:
                tp = write_page_text(doc_meta.document_id, page_number, text, doc_meta.pages_dir)
                text_path = str(tp)
            except Exception as e:
                logger.warning(f"Page {page_number} write_page_text failed: {e}")
                page_errors.append(f"Write page text failed: {e}")

        # --- Table extraction ---
        table_artifacts = []
        if config.tables_enabled:
            try:
                table_artifacts, table_errors = extract_tables(
                    page, page_number, doc_meta.document_id, doc_meta.tables_dir
                )
                page_errors.extend(table_errors)
            except Exception as e:
                logger.warning(f"Page {page_number} table extraction failed: {e}")
                page_errors.append(f"Table extraction failed: {e}")

        # --- Visual signals ---
        try:
            signals = compute_visual_signals(page, text, len(table_artifacts))
        except Exception as e:
            logger.warning(f"Page {page_number} visual signals failed: {e}")
            page_errors.append(f"Visual signals failed: {e}")
            signals = _EMPTY_SIGNALS

        # --- Classification ---
        route = classify_page(text, signals, config.routing)

        logger.info(
            f"Page {page_number} route={route} text_chars={len(text)} "
            f"tables={len(table_artifacts)} images={signals.image_blocks} "
            f"drawings={signals.drawing_count}"
        )

        # --- Render + VLM ---
        visual_artifact = None
        if route in ("VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE"):
            image_path = doc_meta.visuals_dir / f"page-{page_number:03d}.png"
            rendered = False

            if not config.force and image_path.exists():
                rendered = True
            else:
                try:
                    logger.info(f"Rendering page {page_number} to {image_path}")
                    render_page(page, image_path, config.render_zoom)
                    rendered = True
                except Exception as e:
                    logger.warning(f"Page {page_number} render failed: {e}")
                    page_errors.append(f"Render failed: {e}")

            if rendered:
                try:
                    logger.info(f"Calling VLM for page {page_number}")
                    visual_artifact, vlm_pages_used = process_visual_page(
                        image_path=image_path,
                        page_text=text,
                        page_number=page_number,
                        document_id=doc_meta.document_id,
                        visuals_dir=doc_meta.visuals_dir,
                        config=config.vlm,
                        vlm_pages_used=vlm_pages_used,
                        signals=signals,
                        route=route,
                    )
                    if visual_artifact.vlm_status == "FAILED":
                        logger.warning(f"VLM failed for page {page_number}")
                    elif visual_artifact.vlm_status in ("SKIPPED_DISABLED", "SKIPPED_LIMIT"):
                        logger.info(f"VLM skipped for page {page_number}: {visual_artifact.vlm_status}")
                except Exception as e:
                    logger.warning(f"Page {page_number} VLM processing failed: {e}")
                    page_errors.append(f"VLM processing failed: {e}")

        pages.append(PageManifest(
            page_number=page_number,
            route=route,
            text_chars=len(text),
            text_path=text_path,
            visual_signals=signals,
            tables=table_artifacts,
            visual_artifact=visual_artifact,
            errors=page_errors,
        ))

    pdf.close()

    manifest = DocumentManifest(
        document_id=doc_meta.document_id,
        source_path=str(pdf_path),
        source_sha256=doc_meta.source_sha256,
        file_name=pdf_path.name,
        page_count=len(pages),
        pipeline_version=config.pipeline_version,
        created_at=now_iso(),
        config=config.to_dict(),
        pages=pages,
    )

    logger.info("Writing enriched Markdown")
    build_enriched_markdown(out_dir, manifest)
    write_manifest(out_dir, manifest)
    write_summary(out_dir, manifest)
    logger.info("Done")

    return manifest
