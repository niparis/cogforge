# cogforge Product Specification

## Purpose

`cogforge` is an agent-facing command line interface for maintaining the LLM wiki. It consolidates source synchronization, source state tracking, long-document indexing, reporting, logging, and session bookkeeping into a deterministic tool surface that an LLM agent can call reliably.

The CLI is not primarily a human product. It is a tool layer for agents. Design choices should favor predictable command schemas, stable machine-readable output, idempotent operations, and explicit state transitions over interactive convenience.

The provisional product name is `cogforge`. The name can change later.

## Product Goals

- Replace separate synchronization scripts with one coherent CLI.
- Keep the LLM responsible for judgment-heavy wiki compilation.
- Make source synchronization and processing state explicit rather than inferred only from folders.
- Use PageIndex directly for long documents so agents can work with structured document trees instead of oversized raw context.
- Preserve the current pipeline idea: synced sources land in `inbox`; sources move to `raw` only after the LLM has incorporated them into the wiki.
- Generate reliable reports that tell the agent what happened, what changed, what failed, and what requires LLM judgment.
- Make skills thinner and more robust by having them choose CLI commands and parameters instead of hand-assembling shell workflows.
- Improve self-healing and cleanup over time, while keeping user agency through post-compilation reports.

## Non-Goals For The First Version

- No fully autonomous semantic wiki compiler inside the CLI.
- No direct LLM calls for concept/synthesis/decision writing in the first version.
- No watch mode in the first version.
- No heavy pre-execution approval gates for normal wiki work.
- No separate package repository yet.
- No human-first interactive setup flow beyond minimal validation commands.

PageIndex may call an LLM internally for document structuring. That is allowed and desired. The boundary is that `cogforge` does not perform semantic wiki compilation itself in version one.

## Intended User

The main user is an LLM agent operating inside this repository.

The human maintainer may run commands during setup or debugging, but command behavior should be optimized for agents:

- JSON output by default.
- Markdown rendering only when requested.
- No interactive prompts in normal operation.
- Stable exit codes.
- Clear error phases.
- Explicit input and output paths.
- Idempotent commands where possible.

## Existing Problems

The project currently has useful but scattered automation:

- Substack sync is a Python package under `projects/substack-sync`.
- YouTube playlist sync is a Bash script with inline Python and external `uvx` calls.
- Apple Notes graph export is a Python package under `projects/notes-graph`.
- Skills contain both workflow reasoning and brittle command snippets.
- Folder moves currently carry lifecycle meaning, but they do not record retry state, source identity, source changes, PageIndex artifacts, or run reports.

This is manageable now, but will become harder as sources, skills, and processing workflows grow.

## Product Model

`cogforge` should treat the wiki as a pipeline.

1. Sources are synchronized or imported.
2. Source packages land in `llm_wiki/inbox`.
3. A source state file records lifecycle, identity, paths, hashes, and processing metadata.
4. Before an agent session is spawned, `cogforge inbox run` prepares the selected source deterministically: package validation, PDF enrichment when applicable, long-document detection, and PageIndex execution when thresholds are met.
5. The LLM agent compiles the already-prepared source material into wiki pages.
6. The CLI records structured logs/session bookkeeping and moves processed sources to `llm_wiki/raw`.
7. The agent reports changes, contradictions, unresolved issues, and follow-ups to the user.

## Canonical State

The product should use a hybrid model:

- Source YAML state is canonical.
- Folders are readable storage conventions.

Folders should make the repository easy to inspect, but folder location should not be the only source of truth.

### Source Lifecycle

Use a small source lifecycle:

```yaml
status: inbox | processed | failed | excluded
```

`inbox`: A usable source package exists and is waiting for LLM compilation.

`processed`: The LLM has incorporated the source into wiki pages and the source has been checkpointed into raw storage.

`failed`: A CLI operation failed. The state must include the failing phase, message, and whether retry is appropriate.

`excluded`: The source is intentionally out of the pipeline. A reason is required, such as duplicate, irrelevant, unavailable, or user rejected.

Do not use source lifecycle states like `indexed`, `normalized`, `ready_for_llm`, `stale`, or `superseded` in the first version. They either duplicate `inbox`, belong to PageIndex metadata, or are better represented as explicit flags/reasons.

### PageIndex State

PageIndex state belongs under source metadata, not the top-level source lifecycle:

```yaml
pageindex:
  required: true
  status: pending | complete | failed
  artifact_path: llm_wiki/pageindex/youtube/TIYnaNaZq4s/tree.yaml
```

A source can be `status: inbox` while `pageindex.status: complete`. That means the source is still waiting for LLM compilation, but its long-document structure is ready.

### Wiki Element State

Wiki page lifecycle is separate from source lifecycle.

For concepts, synthesis pages, derived outputs, and domain contexts:

```yaml
status: active | needs_review | retired
```

`active`: Current compiled wiki knowledge.

`needs_review`: Useful but affected by a known issue. Reasons can include disputed claim, weak sources, incomplete synthesis, or possible staleness.

`retired`: No longer current, but kept for history and provenance. Reasons can include superseded, duplicate, obsolete, or out of scope.

Claim-level annotations such as disputed, uncertain, superseded, or stale should be handled inside page content by the LLM, not as whole-page lifecycle states unless they affect the whole page.

Decision pages may keep their own decision workflow because decisions behave differently from knowledge pages.

## Source Configuration

User-editable configuration should be shallow and easy to find.

Recommended file:

```text
llm_wiki/sources.yaml
```

This file should unify configuration for:

- Substack publications.
- YouTube playlists and single-video transcript settings.
- Apple Notes graph export roots.

Internal state should live in a dot folder and should not be user-edited.

Recommended internal folder:

```text
llm_wiki/.llmkb/
```

## Folder Strategy

The product should move from document-type-first organization toward connector-first organization.

Recommended future layout:

```text
project-root/
  sources.yaml
  llm_wiki/
    inbox/
      youtube/
      substack/
      apple-notes/
      manual/
    raw/
      youtube/
      substack/
      apple-notes/
      manual/
    pageindex/
      youtube/
      substack/
      apple-notes/
      manual/
    .llmkb/
      state/
        sources/
      reports/
      runs/
      logs/
  .opencode/
    skills/
      process-inbox/
      answer/
      ...
    agents/
      inbox-processor-instructions.md
  .claude/
    skills/
      process-inbox/
      answer/
      ...
    agents/
      inbox-processor-instructions.md
```

The existing `inbox/transcripts`, `inbox/articles`, `raw/transcripts`, `raw/articles`, and similar folders can be migrated later. Migration should be documented separately from product behavior.

## Source Types In Scope

Version one should support the three current source families:

- Substack.
- YouTube playlists and single-video transcripts.
- Apple Notes graph export.

Manual files can be supported by the same source model, but the first migration priority is the existing automated sources.

## Long Document Policy

Use PageIndex directly for long documents.

Default thresholds:

- Page-based documents: `>= 10 pages`.
- Text documents without reliable page count: `>= 20,000 characters`, based on roughly 2,000 characters per page.

Both thresholds must be configurable.

Long document detection should not alter the source lifecycle by itself. It should populate `pageindex.required` and then run PageIndex if requested by the command.

As of the inbox pipeline hardening sprint, `cogforge inbox run` calls the same preparation logic internally before every agent spawn. Skills should not ask spawned agents to run `inbox prepare`; the agent should treat the source as already prepared and consume any PageIndex artifact paths or preparation metadata passed in the prompt/report.

## LLM Responsibilities

The LLM agent remains responsible for:

- Deciding which source material matters.
- Linking paragraphs or sections to sources.
- Detecting contradictions.
- Creating or updating concept pages.
- Creating or updating synthesis pages.
- Creating or updating decisions.
- Deciding whether a page needs review.
- Producing the user-facing explanation of knowledge changes.

The CLI can support these tasks by exposing source metadata, prepared long-document artifacts, relevant file lists, and structured reports.

## CLI Responsibilities

The CLI should own:

- Source sync.
- Source import.
- Source state creation and updates.
- Hashing and duplicate detection.
- PageIndex execution and artifact recording.
- Folder transitions between inbox and raw.
- History log entries.
- Session file creation or update.
- Structural validation.
- Machine-readable run reports.
- Per-source preparation before every `inbox run` agent spawn.
- Structured file logging under `.llmkb/logs/YYYY-MM-DD.log` for operational debugging.
- Rendering reports to Markdown on request.

## Agent Skills

Cogforge distributes companion agent skills as part of the software package.

Canonical skills are packaged inside the wheel and auto-synced into the local project on every Cogforge command:

- `process-inbox`
- `answer`
- `create-synthesis`
- `lint-wiki`
- `log-change`
- `persist-decision`
- `session-memory`
- `update-domain-context`
- `youtube-transcript`

Skills are managed software assets. The local copies in `.opencode/skills/` and `.claude/skills/` are overwritten on every sync. Do not edit them locally; they are not user configuration.

Agent prompt assets (e.g. `inbox-processor-instructions.md`) are also managed and synced.

## Reports

There should be one canonical report object per run when persistence is useful.

Recommended storage:

```text
llm_wiki/.llmkb/reports/<run-id>.yaml
```

Command output defaults to JSON for agents. Markdown is a rendering option, not a separate persisted story.

This avoids divergent human and machine reports.

Reports should separate:

- Facts observed by the CLI.
- Files created, moved, modified, or deleted.
- Source states updated.
- PageIndex artifacts created.
- Errors and retryability.
- Items requiring LLM judgment.
- Suggested next commands.

Contradiction detection is an LLM responsibility and should appear in agent prompts and compilation reports, not as deterministic CLI logic.

## Safety And Agency

The wiki should not require heavy gates for ordinary operation. The product should instead rely on:

- Idempotent commands.
- Clear reports.
- Explicit source states.
- Post-compilation summaries.
- Contradiction reporting by the LLM.
- Structural validation and self-healing commands.

Potentially destructive cleanup should require explicit flags.

## Command Surface

The CLI should use a command tree, not a flat command list.

See [command-reference.md](command-reference.md) for the draft command reference.

## Migration Scope

The specs should include a migration section, but the implementation plan comes later.

Migration should physically move code into the new `src/cogforge` package rather than wrapping the old projects indefinitely. Downtime is acceptable.

Compatibility wrappers are not a long-term requirement. Existing scripts should be merged into the CLI as a secondary objective.

## Open Product Questions

- Exact final CLI name.
- Exact source YAML schema.
- Exact PageIndex artifact schema.
- Whether manual source import should be part of the first implementation slice.
- Whether wiki element status should be represented in frontmatter immediately or introduced only when needed.
- How much session bookkeeping should be automated in the first implementation slice.
