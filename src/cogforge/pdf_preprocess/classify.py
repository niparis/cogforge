"""Page route classification."""
from __future__ import annotations

from cogforge.pdf_preprocess.config import RoutingConfig
from cogforge.pdf_preprocess.manifest import VisualSignals

ROUTES = ("TEXT_ONLY", "TABLE_PAGE", "VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE")


def is_facsimile_page(text_chars: int, signals: VisualSignals, routing: RoutingConfig) -> bool:
    """Detect a 'scanned page with OCR text layer' — a single full-page image
    sitting under extracted text. Treating it as VISUAL_PAGE wastes VLM calls on
    a picture of text we already have.

    A page qualifies when ALL of:
      - image_xobjects ≤ facsimile_max_image_xobjects (default 1)
      - image_area_ratio ≥ facsimile_image_area_min (default 0.95)
      - text_chars ≥ low_text_chars (the text layer is rich enough that we don't need vision)
      - drawing_area_ratio and drawing_count are below the VISUAL_PAGE thresholds
        (a page with both a full-page scan AND substantial vector content is unusual
        and worth routing through the VLM to be safe)
    """
    return (
        signals.image_xobjects <= routing.facsimile_max_image_xobjects
        and signals.image_area_ratio >= routing.facsimile_image_area_min
        and text_chars >= routing.low_text_chars
        and signals.drawing_area_ratio < routing.drawing_area_threshold
        and signals.drawing_count < routing.drawing_count_threshold
    )


def classify_page(text: str, signals: VisualSignals, routing: RoutingConfig) -> str:
    text_chars = len(text)

    # Priority 1: LOW_TEXT_VISUAL_PAGE — sparse text + visible imagery → needs VLM
    if (
        text_chars < routing.low_text_chars
        and signals.visual_area_ratio >= routing.low_text_visual_threshold
    ):
        return "LOW_TEXT_VISUAL_PAGE"

    # Priority 2: FACSIMILE → scanned PDF with OCR text layer. Route as TABLE_PAGE
    # when tables were found (so they still get extracted), otherwise TEXT_ONLY.
    # This MUST come before the VISUAL_PAGE check, since a facsimile trivially
    # blows past image_area_threshold.
    if is_facsimile_page(text_chars, signals, routing):
        return "TABLE_PAGE" if signals.table_count > 0 else "TEXT_ONLY"

    # Priority 3: VISUAL_PAGE
    if (
        signals.image_area_ratio >= routing.image_area_threshold
        or signals.drawing_area_ratio >= routing.drawing_area_threshold
        or signals.drawing_count >= routing.drawing_count_threshold
        or (signals.has_visual_hint and signals.visual_area_ratio >= routing.visual_hint_min_area)
    ):
        return "VISUAL_PAGE"

    # Priority 4: TABLE_PAGE
    if signals.table_count > 0:
        return "TABLE_PAGE"

    return "TEXT_ONLY"


def classification_reasons(signals: VisualSignals, route: str) -> list[str]:
    reasons: list[str] = []
    if route == "LOW_TEXT_VISUAL_PAGE":
        reasons.append(f"low_text, visual_area_ratio={signals.visual_area_ratio:.2f}")
    elif route == "VISUAL_PAGE":
        if signals.image_area_ratio >= 0.08:
            reasons.append(f"image_area_ratio={signals.image_area_ratio:.2f}")
        if signals.drawing_area_ratio >= 0.15:
            reasons.append(f"drawing_area_ratio={signals.drawing_area_ratio:.2f}")
        if signals.drawing_count >= 20:
            reasons.append(f"drawing_count={signals.drawing_count}")
        if signals.has_visual_hint:
            reasons.append(f"visual_hints={signals.visual_hints}")
    elif route == "TABLE_PAGE":
        reasons.append(f"table_count={signals.table_count}")
        # If this page would have been VISUAL_PAGE but we detected a facsimile, say so
        # to make the manifest self-explaining.
        if signals.image_xobjects <= 1 and signals.image_area_ratio >= 0.95:
            reasons.append(f"facsimile_detected (image_area_ratio={signals.image_area_ratio:.2f}, image_xobjects={signals.image_xobjects})")
    elif route == "TEXT_ONLY":
        # Same here — distinguishes "no visuals" from "scanned facsimile we deliberately
        # ignored". Useful when reviewing a manifest of a paper that's all scans.
        if signals.image_xobjects <= 1 and signals.image_area_ratio >= 0.95:
            reasons.append(f"facsimile_detected (image_area_ratio={signals.image_area_ratio:.2f}, image_xobjects={signals.image_xobjects})")
    return reasons
