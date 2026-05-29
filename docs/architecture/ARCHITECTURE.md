# cogforge Technical Architecture Specification

## Architecture Goal

`cogforge` is a three-layer system that combines a deterministic CLI engine (v1), a conversational interface (v1.5), and a full knowledge workbench (v2). The architecture must support all three tiers without requiring rewrites between tiers.

The first deliverable is a CLI engine that exposes stable commands and schemas for source synchronization, long-document preparation, state tracking, reporting, and agent skill management. This engine must be architected so that its core capabilities can be extracted into a shared library consumed by both the CLI and future interfaces.

## System Architecture

Cogforge is organized into three logical layers. See [ADR-001](adr-001-layered-architecture.md).

```
Knowledge Layer        (concepts, sources, wiki content, relationships, decisions)
        ↓
Observability Layer    (runs, reports, logs, events, state, provenance)
        ↓
Interaction Layer      (CLI, conversational interface, dashboard, API)
```

The conversational interface sits at the Interaction Layer and must have access to both Knowledge and Observability data. This enables users to ask knowledge questions, provenance questions, operational questions, and governance questions through the same interface.

Layers are logical in v1 (enforced through module boundaries within a single package) and become physically separate as complexity warrants.

### Service Boundaries

Three service families emerge from the layered architecture:

**Knowledge Access** — concepts, wiki content, source metadata, concept relationships, decisions.

**Observability** — run reports, processing logs, state transitions, events, source preparation metadata (PageIndex artifacts, enrichment manifests).

**Governance** — cases, decisions, reviews, contradiction tracking.

The conversational system and dashboard are consumers of all three service families.

## Conversational Architecture

### Chat as Orchestrator

The chat system is not a simple RAG endpoint. It is an orchestrator with access to multiple tool domains:

- Concept search and concept relationship traversal.
- Source search and source metadata inspection.
- PageIndex document tree navigation.
- Run and report inspection.
- Case and decision inspection and update.
- Knowledge graph exploration.

The conversational agent must be capable of switching between these domains dynamically within a single session. It must also produce durable artifacts: decisions, case updates, concept updates, and processing actions are persisted as structured records, not transient chat messages.

### Query Model

Internally, user questions are classified into four categories matching the product's query types:

- **Knowledge** — "What is PageIndex?"
- **Meta-Knowledge** — "What documents were added this week?"
- **Provenance** — "Why was this source not used in the answer?"
- **Governance** — "Should these contradictory claims be reconciled?"

The backend exposes APIs that support all four categories. The conversational agent selects tools and strategies based on query classification.

### Knowledge Provenance

Every answer produced by the conversational system must maintain references to:

- Concepts used.
- Source documents consulted.
- Decisions that influenced the reasoning.
- Contradictions encountered during generation.

This enables conversational provenance inspection — users can drill into answers interactively to understand the reasoning path.

## Event Architecture

Cogforge uses structured events in two domains. See [ADR-002](adr-002-event-architecture.md).

**Operational events** describe CLI activity: `sync_started`, `sync_completed`, `pageindex_failed`, `source_marked_processed`, `source_excluded`, etc.

**Knowledge events** describe knowledge evolution: `concept_created`, `concept_modified`, `contradiction_detected`, `decision_recorded`, `case_opened`, `case_closed`, etc.

Events are the canonical record of activity. Both dashboards and conversational agents consume the same event stream for operational and knowledge introspection.

## Architectural Evolution

The long-term architecture extracts a shared `CogForge Core` library from the CLI. See [ADR-003](adr-003-core-extraction.md).

```
Phase 1 (v1):  All logic in src/cogforge/, layers enforced via module boundaries.
Phase 2 (v1.5): src/cogforge/core/ extracted. CLI and conversational interface both consume core.
Phase 3 (v2):  Complete extraction. New server/ package for HTTP/API. Dashboard and web UI consume server.
```

The CLI is never deprecated. It remains the primary agent interface and the authoritative tool surface for deterministic operations. The conversational interface remains independent of whether operations originate from the CLI or a web application.

---

## CLI Engine Architecture

The following sections describe the deterministic CLI engine — the initial implementation surface for v1.

### Package Layout

Use a repo-level `src` folder.

Recommended layout:

```text
src/
  cogforge/
    __init__.py
    cli.py
    config.py
    paths.py
    reports.py
    state.py
    hashing.py
    validation.py
    sources/
      __init__.py
      substack.py
      youtube.py
      apple_notes.py
      manual.py
    pageindexing/
      __init__.py
      detector.py
      runner.py
      artifacts.py
    wiki/
      __init__.py
      archive.py
      history.py
      sessions.py
      indexes.py
    renderers/
      __init__.py
      json.py
      markdown.py
```

This keeps source connectors, PageIndex integration, state management, and wiki bookkeeping separate without over-fragmenting the first version.

## Packaging

Use one all-in dependency set for now. Do not introduce extras in the first version.

Recommended project shape:

```text
pyproject.toml
src/cogforge/
```

Recommended script entry point:

```toml
[project.scripts]
cogforge = "cogforge.cli:main"
```

The current source-specific packages under `projects/` should be physically migrated into `src/cogforge`, not wrapped indefinitely.

## CLI Framework

Use a Python CLI framework that supports nested command groups and typed options.

Either `click` or `typer` would work. `click` is closer to OpenKB and avoids magic. `typer` gives nicer type hints. The implementation plan can choose, but the command schema should not depend on framework-specific behavior.

Requirements:

- Nested command tree.
- Non-interactive execution.
- JSON default output.
- Markdown output by flag.
- Stable exit codes.
- Good error messages.

## Configuration

User-editable configuration should live at:

```text
llm_wiki/sources.yaml
```

The config file should include connector definitions, defaults, and long-document thresholds.

Draft shape:

```yaml
version: 1

defaults:
  output_format: json
  long_document:
    page_threshold: 10
    char_threshold: 20000

sources:
  substack:
    - id: paperswithbacktest
      publication: paperswithbacktest
      newsletter: "Algo Trading & AI"
      enabled: true
      cookies_txt: null

  youtube:
    - id: miniature-painting
      playlist_id: "..."
      enabled: true
      language_preferences: ["en", "en-US"]

  apple_notes:
    - id: trading-menu
      root_title: "Trading Menu"
      enabled: true
      max_depth: null
```

Internal runtime state should live under:

```text
llm_wiki/.llmkb/
```

This folder is not user-editable.

## Path Model

The architecture should support the future connector-first layout:

```text
llm_wiki/inbox/<connector>/<source-package>
llm_wiki/raw/<connector>/<source-package>
llm_wiki/pageindex/<connector>/<source-id>/
llm_wiki/.llmkb/state/sources/<source-id>.yaml
llm_wiki/.llmkb/reports/<run-id>.yaml
llm_wiki/.llmkb/enrichment/<connector>/<source-id>/
```

The enrichment path holds per-source PDF enrichment artifacts (manifest, extracted pages, tables, visual summaries, enriched Markdown). See the PDF Enrichment Pipeline section.

The implementation should be able to read old folder layouts during migration.

## Source Identity

Every source must have a stable source ID.

Recommended format:

```text
<connector>:<external-id-or-slug>
```

Examples:

```text
youtube:TIYnaNaZq4s
substack:paperswithbacktest/2026-05-10-jim-simons-the-mathematician-who
apple-notes:trading-menu/<note-uuid>
manual:<sha-or-slug>
```

For filesystem-safe state files, encode `:` and `/`.

Example:

```text
youtube__TIYnaNaZq4s.yaml
substack__paperswithbacktest__2026-05-10-jim-simons-the-mathematician-who.yaml
```

## Source State Schema

One YAML state file per source document.

Draft schema:

```yaml
version: 1
id: youtube:TIYnaNaZq4s
connector: youtube
document_type: transcript
status: inbox

origin:
  url: "https://www.youtube.com/watch?v=TIYnaNaZq4s"
  external_id: TIYnaNaZq4s
  parent_source_id: youtube-playlist:...
  title: "..."
  author: "..."
  fetched_at: "2026-05-14T00:00:00Z"

content:
  sha256: "..."
  size_bytes: 12345
  estimated_chars: 20000
  estimated_pages: null

paths:
  inbox: llm_wiki/inbox/youtube/TIYnaNaZq4s.md
  raw: null

pageindex:
  required: false
  status: null
  artifact_path: null
  error: null

last_error: null

excluded:
  reason: null
  note: null

runs:
  last_sync: null
  last_pageindex: null
  last_archive: null
```

Valid source statuses:

```text
inbox
processed
failed
excluded
```

`failed` must include an error phase:

```yaml
last_error:
  phase: sync | import | pageindex | archive | validation
  message: "..."
  retryable: true
  occurred_at: "..."
```

`excluded` must include a reason:

```yaml
excluded:
  reason: duplicate | irrelevant | unavailable | user_rejected | unsupported
  note: "..."
```

## PageIndex Integration

PageIndex should run for all long documents, regardless of connector. For PDF documents, PageIndex operates on the output of the PDF enrichment pipeline (see below), not on the raw PDF itself.

Long-document detection:

- Use page count when reliable.
- Use character count when no page count is available.
- Defaults: `page_threshold: 10`, `char_threshold: 20000`.
- Make thresholds configurable globally and per connector if needed.

PageIndex artifacts should live under:

```text
llm_wiki/pageindex/<connector>/<source-id>/
```

Suggested artifact files:

```text
tree.yaml
pages.yaml
metadata.yaml
```

The CLI should record artifact paths in the source state file.

PageIndex errors should not erase usable source packages. They should update `pageindex.status: failed` and return a report item requiring action.

### LLM Boundary

The CLI may call LLMs for two purposes that are not semantic wiki compilation:

1. **Document structuring** (PageIndex) — creating hierarchical document trees for navigation.
2. **Visual content extraction** (VLM summaries in PDF enrichment) — converting diagram/chart/table visual content into structured text for indexing.

The CLI must not call LLMs for concept synthesis, decision writing, contradiction detection, or any other semantic wiki compilation task.

## PDF Enrichment Pipeline

Before a PDF source reaches PageIndex, it passes through an enrichment pipeline that converts visual and tabular content into structured text. This makes PageIndex more useful on complex PDFs.

Pipeline:

```text
Native PDF
  → PyMuPDF page extraction
  → Page classifier (TEXT_ONLY | TABLE_PAGE | VISUAL_PAGE | LOW_TEXT_VISUAL_PAGE)
  → Enriched Markdown builder
  → PageIndex input
```

The pipeline produces:

```text
llm_wiki/.llmkb/enrichment/<connector>/<source-id>/
  manifest.json
  summary.md
  pages/
    page-001.text.md
  tables/
    page-005-table-001.csv
    page-005-table-001.md
  visuals/
    page-009.png
    page-009.visual.md
  enriched/
    <source-id>.enriched.md
```

The enriched Markdown file is the PageIndex input. It contains extracted page text, extracted tables in Markdown, VLM summaries for visually important pages, and page-level provenance.

The manifest records per-page routing decisions, visual signal metrics, and VLM call outcomes. It is for debugging and downstream audit.

Page routes:

- **TEXT_ONLY**: Enough extractable text, no strong visual signal. No VLM.
- **TABLE_PAGE**: One or more detected tables. Extract to CSV and Markdown. No VLM unless also a visual page.
- **VISUAL_PAGE**: Significant visual signal (images, drawings, visual hints). Render to PNG, call VLM for summary.
- **LOW_TEXT_VISUAL_PAGE**: Little extractable text but significant visual content. Render to PNG, call VLM.

The pipeline is page-fault tolerant. Text extraction, table extraction, rendering, or VLM failures on individual pages do not fail the whole document. Errors are recorded in the manifest and placeholders are inserted in the enriched Markdown.

## Report Schema

Reports are canonical run records. They should be stored only when useful and should be renderable to JSON or Markdown from the same data object.

Draft schema:

```yaml
version: 1
run_id: "20260514T000000Z-sync-youtube-abc123"
command: "sync youtube"
started_at: "..."
finished_at: "..."
status: success | partial | failed

summary:
  sources_seen: 0
  sources_created: 0
  sources_updated: 0
  sources_failed: 0
  sources_excluded: 0

changes:
  files_created: []
  files_modified: []
  files_moved: []
  files_deleted: []
  states_created: []
  states_updated: []

items:
  - source_id: youtube:...
    action: created | updated | skipped | failed | excluded
    message: "..."
    requires_llm_judgment: false

errors: []
next_commands: []
```

JSON output is the default. Markdown rendering should be available through a flag.

## Exit Codes

Draft exit codes:

```text
0 success
1 command error or invalid arguments
2 validation failed
3 partial success with failed source items
4 external dependency failure
5 state conflict
```

Commands should still emit structured reports on partial success and expected source-level failures.

## Source Connectors

### Substack

Migrate the existing `projects/substack-sync` code into `src/cogforge/sources/substack.py`.

Responsibilities:

- Discover posts.
- Fetch post HTML.
- Preserve original HTML.
- Download images.
- Download linked PDFs when configured.
- Write source package to `inbox/substack`.
- Create or update source state YAML.

### YouTube

Migrate `scripts/sync_playlists.sh` and `.opencode/skills/youtube-transcript` command logic into `src/cogforge/sources/youtube.py`.

Responsibilities:

- Sync configured playlists.
- Fetch single-video transcripts.
- Fetch metadata with `yt-dlp`.
- Fetch transcript text with `youtube-transcript-api`.
- Track no-transcript or unavailable videos as `excluded`.
- Write source package to `inbox/youtube`.
- Create or update source state YAML.

### Apple Notes

Migrate `projects/notes-graph` into `src/cogforge/sources/apple_notes.py`.

Responsibilities:

- Export graph from one configured root title.
- Export each note independently.
- Copy PDF attachments.
- Preserve note identity when available.
- Write source packages to `inbox/apple-notes`.
- Create or update source state YAML.

Apple Notes should not receive a special whole-graph processing model. It is a niche source and should follow the same source-per-document model.

## Wiki Bookkeeping

The CLI should gradually own deterministic bookkeeping:

- Append history log entries.
- Create or update session files.
- Update simple indexes when the operation is deterministic.
- Move processed source packages from inbox to raw.
- Validate required folders and state files.

The LLM still owns semantic wiki edits.

The command that moves a source from inbox to raw should update source state and logs in one operation. The final command name can be decided in the command reference and implementation plan.

## Agent Skill Integration

Skills should evolve from command snippets into workflow instructions plus CLI command selection guidance.

For example, a future inbox-processing skill should:

1. Call `cogforge status` or `cogforge inbox list`.
2. Select sources to process.
3. Read source package and PageIndex artifacts.
4. Perform LLM compilation into wiki pages.
5. Call CLI bookkeeping commands to log, update session, and mark source processed.
6. Report source contributions and contradictions to the user.

## Inbox Processing Orchestration

`cogforge inbox run` is the deterministic orchestrator. It does not trust spawned agents to perform preparation steps.

Flow per source:

1. Select next inbox source (`cogforge inbox list --limit 1`).
2. Run `prepare_inbox_source()` internally — package validation, PDF enrichment, long-document detection, PageIndex.
3. If prepare fails, log and skip to next source.
4. Spawn agent with prompt: *"The source has been pre-validated and prepared. Read it and compile it into the wiki."*
5. Agent calls `mark-processed` and `wiki log`.
6. Verify inbox count decreased.

This means agents never call `inbox prepare` themselves. The CLI passes preparation metadata (estimated chars, PageIndex required, artifact paths) to the agent in the prompt or report so the agent can consume it without needing to discover it.

## Source-by-Source Processing

Inbox sources are processed one at a time in isolated agent contexts.

- Each source gets a fresh subagent with no prior context from previous sources.
- This prevents context pollution (opinions from article A affecting reading of article B).
- Error isolation: one bad source does not crash the batch.
- Future optimization: subagents could be spawned in parallel batches.

## Structural Validation

Validation should be command-based and agent-friendly.

Initial checks:

- Required folders exist.
- Config schema is valid.
- Source state files parse.
- Source paths in state files exist.
- PageIndex artifacts referenced by state files exist.
- No duplicate source IDs.
- No source has impossible lifecycle and path combinations.

Later checks:

- Broken wikilinks.
- Missing index entries.
- Orphan pages.
- Duplicate or near-duplicate wiki pages.
- Pages marked `needs_review` without a review reason.

## Migration Plan Scope

The implementation plan will come later, but the architecture should anticipate these migration steps:

1. Create repo-level package and CLI entry point.
2. Add unified config and state model.
3. Move Substack sync code.
4. Move YouTube playlist and transcript sync code.
5. Move Apple Notes graph export code.
6. Add PageIndex detection and runner.
7. Add report rendering.
8. Add deterministic wiki bookkeeping commands.
9. Rewrite skills to call the CLI.
10. Remove or deprecate old scripts.

Do not preserve wrappers as a long-term architecture requirement.

## Test Strategy

- Unit-test state encoding, YAML round-trip, config loading, and report rendering.
- Snapshot-test JSON output for key commands.
- Use fixture source packages for connector-independent behavior.
- Use mocked external calls for Substack, YouTube, Apple Notes, PageIndex, and VLM in tests.
- Add at least one end-to-end dry-run test per connector.
- Test the prepare pipeline with both short and long document fixtures.

## Architecture Risks

- State/folder drift if commands bypass the state model.
- Over-modeling source states.
- Prematurely embedding semantic LLM compilation into the CLI.
- Divergent reports if Markdown and machine outputs are stored separately.
- PageIndex artifacts becoming opaque without clear source IDs and paths.
- Apple Notes macOS permissions and database changes.
- External-source sync failures from auth, rate limits, or unavailable transcripts.
- Event model drift if operational and knowledge events diverge in schema or semantics (see ADR-002).
- Core extraction scope creep — extracting too much too early creates unnecessary indirection; extracting too late creates a painful refactoring (see ADR-003).
- Conversational agent capability boundaries — the orchestrator model requires the agent to switch tools correctly; incorrect tool selection degrades the experience silently.

## Logging Standards

Every CLI command must show progress to the user. Logging is the standard mechanism for all connector modules.

### Output streams

- **Logging** → stderr. Human-readable progress, warnings, and errors.
- **JSON/Markdown output** → stdout. Machine-readable results, never polluted by log lines.

This separation ensures agents can always pipe stdout to `jq` or parse it as JSON without interference.

### Log levels

| Flag | Level | Purpose |
|---|---|---|
| (default) | INFO | Show per-source progress, skip/warn/error counts, key milestones |
| `--verbose` | DEBUG | Extra detail: fetch URLs, image counts, metadata fields |
| `--quiet` | ERROR | Only critical failures, no progress output |

Configured once in `CogforgeGroup.parse_args` via `logging.basicConfig()` — all connector modules share the same configuration automatically.

### Logger naming

Use `cogforge.<module>` naming for all loggers:

```python
log = logging.getLogger("cogforge.sync")           # substack
log = logging.getLogger("cogforge.sync.youtube")    # youtube
log = logging.getLogger("cogforge.sync.apple-notes") # apple notes
log = logging.getLogger("cogforge.migrate.youtube")  # migration tools
```

### What to log

| Level | Examples |
|---|---|
| INFO | `"discovered %d posts"`, `"[NEW] %s"`, `"skipping already-synced: %s"`, `"done. new=%d errors=%d"` |
| WARNING | `"yt-dlp failed for %s: HTTP 404"`, `"transcript fetch failed for %s"`, `"RATE LIMITED"` |
| ERROR | `"[FAIL] %s: %s"`, `"Could not locate ICNote entity"` |

### Progress visibility guarantee

Every sync command must emit at minimum:
- A start line with operation scope
- One line per source processed (new/skip/error)
- A summary line with counts

## Design Principles

- Agent-first for CLI design, human-first for conversational interface design.
- YAML for persisted state.
- JSON for default command output.
- Markdown as rendering, not separate truth.
- One source document, one source state file.
- Source lifecycle is separate from wiki element lifecycle.
- PageIndex state is metadata, not lifecycle.
- Folder layout is readable but not canonical.
- Semantic judgment stays with the LLM until proven otherwise.
- Observability data is queryable, not dashboard-only. Both visual and conversational consumers access the same APIs.
- Every conversational answer carries provenance references to concepts, sources, decisions, and contradictions.
- Conversation is an orchestrator over multiple tool domains, not a single RAG endpoint.
- CLI and future interfaces share core APIs through progressive extraction (see ADR-003).
