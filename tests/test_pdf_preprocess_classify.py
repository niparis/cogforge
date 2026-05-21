"""Unit tests for classify.py."""
import pytest

from cogforge.pdf_preprocess.classify import classify_page, classification_reasons
from cogforge.pdf_preprocess.config import RoutingConfig
from cogforge.pdf_preprocess.manifest import VisualSignals


def _signals(**kwargs) -> VisualSignals:
    defaults = dict(
        page_width=595.0,
        page_height=842.0,
        page_area=500990.0,
        text_blocks=10,
        image_blocks=0,
        image_xobjects=0,
        drawing_count=0,
        table_count=0,
        text_area_ratio=0.4,
        image_area_ratio=0.0,
        drawing_area_ratio=0.0,
        visual_area_ratio=0.0,
        has_visual_hint=False,
        visual_hints=[],
    )
    defaults.update(kwargs)
    return VisualSignals(**defaults)


routing = RoutingConfig()


def test_text_only_fallback():
    sig = _signals()
    assert classify_page("some text " * 100, sig, routing) == "TEXT_ONLY"


def test_low_text_visual_page_takes_priority():
    sig = _signals(visual_area_ratio=0.5, image_area_ratio=0.5)
    # low text + high visual → LOW_TEXT_VISUAL_PAGE even if it would be VISUAL_PAGE
    assert classify_page("a" * 100, sig, routing) == "LOW_TEXT_VISUAL_PAGE"


def test_visual_page_by_image_area():
    sig = _signals(image_area_ratio=0.1, visual_area_ratio=0.1)
    assert classify_page("lots of text " * 200, sig, routing) == "VISUAL_PAGE"


def test_visual_page_by_drawing_area():
    sig = _signals(drawing_area_ratio=0.2, visual_area_ratio=0.2)
    assert classify_page("lots of text " * 200, sig, routing) == "VISUAL_PAGE"


def test_visual_page_by_drawing_count():
    sig = _signals(drawing_count=25, visual_area_ratio=0.1)
    assert classify_page("lots of text " * 200, sig, routing) == "VISUAL_PAGE"


def test_visual_page_by_hint_and_area():
    sig = _signals(has_visual_hint=True, visual_hints=["chart"], visual_area_ratio=0.1)
    assert classify_page("lots of text " * 200, sig, routing) == "VISUAL_PAGE"


def test_visual_hint_without_area_is_not_visual():
    sig = _signals(has_visual_hint=True, visual_hints=["chart"], visual_area_ratio=0.01)
    # visual_area_ratio below visual_hint_min_area (0.05) → not visual
    result = classify_page("lots of text " * 200, sig, routing)
    assert result == "TEXT_ONLY"


def test_table_page_if_tables_and_not_visual():
    sig = _signals(table_count=2)
    assert classify_page("lots of text " * 200, sig, routing) == "TABLE_PAGE"


def test_table_page_not_assigned_when_visual():
    sig = _signals(table_count=2, image_area_ratio=0.2, visual_area_ratio=0.2)
    assert classify_page("lots of text " * 200, sig, routing) == "VISUAL_PAGE"


def test_classification_reasons_low_text_visual():
    sig = _signals(visual_area_ratio=0.5)
    reasons = classification_reasons(sig, "LOW_TEXT_VISUAL_PAGE")
    assert any("low_text" in r for r in reasons)


def test_classification_reasons_table():
    sig = _signals(table_count=3)
    reasons = classification_reasons(sig, "TABLE_PAGE")
    assert any("table_count" in r for r in reasons)


# ── Facsimile detection (scanned PDF with OCR text layer) ───────────────────

def _facsimile_signals(**overrides):
    """Signals matching a typical JSTOR/SSRN scanned page: one full-page image,
    no drawings, and an OCR text layer underneath."""
    defaults = dict(
        image_blocks=1,
        image_xobjects=1,
        image_area_ratio=1.0,
        visual_area_ratio=1.0,
        drawing_count=0,
        drawing_area_ratio=0.0,
    )
    defaults.update(overrides)
    return _signals(**defaults)


def test_facsimile_with_rich_text_routes_text_only():
    """A full-page scanned image + plenty of OCR'd text → TEXT_ONLY (don't VLM)."""
    sig = _facsimile_signals()
    text = "x" * 3000  # well above low_text_chars (500)
    assert classify_page(text, sig, routing) == "TEXT_ONLY"


def test_facsimile_with_tables_routes_table_page():
    """Same signature but with tables found — preserve table extraction."""
    sig = _facsimile_signals(table_count=2)
    text = "x" * 3000
    assert classify_page(text, sig, routing) == "TABLE_PAGE"


def test_facsimile_classification_reasons_marked():
    """TEXT_ONLY/TABLE_PAGE reasons must call out facsimile so manifests stay debuggable."""
    sig = _facsimile_signals()
    reasons = classification_reasons(sig, "TEXT_ONLY")
    assert any("facsimile" in r for r in reasons)

    sig_tbl = _facsimile_signals(table_count=2)
    reasons_tbl = classification_reasons(sig_tbl, "TABLE_PAGE")
    assert any("facsimile" in r for r in reasons_tbl)


def test_facsimile_with_low_text_still_routes_low_text_visual():
    """A scanned page with sparse OCR (badly scanned, broken text layer) genuinely
    needs the VLM — facsimile rule must NOT shadow LOW_TEXT_VISUAL_PAGE."""
    sig = _facsimile_signals()
    text = "x" * 100  # below low_text_chars
    assert classify_page(text, sig, routing) == "LOW_TEXT_VISUAL_PAGE"


def test_facsimile_with_extra_images_routes_visual_page():
    """Multiple image XObjects = embedded figures, not a single page facsimile.
    Keep routing through VLM."""
    sig = _facsimile_signals(image_xobjects=6)  # 6 distinct images on the page
    text = "x" * 3000
    assert classify_page(text, sig, routing) == "VISUAL_PAGE"


def test_facsimile_with_drawings_routes_visual_page():
    """A page that has both a full-page image AND substantial vector drawings is
    unusual (e.g. annotation overlay). Route VISUAL_PAGE to be safe."""
    sig = _facsimile_signals(drawing_area_ratio=0.2, drawing_count=5)
    text = "x" * 3000
    assert classify_page(text, sig, routing) == "VISUAL_PAGE"


def test_facsimile_disabled_via_routing_config():
    """Setting facsimile_image_area_min above 1.0 disables the heuristic."""
    from cogforge.pdf_preprocess.config import RoutingConfig
    routing_no_facsimile = RoutingConfig(facsimile_image_area_min=1.5)
    sig = _facsimile_signals()
    text = "x" * 3000
    # Without facsimile detection, full-page image would route VISUAL_PAGE as before
    assert classify_page(text, sig, routing_no_facsimile) == "VISUAL_PAGE"
