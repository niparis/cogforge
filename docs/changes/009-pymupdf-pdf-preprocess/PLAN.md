Below is a v1 implementation spec for the simple pipeline from the conclusion:

Native PDF
  ↓
PyMuPDF page extraction
  ↓
Page classifier
  ├─ TEXT_ONLY → extracted text
  ├─ TABLE_PAGE → extracted text + Markdown/CSV tables
  ├─ VISUAL_PAGE → extracted text + VLM visual summary
  └─ LOW_TEXT_VISUAL_PAGE → VLM full-page summary
  ↓
Enriched Markdown builder
  ↓
PageIndex
  ↓
Karpathy-style KB compiler

This spec intentionally avoids region clustering, OCR, caption matching, logo detection, and complex layout repair. The goal is a robust v1, not a perfect document AI system.

⸻

Specification: PyMuPDF + VLM PDF Preprocessor for PageIndex

1. Goal

Build a preprocessing pipeline that converts a native PDF into a PageIndex-ready enriched Markdown document.

The enriched Markdown should contain:

1. Extracted page text.
2. Extracted tables in Markdown.
3. VLM summaries for visually important pages.
4. Page-level provenance.
5. A machine-readable manifest for debugging and downstream KB compilation.

The pipeline should make PageIndex more useful on complex PDFs by converting relevant visual and tabular content into structured text before indexing.

⸻

2. Non-goals for v1

The first version should not attempt to solve every PDF problem.

Explicit non-goals:

No OCR for scanned PDFs
No region-level visual cropping
No caption-to-figure association
No deduplication of logos/decorative images
No multi-column reconstruction beyond PyMuPDF sort=True
No human review UI
No diagram-to-Mermaid conversion
No direct Obsidian wiki generation
No full KB compiler yet

The v1 output is simply:

raw PDF → enriched Markdown + manifest → PageIndex input

⸻

3. Inputs and outputs

3.1 Input

A native PDF file:

raw/my-document.pdf

Assumption:

The PDF has selectable/native text.

The pipeline should detect low-text pages, but it does not need to perform OCR in v1.

⸻

3.2 Output directory structure

Given:

raw/my-document.pdf

The pipeline should create:

work/my-document/
  manifest.json
  summary.md
  pages/
    page-001.text.md
    page-002.text.md
    ...
  tables/
    page-005-table-001.csv
    page-005-table-001.md
    ...
  visuals/
    page-009.png
    page-009.visual.md
    ...
  enriched/
    my-document.enriched.md

Optional later:

indexes/pageindex/
  my-document.pageindex.json

For v1, PageIndex invocation can be a separate command.

⸻

4. CLI

Implement a CLI called:

pdf-preprocess

4.1 Main command

pdf-preprocess ingest raw/my-document.pdf --out work/my-document

This command should:

1. Open the PDF.
2. Extract page text.
3. Extract tables.
4. Classify pages.
5. Render pages needing VLM.
6. Call VLM for visual summaries.
7. Build enriched Markdown.
8. Write manifest and summary.

⸻

4.2 Useful options

pdf-preprocess ingest raw/my-document.pdf \
  --out work/my-document \
  --vlm-enabled true \
  --vlm-model gpt-4.1-mini \
  --render-zoom 2.0 \
  --max-vlm-pages 50

Required options:

pdf_path
--out

Optional options:

Option	Default	Description
--vlm-enabled	true	Whether to call the VLM
--vlm-model	configurable	Model used for visual summaries
--render-zoom	2.0	PyMuPDF render zoom
--max-vlm-pages	50	Hard cap on VLM pages
--force	false	Recompute existing artifacts
--config	none	Path to YAML config

⸻

5. Package structure

Suggested Python package:

pdf_preprocess/
  __init__.py
  cli.py
  config.py
  document.py
  extract_text.py
  extract_tables.py
  visual_signals.py
  classify.py
  render.py
  vlm.py
  markdown_builder.py
  manifest.py
  summary.py
  utils.py

5.1 Responsibilities

Module	Responsibility
cli.py	Command-line entrypoint
config.py	Defaults and config loading
document.py	Document metadata, hashing, output path handling
extract_text.py	Page text extraction
extract_tables.py	Table extraction to CSV/Markdown
visual_signals.py	Compute per-page visual metrics
classify.py	Assign page route
render.py	Render full-page PNGs for VLM
vlm.py	Call VLM and save visual Markdown
markdown_builder.py	Build final enriched Markdown
manifest.py	Build/write manifest.json
summary.py	Generate human-readable summary.md
utils.py	Shared helpers

⸻

6. Data model

Use dataclasses or Pydantic models. Pydantic is better if you want strict JSON serialization.

6.1 DocumentManifest

class DocumentManifest(BaseModel):
    document_id: str
    source_path: str
    source_sha256: str
    file_name: str
    page_count: int
    pipeline_version: str
    created_at: str
    config: dict
    pages: list[PageManifest]

⸻

6.2 PageManifest

class PageManifest(BaseModel):
    page_number: int
    route: str
    text_chars: int
    text_path: str | None = None
    visual_signals: VisualSignals
    tables: list[TableArtifact] = []
    visual_artifact: VisualArtifact | None = None
    errors: list[str] = []

⸻

6.3 VisualSignals

class VisualSignals(BaseModel):
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

⸻

6.4 TableArtifact

class TableArtifact(BaseModel):
    table_id: str
    page_number: int
    csv_path: str
    markdown_path: str
    rows: int
    columns: int
    extraction_status: str

Allowed extraction_status:

SUCCESS
EMPTY
FAILED
LOW_QUALITY

For v1, only SUCCESS and FAILED are required.

⸻

6.5 VisualArtifact

class VisualArtifact(BaseModel):
    page_number: int
    image_path: str
    visual_markdown_path: str | None
    vlm_model: str | None
    vlm_status: str
    reason: list[str]

Allowed vlm_status:

NOT_REQUIRED
SKIPPED_DISABLED
SKIPPED_LIMIT
SUCCESS
FAILED

⸻

7. Page routes

The classifier must assign one route per page.

Allowed routes:

TEXT_ONLY
TABLE_PAGE
VISUAL_PAGE
LOW_TEXT_VISUAL_PAGE

These four are enough for v1.

⸻

7.1 Route definitions

TEXT_ONLY

A page with enough extractable text and no strong table/visual signal.

Action:

Save extracted text.
Do not render.
Do not call VLM.

⸻

TABLE_PAGE

A page with one or more detected tables.

Action:

Save extracted text.
Extract table(s) to CSV and Markdown.
Do not call VLM unless the page also qualifies as LOW_TEXT_VISUAL_PAGE or VISUAL_PAGE.

For v1, tables take priority over text, but not over obvious visual pages.

⸻

VISUAL_PAGE

A page with enough visual signal to require VLM summary.

Action:

Save extracted text.
Extract tables if present.
Render full page to PNG.
Call VLM.
Save visual Markdown.

⸻

LOW_TEXT_VISUAL_PAGE

A page with little extractable text but significant visual content.

Action:

Save extracted text, even if short.
Render full page to PNG.
Call VLM.
Save visual Markdown.

This is the route most likely to catch slide-like pages, diagrams, dashboards, and pages where PyMuPDF text extraction alone is insufficient.

⸻

8. Visual signal extraction

Use PyMuPDF.

8.1 Required PyMuPDF calls

For each page:

page.get_text("text", sort=True)
page.get_text("dict")
page.get_images(full=True)
page.get_drawings()
page.find_tables()

⸻

8.2 Text extraction

Function:

def extract_page_text(page: fitz.Page) -> str:
    return page.get_text("text", sort=True).strip()

Write to:

work/my-document/pages/page-001.text.md

Format:

---
document_id: my-document
page: 1
artifact_type: extracted_text
---
# Page 1 — Extracted Text
...

⸻

8.3 Area calculation

From page.get_text("dict"), use block bounding boxes.

PyMuPDF block types:

type == 0 → text
type == 1 → image

Calculate:

page_area = page.width * page.height
text_area = sum(text block bbox areas)
image_area = sum(image block bbox areas)

For drawings:

drawings = page.get_drawings()
drawing_area = sum(d["rect"].area for d in drawings if d.get("rect"))

Acknowledge that drawing area is approximate and can overcount.

Cap ratios at 1.0.

⸻

8.4 Visual hint detection

Check extracted text for visual hint terms.

Regex terms:

figure
fig.
chart
graph
diagram
exhibit
table
architecture
workflow
screenshot
shown below
shown above
as shown
see below
see above
illustrates
depicts

Function:

def detect_visual_hints(text: str) -> list[str]:
    ...

Return all matching hint terms.

⸻

9. Classification rules

Use simple deterministic rules.

9.1 Constants

Default thresholds:

IMAGE_AREA_THRESHOLD = 0.08
DRAWING_AREA_THRESHOLD = 0.15
DRAWING_COUNT_THRESHOLD = 20
LOW_TEXT_CHARS = 500
LOW_TEXT_VISUAL_THRESHOLD = 0.20
VISUAL_HINT_MIN_AREA = 0.05

⸻

9.2 Classification order

Classification order matters.

Use this order:

1. LOW_TEXT_VISUAL_PAGE
2. VISUAL_PAGE
3. TABLE_PAGE
4. TEXT_ONLY

Reason:

A visual-heavy page with a table should still get VLM if visual signals are strong.
A table-only page should not automatically get VLM.

⸻

9.3 LOW_TEXT_VISUAL_PAGE rule

Assign LOW_TEXT_VISUAL_PAGE if:

text_chars < LOW_TEXT_CHARS
and visual_area_ratio >= LOW_TEXT_VISUAL_THRESHOLD

Default:

text_chars < 500
visual_area_ratio >= 0.20

⸻

9.4 VISUAL_PAGE rule

Assign VISUAL_PAGE if any of these is true:

image_area_ratio >= IMAGE_AREA_THRESHOLD
drawing_area_ratio >= DRAWING_AREA_THRESHOLD
drawing_count >= DRAWING_COUNT_THRESHOLD
has_visual_hint and visual_area_ratio >= VISUAL_HINT_MIN_AREA

Defaults:

image_area_ratio >= 0.08
drawing_area_ratio >= 0.15
drawing_count >= 20
visual hint + visual_area_ratio >= 0.05

⸻

9.5 TABLE_PAGE rule

Assign TABLE_PAGE if:

table_count > 0

Unless already classified as LOW_TEXT_VISUAL_PAGE or VISUAL_PAGE.

⸻

9.6 TEXT_ONLY rule

Fallback route.

route = "TEXT_ONLY"

⸻

10. Table extraction

10.1 Function

def extract_tables(page: fitz.Page, page_number: int, output_dir: Path) -> list[TableArtifact]:
    ...

Use:

tables = page.find_tables()

For each table:

1. Convert to pandas DataFrame if possible.
2. Save as CSV.
3. Save as Markdown.
4. Record row/column counts.

⸻

10.2 Table file names

tables/page-005-table-001.csv
tables/page-005-table-001.md

⸻

10.3 Markdown format

---
document_id: my-document
page: 5
artifact_type: table
table_id: page-005-table-001
---
# Table page-005-table-001
| Column A | Column B |
|---|---|
| ... | ... |

⸻

10.4 Table failure behavior

If table extraction fails:

1. Add error to PageManifest.errors.
2. Continue processing the page.
3. Do not fail the document.

For v1, do not send failed tables separately to VLM. If the page qualifies as visual, the full-page VLM summary may capture some of it.

⸻

11. Rendering for VLM

11.1 Rendering rule

Only render pages with route:

VISUAL_PAGE
LOW_TEXT_VISUAL_PAGE

Render full page only.

No region cropping in v1.

⸻

11.2 File path

visuals/page-009.png

⸻

11.3 Render function

def render_page(page: fitz.Page, output_path: Path, zoom: float = 2.0) -> Path:
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(output_path)
    return output_path

⸻

12. VLM processing

12.1 Function

def summarize_visual_page(
    image_path: Path,
    page_text: str,
    page_number: int,
    document_id: str,
    model: str,
) -> str:
    ...

Returns Markdown.

⸻

12.2 VLM context

Send the VLM:

document_id
page_number
page image
extracted page text
classification route
visual signals summary

Do not send the whole document.

⸻

12.3 VLM prompt

Use this prompt template:

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

⸻

12.4 Visual Markdown output

Save to:

visuals/page-009.visual.md

Format:

---
document_id: my-document
page: 9
artifact_type: visual_summary
source_image: visuals/page-009.png
vlm_model: gpt-4.1-mini
---
# Visual Summary — Page 9
## Visual type
...
## Short description
...
## Extracted visual facts
...
## Entities and labels
...
## Relationships
...
## Numeric values
...
## Relationship to extracted text
...
## Uncertainties
...

⸻

12.5 VLM failure behavior

If VLM call fails:

1. Save rendered image.
2. Create placeholder visual Markdown.
3. Mark vlm_status = FAILED.
4. Add error to manifest.
5. Continue document processing.

Placeholder:

---
document_id: my-document
page: 9
artifact_type: visual_summary
source_image: visuals/page-009.png
vlm_status: failed
---
# Visual Summary — Page 9
Visual content was detected on this page, but VLM processing failed.
The extracted page text is still included in the enriched document.

⸻

12.6 VLM cap

Respect:

max_vlm_pages

Default:

50

If cap is reached:

Do not call VLM for further pages.
Mark vlm_status = SKIPPED_LIMIT.
Still include extracted text and tables.

⸻

13. Enriched Markdown builder

The enriched Markdown is the main output for PageIndex.

Path:

work/my-document/enriched/my-document.enriched.md

⸻

13.1 Document-level header

---
document_id: my-document
source_file: raw/my-document.pdf
source_sha256: ...
page_count: 42
pipeline_version: pdf-preprocess-0.1
---
# my-document
This document was generated from a native PDF by the PDF preprocessing pipeline.
It contains:
- Extracted text by page
- Extracted tables
- Visual summaries for selected pages
- Page-level provenance

⸻

13.2 Page-level structure

For each page:

---
## Page {page_number}
### Page route
`TEXT_ONLY`
### Extracted text
...
### Extracted tables
...
### Visual summary
...
### Provenance
- Source file: `raw/my-document.pdf`
- Source page: `{page_number}`
- Text artifact: `pages/page-001.text.md`

⸻

13.3 TEXT_ONLY page format

---
## Page 1
### Page route
`TEXT_ONLY`
### Extracted text
{page_text}
### Provenance
- Source page: 1
- Text artifact: `pages/page-001.text.md`

⸻

13.4 TABLE_PAGE format

---
## Page 5
### Page route
`TABLE_PAGE`
### Extracted text
{page_text}
### Extracted tables
#### Table page-005-table-001
{markdown_table}
Source: page 5.
### Provenance
- Source page: 5
- Text artifact: `pages/page-005.text.md`
- Table artifact: `tables/page-005-table-001.md`
- Table CSV: `tables/page-005-table-001.csv`

⸻

13.5 VISUAL_PAGE format

---
## Page 9
### Page route
`VISUAL_PAGE`
### Extracted text
{page_text}
### Visual summary
{visual_markdown_body}
### Provenance
- Source page: 9
- Text artifact: `pages/page-009.text.md`
- Rendered page image: `visuals/page-009.png`
- Visual summary artifact: `visuals/page-009.visual.md`

⸻

13.6 LOW_TEXT_VISUAL_PAGE format

Same as VISUAL_PAGE, but route says:

`LOW_TEXT_VISUAL_PAGE`

Also include a warning:

Note: This page had low extractable text and significant visual content. The visual summary may carry most of the page meaning.

⸻

14. Manifest

Write:

work/my-document/manifest.json

The manifest should be complete enough to debug every page.

Example:

{
  "document_id": "my-document",
  "source_path": "raw/my-document.pdf",
  "source_sha256": "abc123",
  "file_name": "my-document.pdf",
  "page_count": 42,
  "pipeline_version": "pdf-preprocess-0.1",
  "created_at": "2026-05-15T20:00:00+08:00",
  "config": {
    "render_zoom": 2.0,
    "image_area_threshold": 0.08,
    "drawing_area_threshold": 0.15,
    "drawing_count_threshold": 20,
    "low_text_chars": 500,
    "low_text_visual_threshold": 0.2,
    "max_vlm_pages": 50
  },
  "pages": [
    {
      "page_number": 1,
      "route": "TEXT_ONLY",
      "text_chars": 2440,
      "text_path": "pages/page-001.text.md",
      "visual_signals": {
        "page_width": 595.0,
        "page_height": 842.0,
        "page_area": 500990.0,
        "text_blocks": 12,
        "image_blocks": 0,
        "image_xobjects": 0,
        "drawing_count": 2,
        "table_count": 0,
        "text_area_ratio": 0.42,
        "image_area_ratio": 0.0,
        "drawing_area_ratio": 0.01,
        "visual_area_ratio": 0.01,
        "has_visual_hint": false,
        "visual_hints": []
      },
      "tables": [],
      "visual_artifact": null,
      "errors": []
    }
  ]
}

⸻

15. Human-readable summary

Write:

work/my-document/summary.md

Example:

# Ingestion Summary — my-document.pdf
## Document
- Pages: 42
- Source SHA256: `abc123`
- Pipeline version: `pdf-preprocess-0.1`
## Page routing
| Route | Count |
|---|---:|
| TEXT_ONLY | 30 |
| TABLE_PAGE | 6 |
| VISUAL_PAGE | 4 |
| LOW_TEXT_VISUAL_PAGE | 2 |
## Tables
- Tables extracted: 9
- Table extraction failures: 1
## VLM
- Pages rendered: 6
- VLM successes: 5
- VLM failures: 1
- VLM skipped due to cap: 0
## Pages requiring attention
| Page | Reason |
|---:|---|
| 17 | VLM failed |
| 29 | Table extraction failed |

This is essential for trust and debugging.

⸻

16. Config file

Support a YAML config.

Example:

pipeline:
  version: pdf-preprocess-0.1
routing:
  image_area_threshold: 0.08
  drawing_area_threshold: 0.15
  drawing_count_threshold: 20
  low_text_chars: 500
  low_text_visual_threshold: 0.20
  visual_hint_min_area: 0.05
render:
  zoom: 2.0
vlm:
  enabled: true
  model: gpt-4.1-mini
  max_pages_per_document: 50
tables:
  enabled: true

CLI values should override config values.

⸻

17. Error handling requirements

The pipeline must be page-fault tolerant.

17.1 Document-level failure

Fail the whole pipeline only if:

PDF cannot be opened
output directory cannot be created
manifest cannot be written
enriched Markdown cannot be written

17.2 Page-level failure

Do not fail the whole document if:

text extraction fails on one page
table extraction fails on one page
rendering fails on one page
VLM fails on one page

Instead:

record error in manifest
add placeholder in enriched Markdown
continue

⸻

18. Caching

For v1, simple caching is enough.

If an artifact already exists and --force is false:

reuse page text
reuse rendered image
reuse VLM summary
reuse table outputs if present

For VLM, use a cache key later. In v1, path existence is acceptable.

Recommended future cache key:

sha256(image_bytes + prompt_version + model_name)

⸻

19. PageIndex integration

For v1, the preprocessor should not need to deeply integrate with PageIndex internals.

It should produce:

work/my-document/enriched/my-document.enriched.md

Then a separate command can load this into PageIndex.

Optional command:

pdf-preprocess pageindex work/my-document/enriched/my-document.enriched.md \
  --out indexes/pageindex/my-document

But this can be deferred.

Main contract:

The enriched Markdown file is the PageIndex input.

⸻

20. Acceptance criteria

20.1 Functional acceptance

Given a native PDF with 10 pages:

1. The tool creates manifest.json.
2. The tool creates summary.md.
3. The tool creates one .text.md file per page.
4. The tool creates one enriched Markdown file.
5. Pages with tables include Markdown tables in the enriched document.
6. Pages with visual signals are rendered to PNG.
7. Rendered pages receive VLM summaries if VLM is enabled.
8. The pipeline continues if VLM fails on one page.
9. The enriched Markdown preserves page boundaries.
10. The enriched Markdown can be passed to PageIndex as a text/Markdown document.

⸻

20.2 Classification acceptance

Use synthetic or known test PDFs.

Expected behavior:

Test document page	Expected route
Dense text-only page	TEXT_ONLY
Page with native table	TABLE_PAGE
Page with large embedded chart image	VISUAL_PAGE
Slide-like page with few words and diagram	LOW_TEXT_VISUAL_PAGE
Page with small logo only	likely TEXT_ONLY or TEXT_WITH_MINOR_VISUALS later; in v1 may be false positive

Since v1 only has four routes, some small-logo false positives are acceptable initially.

⸻

20.3 Output quality acceptance

The enriched Markdown should be readable by a human.

A page should look like:

## Page 12
### Page route
`TABLE_PAGE`
### Extracted text
...
### Extracted tables
...
### Provenance
...

No page should be a raw JSON dump.

⸻

21. Unit tests

21.1 visual_signals.py

Test:

area calculation
ratio capping
visual hint detection
empty page handling
drawings with missing rects

⸻

21.2 classify.py

Test classification rules:

def test_low_text_visual_page_takes_priority():
    ...
def test_visual_page_by_image_area():
    ...
def test_visual_page_by_drawing_count():
    ...
def test_table_page_if_tables_and_not_visual():
    ...
def test_text_only_fallback():
    ...

⸻

21.3 markdown_builder.py

Test:

includes document header
includes every page
includes table Markdown
includes visual summary
includes provenance
handles missing VLM summary
handles page errors

⸻

21.4 manifest.py

Test:

serializes valid JSON
contains page count
contains all page routes
records errors

⸻

22. Integration test

Create or select a small fixture PDF with:

Page 1: text only
Page 2: table
Page 3: large image/chart
Page 4: low-text diagram

Run:

pdf-preprocess ingest tests/fixtures/mixed.pdf --out tmp/mixed --vlm-enabled false

Expected:

manifest exists
summary exists
enriched markdown exists
page text files exist
table files exist
visual pages rendered or marked skipped depending on vlm flag

Then run with VLM mocked:

pdf-preprocess ingest tests/fixtures/mixed.pdf --out tmp/mixed --vlm-enabled true

Expected:

visual summaries are inserted from mock VLM response

⸻

23. Mock VLM mode

Implement mock mode for testing.

CLI:

pdf-preprocess ingest raw/my-document.pdf --out work/my-document --vlm-model mock

Mock output:

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

This makes the pipeline testable without API calls.

⸻

24. Logging

Log at document level and page level.

Example:

[INFO] Opening PDF raw/my-document.pdf
[INFO] Page count: 42
[INFO] Page 1 route=TEXT_ONLY text_chars=2440 tables=0 images=0 drawings=2
[INFO] Page 5 route=TABLE_PAGE text_chars=1100 tables=2
[INFO] Page 9 route=VISUAL_PAGE text_chars=650 image_area=0.22 drawings=14
[INFO] Rendering page 9 to visuals/page-009.png
[INFO] Calling VLM for page 9
[WARN] VLM failed for page 17: timeout
[INFO] Writing enriched Markdown
[INFO] Done

⸻

25. Minimal implementation sequence

Build in this exact order:

Milestone 1 — Text extraction and manifest

Deliver:

open PDF
extract text per page
compute basic page metadata
write page text files
write manifest
write summary

No tables, no VLM.

⸻

Milestone 2 — Visual signal and routing

Deliver:

image area
drawing count
drawing area
visual hints
table count
page route classification
summary by route

Still no VLM.

⸻

Milestone 3 — Table extraction

Deliver:

extract tables
write CSV
write Markdown
include tables in manifest
include tables in enriched Markdown

⸻

Milestone 4 — Rendering and mock VLM

Deliver:

render VISUAL_PAGE and LOW_TEXT_VISUAL_PAGE
mock VLM summary
save visual markdown
include visual summary in enriched Markdown

⸻

Milestone 5 — Real VLM

Deliver:

real VLM integration
VLM failure handling
max_vlm_pages cap
summary stats

⸻

Milestone 6 — PageIndex handoff

Deliver:

final enriched Markdown accepted by PageIndex
optional command or documented call

⸻

26. The core algorithm

In pseudocode:

def ingest_pdf(pdf_path: Path, out_dir: Path, config: Config) -> DocumentManifest:
    doc_meta = register_document(pdf_path, out_dir, config)
    pdf = fitz.open(pdf_path)
    pages = []
    vlm_pages_used = 0
    for index, page in enumerate(pdf):
        page_number = index + 1
        page_errors = []
        text = safe_extract_text(page, page_errors)
        text_path = write_page_text(out_dir, doc_meta.document_id, page_number, text)
        table_artifacts = []
        if config.tables.enabled:
            table_artifacts = safe_extract_tables(page, page_number, out_dir, page_errors)
        signals = compute_visual_signals(page, text, table_artifacts)
        route = classify_page(text, signals, config.routing)
        visual_artifact = None
        if route in ["VISUAL_PAGE", "LOW_TEXT_VISUAL_PAGE"]:
            image_path = render_page(page, out_dir / "visuals" / f"page-{page_number:03d}.png")
            if not config.vlm.enabled:
                visual_artifact = VisualArtifact(
                    page_number=page_number,
                    image_path=str(image_path),
                    visual_markdown_path=None,
                    vlm_model=None,
                    vlm_status="SKIPPED_DISABLED",
                    reason=classification_reasons(signals, route),
                )
            elif vlm_pages_used >= config.vlm.max_pages_per_document:
                visual_artifact = VisualArtifact(
                    page_number=page_number,
                    image_path=str(image_path),
                    visual_markdown_path=None,
                    vlm_model=config.vlm.model,
                    vlm_status="SKIPPED_LIMIT",
                    reason=classification_reasons(signals, route),
                )
            else:
                visual_md_path, status = call_and_save_vlm_summary(
                    image_path=image_path,
                    page_text=text,
                    page_number=page_number,
                    document_id=doc_meta.document_id,
                    model=config.vlm.model,
                )
                vlm_pages_used += 1
                visual_artifact = VisualArtifact(
                    page_number=page_number,
                    image_path=str(image_path),
                    visual_markdown_path=str(visual_md_path),
                    vlm_model=config.vlm.model,
                    vlm_status=status,
                    reason=classification_reasons(signals, route),
                )
        page_manifest = PageManifest(
            page_number=page_number,
            route=route,
            text_chars=len(text),
            text_path=str(text_path),
            visual_signals=signals,
            tables=table_artifacts,
            visual_artifact=visual_artifact,
            errors=page_errors,
        )
        pages.append(page_manifest)
    manifest = DocumentManifest(
        document_id=doc_meta.document_id,
        source_path=str(pdf_path),
        source_sha256=doc_meta.source_sha256,
        file_name=pdf_path.name,
        page_count=len(pdf),
        pipeline_version=config.pipeline.version,
        created_at=now_iso(),
        config=config.model_dump(),
        pages=pages,
    )
    write_manifest(out_dir, manifest)
    build_enriched_markdown(out_dir, manifest)
    write_summary(out_dir, manifest)
    return manifest

⸻

27. PageIndex-ready contract

The output file:

work/my-document/enriched/my-document.enriched.md

must satisfy:

1. It is valid Markdown.
2. It has explicit page headings.
3. It includes extracted text.
4. It includes tables as Markdown tables.
5. It includes VLM summaries as Markdown.
6. It includes source page provenance.
7. It does not require images to be loaded by PageIndex.

This is the core contract.

PageIndex does not need to understand images. The VLM summaries convert the useful image content into text before PageIndex sees the document.

⸻

28. Recommended defaults

Use these defaults for v1:

routing:
  image_area_threshold: 0.08
  drawing_area_threshold: 0.15
  drawing_count_threshold: 20
  low_text_chars: 500
  low_text_visual_threshold: 0.20
  visual_hint_min_area: 0.05
render:
  zoom: 2.0
vlm:
  enabled: true
  model: gpt-4.1-mini
  max_pages_per_document: 50
tables:
  enabled: true

For early testing, run with:

--vlm-model mock

Then inspect the routing.

⸻

29. Practical first test

Use three PDFs:

1. mostly text PDF
2. annual report / financial PDF with tables and charts
3. slide-like PDF with diagrams

For each, compare:

A. raw PDF into PageIndex
B. enriched Markdown into PageIndex

Ask:

What does the document say?
What are the important tables?
What do the visual pages explain?
What diagrams or charts are important?
What claims should be added to the KB?

Expected result:

Text PDF: small improvement
Financial/report PDF: meaningful improvement
Diagram-heavy PDF: large improvement

⸻

30. Summary

The implementation should stay simple:

Extract text from every page.
Extract tables when PyMuPDF detects them.
Classify pages using image/drawing/text signals.
Render only visual-heavy pages.
Ask VLM for Markdown summaries.
Build one enriched Markdown document.
Send that enriched Markdown to PageIndex.

That gives you a clean v1 with the right separation of concerns:

PyMuPDF = extraction and routing
VLM = visual interpretation
Markdown builder = text normalization
PageIndex = long-document navigation
KB compiler = durable knowledge synthesis