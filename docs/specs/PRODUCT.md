# cogforge Product Specification

## Purpose

`cogforge` is a knowledge-base curation and exploration system built around an LLM-backed knowledge repository.

The purpose is twofold:

1. Build and maintain a high-quality curated knowledge base.
2. Provide a superior conversational interface over that knowledge base.

These goals are inseparable. The curation pipeline exists to improve the quality, explainability, and trustworthiness of the conversational experience. The conversational experience exists to make the knowledge base useful and to allow users to interrogate, validate, and improve the knowledge it contains.

Cogforge combines knowledge retrieval, knowledge curation, knowledge observability, and knowledge governance within a unified experience.

The provisional product name is `cogforge`. The name can change later.

## Core Philosophy

Most knowledge systems focus on retrieval. Cogforge focuses on knowledge stewardship.

The system is designed around three complementary activities:

- **Accessing** knowledge — asking questions and receiving grounded answers.
- **Understanding** knowledge — inspecting provenance, evidence, and reasoning.
- **Improving** knowledge — resolving contradictions, making governance decisions, and evolving the knowledge base.

Users should move fluidly between these activities. A question leads to an answer, which leads to evidence, which leads to source documents, which leads to compilation history, which surfaces contradictions, which prompt a user decision, which updates the knowledge base, which produces a revised answer. The user should never feel forced to switch tools or workflows.

## Delivery Tiers

The product is delivered in tiers. Each tier builds on the previous one.

**Tier 1 — CLI Engine (v1).** Source synchronization, inbox preparation, state tracking, long-document indexing (PageIndex), run reports, agent skill management, and folder lifecycle management. The deterministic tool surface that agents call reliably.

**Tier 2 — Conversational Layer (v1.5).** Conversation as the universal interface. Chat sessions support knowledge queries, meta-knowledge queries, provenance queries, and governance queries with conversational continuity across activities.

**Tier 3 — Full Workbench (v2).** Dashboard, Cases, knowledge evolution history, full observability UI, decisions workflow, and concept relationship visualization.

Each tier's scope is additive. Architecture decisions should accommodate later tiers without requiring rewrites.

## First-Class Objects

### Chat

Chat is a conversational lens over the entire system, not a standalone chatbot. Through Chat, users access concepts, sources, reports, runs, cases, and decisions without leaving the conversational experience. Chat sessions are first-class artifacts that maintain conversational continuity across queries and activities.

### Sources

External information entering the system: YouTube transcripts, Substack articles, Apple Notes, PDFs, web pages, and manual imports. Sources are the foundation of knowledge acquisition. They enter the pipeline, are prepared by the CLI engine, and are compiled into wiki knowledge by LLM agents.

### Concepts

Concepts represent curated knowledge. Each concept maintains provenance (which sources contributed), supporting evidence, confidence, change history, and relationships to other concepts. Concepts are living artifacts — they evolve as new sources arrive, contradictions emerge, and governance decisions are made.

### Cases

Cases represent unresolved issues requiring attention. They are a complementary tracking mechanism that sits above source and wiki element lifecycles, not a replacement for them. Examples: contradiction detected, stale knowledge, duplicate knowledge, low-confidence extraction, failed processing. A failed source may generate a Case; a `needs_review` concept may generate a Case. Cases are the primary mechanism for human review and intervention. Reopening a resolved source or concept is expressed as a new Case, not as a lifecycle regression.

### Decisions

Decisions represent durable governance artifacts. They capture human judgment — which interpretation to prefer, whether a source is trustworthy, how a contradiction should be resolved — and become part of the knowledge base history. Decisions influence future curation and are themselves auditable.

## Conversational Interface

Conversation is the universal interface through which users access knowledge, provenance, observability, governance, and curation. It is not merely a chat experience — it is a navigational layer over the entire knowledge ecosystem.

The delivery form of the conversational interface is intentionally abstract at the spec level. It may be realized as a web application, a CLI command, an API server, or a combination. The spec describes the *capabilities* the interface must provide, not the technology that delivers them.

### Query Types

**Knowledge Queries.** Questions about the content of the knowledge base. Examples: "What do we know about momentum investing?", "Explain PageIndex.", "Summarize hybrid retrieval limitations."

**Meta-Knowledge Queries.** Questions about the knowledge base itself. Examples: "What documents were added this week?", "Which sources discuss this topic?", "Which topics are poorly represented?"

**Provenance Queries.** Questions about how answers were generated. Examples: "Why did you answer this way?", "Which documents contributed to this answer?", "Which papers disagree with this conclusion?"

**Governance Queries.** Questions that influence future knowledge curation. Examples: "Which interpretation should be preferred?", "Is this source trustworthy?", "Should this contradiction be resolved?" Governance queries produce durable decisions.

### Conversational Continuity

Users must be able to move seamlessly between asking questions, inspecting evidence, inspecting sources, reviewing compilation history, reviewing decisions, and modifying knowledge — all within a single conversation. Chat acts as a navigational layer that reaches into every part of the system.

## Observability

Cogforge requires both operational observability and knowledge observability.

**Operational observability** answers: Did processing succeed? Did synchronization fail? What command executed? What errors occurred and are they retryable? This is provided by the CLI engine's structured logging, run reports, and source state tracking.

**Knowledge observability** answers: Why does the system believe this? Which evidence supports this conclusion? What changed? Which contradictions exist? Which decisions shaped the knowledge base? This must be accessible both conversationally and through visual/dashboard interfaces.

## Knowledge Evolution

Knowledge is treated as an evolving system. For every concept, users must be able to trace: where it originated, how it changed over time, which sources contributed to it, which contradictions emerged, and how those contradictions were resolved.

The system should feel closer to a source-controlled knowledge system than a traditional document repository. Every change must be attributable and reversible in principle.

## Dashboard & Navigation

The dashboard answers operational questions: what requires attention, what changed recently, what is new, what is unresolved. It acts as an operational overview.

Primary navigation: Dashboard, Chat, Sources, Concepts, Cases, Runs, Reports.

Chat acts as the universal entry point. Users should be able to move naturally between knowledge, provenance, observability, and governance through conversation, with the dashboard providing structured overview when needed.

## Product Goals

- Replace separate synchronization scripts with one coherent CLI engine.
- Keep the LLM responsible for judgment-heavy wiki compilation.
- Make source synchronization and processing state explicit rather than inferred only from folders.
- Use PageIndex directly for long documents so agents work with structured document trees instead of oversized raw context.
- Preserve the pipeline: synced sources land in `inbox`; sources move to `raw` only after the LLM has incorporated them into the wiki.
- Generate reliable reports that tell the agent what happened, what changed, what failed, and what requires LLM judgment.
- Make skills thinner and more robust by having them choose CLI commands and parameters instead of hand-assembling shell workflows.
- Improve self-healing and cleanup over time, while keeping user agency through post-compilation reports.
- Provide a conversational interface that makes knowledge retrieval, provenance inspection, observability, and governance accessible without switching tools.
- Track knowledge evolution with attributable history, source links, and contradiction visibility.
- Surface unresolved issues (contradictions, stale knowledge, failures) as Cases for human review.

## Non-Goals For v1

The following are explicitly out of scope for Tier 1:

- No conversational interface (knowledge queries, meta-knowledge queries, provenance queries, governance queries).
- No dashboard, Cases, knowledge evolution UI, or concept relationship visualization.
- No fully autonomous semantic wiki compiler inside the CLI.
- No direct LLM calls for concept/synthesis/decision writing.
- No watch mode.
- No heavy pre-execution approval gates for normal wiki work.
- No separate package repository.
- No human-first interactive setup flow beyond minimal validation commands.
- No OCR for scanned PDFs in the enrichment pipeline.
- No region-level visual cropping, caption-to-figure association, or logo deduplication.
- No diagram-to-Mermaid conversion in the enrichment pipeline.
- No multi-column reconstruction beyond PyMuPDF `sort=True`.

PageIndex may call an LLM internally for document structuring. That is allowed and desired. The boundary is that `cogforge` does not perform semantic wiki compilation itself in v1.

## Intended Users

The product has two user classes:

**LLM agents** operating inside the repository. In v1, agents are the primary user through the CLI. CLI behavior is optimized for agents: JSON output by default, Markdown rendering only when requested, no interactive prompts in normal operation, stable exit codes, clear error phases, explicit input and output paths, idempotent commands where possible.

**Human users** accessing the knowledge base through conversation. In v1.5+, humans become peers to agents. The conversational interface provides access to knowledge, provenance, observability, and governance without requiring CLI familiarity.

The human maintainer may also run CLI commands during setup or debugging, but the CLI interface is designed for agent consumption first.

## Product Model

`cogforge` treats the wiki as a pipeline.

1. Sources are synchronized or imported.
2. Source packages land in `llm_wiki/inbox`.
3. A source state file records lifecycle, identity, paths, hashes, and processing metadata.
4. Before an agent session is spawned, `cogforge inbox run` prepares the selected source deterministically: package validation, PDF enrichment when applicable (text extraction, table extraction, page classification, VLM summaries for visual pages), long-document detection, and PageIndex execution when thresholds are met.
5. The LLM agent compiles the already-prepared source material into wiki pages.
6. The CLI records structured logs/session bookkeeping and moves processed sources to `llm_wiki/raw`.
7. The agent reports changes, contradictions, unresolved issues, and follow-ups to the user.

## Source-by-Source Processing

Inbox sources are processed one at a time in isolated agent contexts. Each source gets a fresh subagent with no prior context from previous sources. This prevents context pollution (opinions from article A affecting reading of article B) and provides error isolation (one bad source does not crash the batch). The CLI loops over sources, forces preparation for each, spawns the agent with preparation metadata, and handles bookkeeping when the agent completes. The agent itself processes exactly one source and returns structured output.

## Canonical State

The product uses a hybrid model:

- Source YAML state is canonical.
- Folders are readable storage conventions.

Folders should make the repository easy to inspect, but folder location should not be the only source of truth.

### Source Lifecycle

```yaml
status: inbox | processed | failed | excluded
```

`inbox`: A usable source package exists and is waiting for LLM compilation.

`processed`: The LLM has incorporated the source into wiki pages and the source has been checkpointed into raw storage.

`failed`: A CLI operation failed. The state must include the failing phase, message, and whether retry is appropriate.

`excluded`: The source is intentionally out of the pipeline. A reason is required, such as duplicate, irrelevant, unavailable, or user rejected.

Do not use source lifecycle states like `indexed`, `normalized`, `ready_for_llm`, `stale`, or `superseded`. They either duplicate `inbox`, belong to PageIndex metadata, or are better represented as explicit flags/reasons.

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

### Cases and Lifecycle States

Cases are a cross-cutting tracking layer that sits above source and wiki element lifecycles. They do not replace or modify these lifecycles — they track unresolved issues that may span multiple objects.

A `failed` source may or may not have an open Case. A `needs_review` concept may or may not have an open Case. Cases are opened and closed independently, and their lifecycle is separate from the objects they reference. Resolving a Case does not automatically change a source or concept lifecycle; that change is a separate, deliberate action.

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

Tier 1 should support the three current source families:

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
- Opening Cases when contradictions, stale knowledge, or processing issues require human attention (v1.5+).
- Answering knowledge, meta-knowledge, provenance, and governance queries through the conversational interface (v1.5+).

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

Obsolete skills are automatically removed. For example, `youtube-transcript` was previously a skill but is now handled entirely by `cogforge sync youtube`.

Skills are managed software assets. The local copies in `.opencode/skills/` and `.claude/skills/` are overwritten on every sync. Do not edit them locally; they are not user configuration.

Agent prompt assets (e.g. `inbox-processor-instructions.md`) are also managed and synced.

### Skill Content Constraints

Skills must not embed shell command snippets, bash pipelines, or manual file path operations. They describe workflow intent and guide CLI command selection, not assembly of imperative steps. For example:

- ❌ `Append changes to ./llm_wiki/history/history.log`
- ✅ `Run: cogforge wiki log --message "..." --session PATH`

This keeps skills thin, makes them resilient to CLI changes, and ensures deterministic bookkeeping is owned by the CLI.

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

## Future Product Goals

These goals are not scheduled for Tier 1, but they shape architectural decisions so that the system can evolve into them cleanly.

### Conversational Interface (Tier 2)

A conversational interface supporting knowledge queries, meta-knowledge queries, provenance queries, and governance queries. Chat sessions maintain conversational continuity and act as a navigational layer over concepts, sources, reports, runs, cases, and decisions.

### Cases, Dashboard, and Knowledge Evolution (Tier 3)

- **Cases** as a cross-cutting tracking mechanism for unresolved issues, surfaced in the dashboard and accessible through conversation.
- **Dashboard** answering what requires attention, what changed, what's new, and what's unresolved.
- **Knowledge evolution UI** showing per-concept provenance, change history, contributing sources, and contradiction resolution paths.

### Skill Lifecycle and Contract Format

Managed skills should carry a front-matter contract with: `name`, `version`, `status`, `triggers`, `dependencies`, `owner`, and `updated` fields. The status field powers a lifecycle state machine (`experimental → active → deprecated → removed`). This allows the CLI to validate skill health, detect stale skills, and evolve the skill set safely without silent breakage.

### Hook Protocol

A future mechanism for skills to declare `pre`, `post`, and `on_error` hooks that the CLI can enforce. For example, a mandatory `should-distill` post-hook would prevent an agent from silently skipping the "did this run produce anything worth distilling?" check. The hook action whitelist (e.g., `proceed`, `skip`, `warn`, `propose-distill`) keeps agents from inventing arbitrary side effects.

### Separation of Concerns

Routing rules — which skill to use when, and how skills cooperate — belong in `AGENTS.md` (the schema layer). Domain knowledge belongs in individual `skills/<name>/SKILL.md` files (the wiki layer). `AGENTS.md` must never contain domain knowledge; skills must not import each other's internals. This separation keeps the routing table stable, short, and trustworthy while allowing skills to evolve independently.

### Parallel Batch Processing

Subagents could be spawned in parallel batches for throughput when the agent runtime supports it. The one-at-a-time constraint is an isolation guarantee, not a throughput ceiling. Parallel batching should respect the same per-source isolation rules.

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
- How Chat sessions relate to the source processing pipeline — same agent context, separate context, or orchestrated handoff.
- How Cases integrate with source and wiki element lifecycles at the schema level.
- Delivery form for the conversational interface — CLI command, API server, web application, or a combination.
- Model for knowledge evolution history — git-backed, database, YAML diffs, or embedded in page frontmatter.
