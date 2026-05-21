"""Configuration dataclasses for the PDF preprocessing pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutingConfig:
    image_area_threshold: float = 0.08
    drawing_area_threshold: float = 0.15
    drawing_count_threshold: int = 20
    low_text_chars: int = 500
    low_text_visual_threshold: float = 0.20
    visual_hint_min_area: float = 0.05
    # Facsimile detection: a single page-sized image overlaid with extracted text is the
    # signature of a scanned PDF with an OCR text layer (JSTOR/SSRN/old proceedings).
    # In that case the "image" is a picture of the text we already have — sending it
    # through a VLM gets us a paraphrase, not new information. Route as TEXT_ONLY
    # (or TABLE_PAGE if tables were found) instead.
    facsimile_image_area_min: float = 0.95
    facsimile_max_image_xobjects: int = 1


@dataclass
class VLMConfig:
    enabled: bool = True
    model: str = "deepseek-vl2"  # "mock" for tests
    max_pages_per_document: int = 50
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com"


@dataclass
class PDFPreprocessConfig:
    pipeline_version: str = "pdf-preprocess-0.1"
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    vlm: VLMConfig = field(default_factory=VLMConfig)
    render_zoom: float = 2.0
    tables_enabled: bool = True
    force: bool = False

    def to_dict(self) -> dict:
        return {
            "pipeline_version": self.pipeline_version,
            "render_zoom": self.render_zoom,
            "tables_enabled": self.tables_enabled,
            "routing": {
                "image_area_threshold": self.routing.image_area_threshold,
                "drawing_area_threshold": self.routing.drawing_area_threshold,
                "drawing_count_threshold": self.routing.drawing_count_threshold,
                "low_text_chars": self.routing.low_text_chars,
                "low_text_visual_threshold": self.routing.low_text_visual_threshold,
                "visual_hint_min_area": self.routing.visual_hint_min_area,
                "facsimile_image_area_min": self.routing.facsimile_image_area_min,
                "facsimile_max_image_xobjects": self.routing.facsimile_max_image_xobjects,
            },
            "vlm": {
                "enabled": self.vlm.enabled,
                "model": self.vlm.model,
                "max_pages_per_document": self.vlm.max_pages_per_document,
            },
        }
