# cogforge Initial Implementation Plan

## Purpose

This plan turns the initial `cogforge` product, architecture, and command-reference specs into a staged implementation path.

References:

- [Product specification](../product.md)
- [Technical architecture](../architecture.md)
- [Command reference](../command-reference.md)

The goal is to build the deterministic agent-facing CLI in slices, starting with the package skeleton, schemas, and state/report foundations, then migrating source connectors one at a time.

## Planning Principles

- Keep the CLI agent-first: JSON default output, no interactive prompts, stable exit codes.
- Build vertical slices that can be tested from the command line.
- Avoid semantic wiki compilation in the CLI.
- Treat source YAML state as canonical and folders as readable storage conventions.
- Physically migrate existing code into `src/cogforge`; do not keep wrappers as the long-term architecture.
- Keep each sprint shippable even if later connectors are not migrated yet.

## Out Of Scope For This Plan

- Watch mode.
- Direct LLM calls for concept/synthesis/decision writing.
- Full wiki semantic linting.
- Separate package repository extraction.
- Comprehensive source-to-paragraph provenance.

## Sprint 0: Project Skeleton And Tooling

### Goal

Create the repo-level Python package and a minimal `cogforge` CLI entry point.

### Work

- Add root `pyproject.toml` or update the existing packaging strategy if one already exists.
- Create `src/cogforge`.
- Add `cogforge.cli:main`.
- Choose CLI framework, preferably `click` unless implementation needs make `typer` clearly better.
- Implement global options:
  - `--wiki-root`
  - `--config`
  - `--format`
  - `--report`
  - `--dry-run`
  - `--verbose`
  - `--quiet`
- Implement shared exit-code handling.
- Add basic tests for CLI invocation and JSON output.

### Deliverable

`cogforge status` runs and returns valid JSON, even if most counts are zero or stubbed.

### Acceptance Criteria

- `uv run cogforge status` or equivalent local command works.
- CLI emits valid JSON by default.
- Invalid arguments return a non-zero exit code.
- No command prompts for human input.

## Sprint 1: Config, Paths, Reports, And Source State

### Goal

Build the deterministic core that all connectors will use.

### Work

- Implement config loading from `llm_wiki/sources.yaml`.
- Define default config values in code.
- Implement path resolution for:
  - `llm_wiki/inbox/<connector>`
  - `llm_wiki/raw/<connector>`
  - `llm_wiki/pageindex/<connector>`
  - `llm_wiki/.llmkb/state/sources`
  - `llm_wiki/.llmkb/reports`
- Implement source ID encoding and decoding for state filenames.
- Implement source state YAML read/write.
- Implement source lifecycle validation:
  - `inbox`
  - `processed`
  - `failed`
  - `excluded`
- Implement report data model.
- Implement JSON report rendering.
- Implement Markdown rendering from the same report object.
- Implement:
  - `cogforge config validate`
  - `cogforge config show`
  - `cogforge state show`
  - `cogforge state validate`
  - `cogforge reports list`
  - `cogforge reports show`
  - `cogforge reports render`

### Deliverable

The CLI can validate config, inspect state, and emit canonical reports before any connector is migrated.

### Acceptance Criteria

- Missing config returns structured JSON with a clear error.
- State files round-trip through YAML.
- Markdown report output is generated from the same in-memory report object as JSON.
- State validation catches duplicate IDs and invalid status values.

## Sprint 2: Substack Connector Migration

### Goal

Move existing Substack sync into `src/cogforge` and make it write source state.

### Work

- Migrate code from `projects/substack-sync/substack_sync`.
- Preserve existing behavior:
  - post discovery
  - cached index use
  - HTML preservation
  - Markdown conversion
  - image download
  - PDF download
  - paywall stub handling
  - failed slug tracking
- Adapt output paths to `llm_wiki/inbox/substack`.
- Create or update one source state YAML per post.
- Implement:
  - `cogforge sync substack`
- Support options from the command reference:
  - `--source-id`
  - `--all`
  - `--max`
  - `--refresh-index`
  - `--cookies-txt`
  - `--skip-pdfs`

### Deliverable

Substack sync works through the new CLI without using `scripts/sync_substack.sh`.

### Acceptance Criteria

- Dry run reports discovered posts without writing source packages.
- A real sync writes source packages to `inbox/substack`.
- Each new post has a state YAML file.
- Already-synced posts are skipped idempotently.
- Errors are reported per source without aborting the entire run when possible.

## Sprint 3: YouTube Connector Migration

### Goal

Move YouTube playlist and transcript fetching into `src/cogforge`.

### Work

- Replace Bash and inline Python logic from `scripts/sync_playlists.sh`.
- Reuse the transcript behavior described by the existing YouTube transcript skill.
- Implement playlist sync from unified config.
- Implement single video transcript fetch.
- Track unavailable videos or missing transcripts as `excluded` when the failure is expected and permanent enough.
- Track external/tool failures as `failed` when retry may work.
- Write transcript source packages to `llm_wiki/inbox/youtube`.
- Create or update source state YAML.
- Implement:
  - `cogforge sync youtube`

### Deliverable

YouTube playlist and single-video transcript sync work through the CLI.

### Acceptance Criteria

- Existing raw and inbox files are not overwritten accidentally.
- Transcript output remains Markdown with metadata.
- No-transcript videos are represented in state/report output.
- Rate-limit or external command failures have a clear error phase and retryability.

## Sprint 4: Apple Notes Connector Migration

### Goal

Move Apple Notes graph export into `src/cogforge` while keeping each note as an independent source.

### Work

- Migrate code from `projects/notes-graph/notes_graph`.
- Preserve current behavior:
  - read Apple Notes database
  - discover linked notes
  - export note body to Markdown
  - copy PDF attachments
- Adapt output to `llm_wiki/inbox/apple-notes`.
- Create one state file per exported note.
- Preserve note UUID when available.
- Implement:
  - `cogforge sync apple-notes`

### Deliverable

Apple Notes export works through the new CLI and follows the same source model as other connectors.

### Acceptance Criteria

- A configured root note exports independent note packages.
- PDF attachments are copied and referenced.
- macOS permission/database failures are reported as external dependency failures.
- Each note has a stable source ID and state YAML.

## Sprint 5: PageIndex Preparation

### Goal

Add long-document detection and PageIndex artifact generation.

### Work

- Implement long-document detection:
  - page count when available
  - character count otherwise
  - defaults: 10 pages, 20,000 characters
- Add config overrides for thresholds.
- Integrate PageIndex directly.
- Write artifacts under `llm_wiki/pageindex/<connector>/<source-id>/`.
- Record PageIndex status and artifact path in source state.
- Implement:
  - `cogforge pageindex detect`
  - `cogforge pageindex run`
  - `cogforge pageindex show`
  - `cogforge inbox prepare`

### Deliverable

An agent can prepare a long source and receive paths to the source package and PageIndex artifacts.

### Acceptance Criteria

- Short sources do not require PageIndex.
- Long sources can be indexed.
- PageIndex failure does not destroy or move the source package.
- `inbox prepare` emits clear machine-readable paths for agent consumption.

## Sprint 6: Inbox Finalization And Wiki Bookkeeping

### Goal

Move deterministic post-compilation bookkeeping into the CLI.

### Work

- Implement source package transition from inbox to raw.
- Update state from `inbox` to `processed`.
- Append history log entries.
- Support session file creation or update from structured input.
- Implement:
  - `cogforge inbox list`
  - `cogforge inbox show`
  - `cogforge inbox mark-processed`
  - `cogforge inbox exclude`
  - `cogforge wiki log`
  - `cogforge wiki session close`

### Deliverable

After the LLM compiles a source into wiki pages, the agent can call the CLI to checkpoint the source and update deterministic logs.

### Acceptance Criteria

- `mark-processed` updates state and moves files atomically enough to avoid partial state drift.
- `exclude` requires a reason.
- History log entries include source ID, reason, and associated session/report when provided.
- Commands are idempotent or report a clear state conflict.

## Sprint 7: Validation, Migration, And Script Removal

### Goal

Make the new CLI the primary execution path and retire old scripts.

### Work

- Implement `cogforge wiki validate`.
- Implement safe `cogforge state repair --dry-run`.
- Add migration helpers for existing source folders where useful.
- Rewrite relevant skills to reference CLI commands instead of shell snippets.
- Deprecate or remove:
  - `scripts/sync_substack.sh`
  - `scripts/sync_playlists.sh`
  - old project-local entry points under `projects/` once migrated
- Update documentation to mark old paths as historical.

### Deliverable

The new CLI is the documented way for agents to sync, prepare, and finalize source processing.

### Acceptance Criteria

- Validation catches missing state files, missing source paths, invalid statuses, and missing PageIndex artifacts.
- Old scripts are no longer required for normal workflows.
- Skills describe the workflow and CLI parameter choices rather than embedding long command snippets.

## Cross-Cutting Test Strategy

- Unit-test state encoding, YAML round-trip, config loading, and report rendering.
- Snapshot-test JSON output for key commands.
- Use fixture source packages for connector-independent behavior.
- Use mocked external calls for Substack, YouTube, Apple Notes, and PageIndex in tests.
- Add at least one end-to-end dry-run test per connector.

## Cross-Cutting Documentation Updates

When implementation begins, update docs as behavior becomes real:

- Keep [command-reference.md](../command-reference.md) aligned with implemented commands.
- Add examples of agent workflows.
- Add migration notes after the first connector is migrated.
- Record any intentional deviations from the architecture spec.

## Risks To Watch

- State/folder drift if files are moved outside the CLI.
- Overly broad source states creeping back in.
- External API and auth failures turning into noisy state churn.
- Apple Notes permission errors being hard to reproduce in tests.
- PageIndex output changing shape across versions.
- Skills continuing to bypass the CLI after migration.

## First Implementation Slice Recommendation

Start with Sprint 0 and Sprint 1 together as the first implementation slice.

Reason: connector migration will be cleaner once config, state, report, path, and rendering primitives exist. The first visible milestone should be a working `cogforge status`, `cogforge config validate`, and `cogforge state validate` with valid JSON output.
