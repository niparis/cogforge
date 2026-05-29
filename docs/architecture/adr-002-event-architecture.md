# ADR-002: Dual-Domain Event Architecture

## Status

Accepted.

## Context

Cogforge produces two kinds of information that downstream consumers need: operational telemetry (did sync succeed? did PageIndex fail?) and knowledge evolution signals (was a concept created? was a contradiction detected? was a decision recorded?).

Without a structured event model, each consumer (dashboard, conversational agent, CLI report) would need to poll state files, parse logs, or infer facts from artifacts. This creates fragile, divergent interpretations of the same underlying activity.

## Decision

Cogforge emits structured events in two domains:

**Operational Events** describe CLI activity:
- `sync_started`, `sync_completed`, `sync_failed`
- `pageindex_started`, `pageindex_completed`, `pageindex_failed`
- `inbox_prepare_started`, `inbox_prepare_completed`, `inbox_prepare_failed`
- `source_marked_processed`, `source_excluded`

**Knowledge Events** describe knowledge evolution:
- `concept_created`, `concept_modified`, `concept_retired`
- `contradiction_detected`, `contradiction_resolved`
- `decision_recorded`
- `case_opened`, `case_closed`
- `review_needed`, `review_resolved`

Events are emitted by the code that performs the action (CLI for operational events, LLM agent for knowledge events). They are consumed by:

- **Run reports** — operational events are aggregated into structured YAML reports.
- **Dashboards** — both domains feed visual overviews (what ran, what changed, what needs attention).
- **Conversational agents** — operational events answer meta-knowledge queries ("what failed yesterday?"); knowledge events answer provenance queries ("why did this concept change?").

Events are the canonical record of activity. State files, logs, and reports are derived views.

## Consequences

- **Positive**: Single source of truth for activity. Consumers don't need to parse multiple formats or infer state from side effects.
- **Positive**: New consumers (e.g., a notification system, a future web dashboard) plug into the same event stream without refactoring producers.
- **Positive**: Conversational agents can answer operational questions ("what failed?", "what's in the inbox?") by querying events rather than crawling the filesystem.
- **Negative**: Knowledge events depend on LLM agents emitting them reliably. If an agent creates a concept without emitting `concept_created`, the event stream is incomplete. Knowledge events are best-effort until agents are instrumented.
- **Negative**: Event taxonomy must be designed carefully. Adding event types later requires consumers to handle them. Prefer fewer, well-defined event types over exhaustive granularity in v1.
- **Mitigation**: Operational events are deterministic (emitted by the CLI). Knowledge events are aspirational for v1, required for v1.5+. The event schema is extensible — new event types are additive, and consumer code handles unknown event types gracefully.
