# ADR-003: Core Library Extraction Path

## Status

Accepted.

## Context

Cogforge currently exists as a CLI tool (`src/cogforge/`). The product vision calls for conversational and dashboard interfaces (v1.5+) that consume the same knowledge, observability, and governance capabilities. Without a shared core, each interface would duplicate logic or couple to CLI internals.

The long-term architecture goal is:

```
Web UI / API Server
        ↓
  CogForge Core  ←  CLI
```

Both the CLI and future interfaces consume the same core library. The conversational interface remains independent of whether operations originate from the CLI or a web application.

## Decision

Cogforge's codebase follows a progressive extraction path:

**Phase 1 (v1 — CLI engine):** All logic lives in `src/cogforge/`. No physical separation of core vs. CLI. The three-layer architecture (ADR-001) is enforced through module boundaries within the package. CLI entry points (`cli.py`) consume domain modules; domain modules never import CLI code.

**Phase 2 (v1.5 — conversational layer):** Extraction begins. Domain logic (source management, state, reports, validation) moves into `src/cogforge/core/`. The CLI becomes a thin wrapper around core APIs. The conversational interface (however delivered) also consumes core APIs.

**Phase 3 (v2 — full workbench):** Complete extraction. `src/cogforge/core/` is the shared library. `src/cogforge/cli/` is the CLI wrapper. A new `src/cogforge/server/` (or equivalent) provides HTTP/API access. Dashboard and web UI consume the server.

The CLI is never deprecated. It remains the primary agent interface and the authoritative tool surface for deterministic operations.

## Consequences

- **Positive**: Prevents logic duplication between CLI and future interfaces. Source management, state transitions, and report generation are implemented once.
- **Positive**: Enables testing of core logic independently of CLI presentation.
- **Positive**: Allows the conversational interface to call the same operations as the CLI (e.g., "sync sources from YouTube") without shelling out to a subprocess.
- **Negative**: Phase 1 has no physical separation, risking accidental CLI coupling in domain modules. Mitigated by code review and architecture enforcement in tests.
- **Negative**: Extraction in Phase 2 is a refactoring tax. Mitigated by clear module boundaries from day one.
- **Negative**: Core API design choices made for CLI use may not perfectly suit a synchronous HTTP API. Mitigated by designing core APIs to be stateless and request-response from the start.
