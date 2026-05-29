# ADR-001: Three-Layer Architecture

## Status

Accepted.

## Context

Cogforge combines knowledge retrieval, curation, observability, and governance. Without an architectural layering model, these concerns risk becoming entangled — observability logic embedded in the knowledge layer, conversational logic mixed with curation logic, and no clear API surface for future consumers.

The product spec defines three delivery tiers: CLI engine (v1), conversational layer (v1.5), and full workbench (v2). Each tier adds new capabilities that must compose cleanly with existing ones.

## Decision

Cogforge is organized into three logical layers:

```
Knowledge Layer        (concepts, sources, wiki content, relationships, decisions)
        ↓
Observability Layer    (runs, reports, logs, events, state, provenance)
        ↓
Interaction Layer      (CLI, conversational interface, dashboard, API)
```

**Knowledge Layer** owns the data models: concepts, sources, wiki pages, cases, decisions, and their relationships. It answers "what do we know?"

**Observability Layer** owns operational and knowledge telemetry: run reports, processing logs, state transitions, concept provenance, event history. It answers "what happened?" and "why does the system believe this?"

**Interaction Layer** owns entry points: the CLI commands, the conversational interface, the dashboard, and any future API. It consumes the Knowledge and Observability layers through defined interfaces. It answers "how does the user interact?"

Layer boundaries are enforced by dependency direction: the Interaction layer depends on both lower layers; the Observability layer depends on the Knowledge layer. No upward dependencies.

The conversational interface sits at the Interaction Layer and has access to both Knowledge and Observability data. This enables users to ask knowledge questions, provenance questions, operational questions, and governance questions through the same interface.

## Consequences

- **Positive**: Clean separation enables independent evolution of each layer. The CLI engine (v1) lives primarily in the Knowledge and Observability layers. The conversational interface (v1.5) plugs into both through the Interaction layer. The dashboard (v2) consumes Observability APIs.
- **Positive**: Observability data is a first-class architectural concern, not a side effect of processing. Both visual dashboards and conversational agents consume the same Observability APIs.
- **Positive**: The CLI, web UI, and conversational interface share the same core — they differ only in presentation.
- **Negative**: Requires discipline to avoid shortcutting layer boundaries, especially during early v1 development when the Interaction layer is thin.
- **Negative**: Adds abstraction overhead. Simple operations (e.g., "sync a source") must not require navigating three layers when the task is straightforward.
- **Mitigation**: Layers are logical, not necessarily separate packages. In v1, a single Python package can implement multiple layers as long as the dependency direction is respected. Physical separation follows when complexity warrants it.
