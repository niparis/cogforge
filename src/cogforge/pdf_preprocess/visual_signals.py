"""Per-page visual signal computation."""
from __future__ import annotations

import re

import fitz  # PyMuPDF

from cogforge.pdf_preprocess.manifest import VisualSignals

_HINT_TERMS = [
    r"figure", r"fig\.", r"chart", r"graph", r"diagram", r"exhibit",
    r"table", r"architecture", r"workflow", r"screenshot",
    r"shown below", r"shown above", r"as shown",
    r"see below", r"see above", r"illustrates", r"depicts",
]
_HINT_PATTERN = re.compile("|".join(_HINT_TERMS), re.IGNORECASE)


def detect_visual_hints(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _HINT_PATTERN.finditer(text)})


def _bbox_area(bbox: tuple | list | None) -> float:
    if bbox is None:
        return 0.0
    try:
        w = max(0.0, bbox[2] - bbox[0])
        h = max(0.0, bbox[3] - bbox[1])
        return w * h
    except Exception:
        return 0.0


def _rect_area(rect) -> float:
    if rect is None:
        return 0.0
    try:
        return max(0.0, rect.width * rect.height)
    except Exception:
        return 0.0


def compute_visual_signals(page: fitz.Page, text: str, table_count: int) -> VisualSignals:
    page_width = page.rect.width
    page_height = page.rect.height
    page_area = max(page_width * page_height, 1.0)

    page_dict = page.get_text("dict")
    blocks = page_dict.get("blocks", [])

    text_blocks = 0
    text_area = 0.0
    image_blocks = 0
    image_area = 0.0

    for block in blocks:
        area = _bbox_area(block.get("bbox"))
        if block.get("type") == 0:
            text_blocks += 1
            text_area += area
        elif block.get("type") == 1:
            image_blocks += 1
            image_area += area

    image_xobjects = len(page.get_images(full=True))

    drawings = page.get_drawings()
    drawing_count = len(drawings)
    drawing_area = sum(_rect_area(d.get("rect")) for d in drawings)

    def _cap(v: float) -> float:
        return min(v / page_area, 1.0)

    text_area_ratio = _cap(text_area)
    image_area_ratio = _cap(image_area)
    drawing_area_ratio = _cap(drawing_area)
    visual_area_ratio = min(image_area_ratio + drawing_area_ratio, 1.0)

    hints = detect_visual_hints(text)

    return VisualSignals(
        page_width=page_width,
        page_height=page_height,
        page_area=page_area,
        text_blocks=text_blocks,
        image_blocks=image_blocks,
        image_xobjects=image_xobjects,
        drawing_count=drawing_count,
        table_count=table_count,
        text_area_ratio=text_area_ratio,
        image_area_ratio=image_area_ratio,
        drawing_area_ratio=drawing_area_ratio,
        visual_area_ratio=visual_area_ratio,
        has_visual_hint=bool(hints),
        visual_hints=hints,
    )
