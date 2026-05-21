"""VLM integration: DeepSeek vision via OpenAI-compatible API."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cogforge.pdf_preprocess.manifest import VisualSignals

from cogforge.pdf_preprocess.manifest import VisualArtifact

MOCK_RESPONSE = """\
## Visual type
Mock visual summary.
## Short description
This is a mocked VLM response for testing.
## Extracted visual facts
- Mock fact.
## Entities and labels
- Mock entity.
## Relationships
None.
## Numeric values
None reliably extractable.
## Relationship to extracted text
Mock relationship.
## Uncertainties
None.
"""

_PROMPT_TEMPLATE = """\
You are analyzing a page from a native PDF for knowledge-base ingestion.
Document: {document_id}
Page: {page_number}
The page has been flagged as visually important.
Use the image as the source of truth for visual content.
Use the extracted text only as context.
Do not invent facts, numbers, labels, or relationships that are not visible.
If something is unclear, say so.
Return Markdown with these sections:
## Visual type
Choose one or more: chart, diagram, table, screenshot, photo, map, slide, mixed, unknown.
## Short description
Briefly describe what the visual content shows.
## Extracted visual facts
Bullet list of concrete facts visible on the page.
## Entities and labels
List visible named entities, labels, systems, axes, legends, categories, or components.
## Relationships
Describe visible arrows, flows, hierarchy, grouping, comparisons, dependencies, or spatial relationships.
## Numeric values
Extract numbers only if clearly readable. Preserve units. If no reliable numbers are visible, write "None reliably extractable."
## Relationship to extracted text
Explain how the visual content appears to support, extend, or clarify the extracted text.
## Uncertainties
List anything ambiguous, unreadable, cropped, or low-confidence.
"""

_VISUAL_MD_HEADER = """\
---
document_id: {document_id}
page: {page_number}
artifact_type: visual_summary
source_image: {image_path}
vlm_model: {vlm_model}
---
# Visual Summary — Page {page_number}

"""

_FAILED_MD_TEMPLATE = """\
---
document_id: {document_id}
page: {page_number}
artifact_type: visual_summary
source_image: {image_path}
vlm_status: failed
---
# Visual Summary — Page {page_number}

Visual content was detected on this page, but VLM processing failed.
The extracted page text is still included in the enriched document.
"""


def _call_vlm_api(
    image_path: Path,
    page_text: str,
    page_number: int,
    document_id: str,
    model: str,
    api_key_env: str,
    base_url: str,
) -> str:
    from openai import OpenAI  # lazy import — mock mode needs no API key

    with image_path.open("rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    client = OpenAI(api_key=os.environ[api_key_env], base_url=base_url)
    prompt = _PROMPT_TEMPLATE.format(document_id=document_id, page_number=page_number)
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt + f"\n\nExtracted page text:\n{page_text}"},
            ],
        }],
    )
    return response.choices[0].message.content or ""


def process_visual_page(
    image_path: Path,
    page_text: str,
    page_number: int,
    document_id: str,
    visuals_dir: Path,
    config,  # VLMConfig — avoid circular import at module level
    vlm_pages_used: int,
    signals: "VisualSignals",
    route: str,
) -> tuple[VisualArtifact, int]:
    """Produce a VisualArtifact for a rendered page. Returns (artifact, updated_count)."""
    from cogforge.pdf_preprocess.classify import classification_reasons

    reason = classification_reasons(signals, route)
    visual_md_path = visuals_dir / f"page-{page_number:03d}.visual.md"

    if not config.enabled:
        return VisualArtifact(
            page_number=page_number,
            image_path=str(image_path),
            visual_markdown_path=None,
            vlm_model=None,
            vlm_status="SKIPPED_DISABLED",
            reason=reason,
        ), vlm_pages_used

    if vlm_pages_used >= config.max_pages_per_document:
        return VisualArtifact(
            page_number=page_number,
            image_path=str(image_path),
            visual_markdown_path=None,
            vlm_model=config.model,
            vlm_status="SKIPPED_LIMIT",
            reason=reason,
        ), vlm_pages_used

    try:
        if config.model == "mock":
            md_body = MOCK_RESPONSE
        else:
            md_body = _call_vlm_api(
                image_path=image_path,
                page_text=page_text,
                page_number=page_number,
                document_id=document_id,
                model=config.model,
                api_key_env=config.api_key_env,
                base_url=config.base_url,
            )

        header = _VISUAL_MD_HEADER.format(
            document_id=document_id,
            page_number=page_number,
            image_path=str(image_path),
            vlm_model=config.model,
        )
        visual_md_path.write_text(header + md_body, encoding="utf-8")

        return VisualArtifact(
            page_number=page_number,
            image_path=str(image_path),
            visual_markdown_path=str(visual_md_path),
            vlm_model=config.model,
            vlm_status="SUCCESS",
            reason=reason,
        ), vlm_pages_used + 1

    except Exception as e:
        failed_md = _FAILED_MD_TEMPLATE.format(
            document_id=document_id,
            page_number=page_number,
            image_path=str(image_path),
        )
        visual_md_path.write_text(failed_md, encoding="utf-8")
        return VisualArtifact(
            page_number=page_number,
            image_path=str(image_path),
            visual_markdown_path=str(visual_md_path),
            vlm_model=config.model,
            vlm_status="FAILED",
            reason=reason + [str(e)],
        ), vlm_pages_used
