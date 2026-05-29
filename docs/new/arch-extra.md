# CogForge Workbench - Technical Architecture and Implementation Strategy (Revised)

## Architectural Principle

CogForge consists of three logical layers:

Knowledge Layer

↓

Observability Layer

↓

Interaction Layer

The conversational interface sits at the Interaction Layer and must have access to both knowledge and observability data.

This allows users to ask:

- knowledge questions
- provenance questions
- operational questions
- governance questions

through the same interface.

---

# Chat as a System Interface

The chat system should not be implemented as a simple RAG endpoint.

Instead, the chat system acts as an orchestrator over multiple information domains.

Potential tools available to the conversational agent include:

- Concept search
- Source search
- PageIndex navigation
- Run inspection
- Report inspection
- Case inspection
- Decision inspection
- Knowledge graph exploration

The agent should be capable of switching between these domains dynamically.

---

# Unified Query Model

Internally, questions should be classified into categories.

Examples:

Knowledge Query

"What is PageIndex?"

Meta-Knowledge Query

"What documents discussing PageIndex were added this month?"

Provenance Query

"Why was this source not used in the answer?"

Governance Query

"Should these contradictory papers be reconciled?"

The backend should expose APIs that support all four categories.

---

# Observability as Queryable Data

Observability data should not exist only in dashboards.

It should be accessible through APIs used by both:

- visual interfaces
- conversational interfaces

Examples:

"What failed yesterday?"

"What sources are waiting in the inbox?"

"What concepts changed this week?"

The conversational agent should be able to answer these directly.

---

# Knowledge Provenance Architecture

Every answer should maintain references to:

- concepts used
- source documents used
- decisions consulted
- contradictions encountered

This enables conversational provenance inspection.

Users should be able to drill into answers interactively.

---

# Case-Aware Conversation

The conversational system should understand Cases as first-class entities.

Examples:

- contradiction cases
- stale concept cases
- failed processing cases

A user should be able to discuss a case directly within the chat interface.

Case conversations become part of the governance record.

---

# Conversation Persistence

Conversations are not isolated sessions.

Conversations may generate:

- decisions
- case updates
- concept updates
- processing actions

Important interactions should be persisted as structured artifacts.

---

# Backend Services

The backend should expose services for:

Knowledge Access

- concepts
- wiki content
- relationships

Observability

- runs
- reports
- logs
- events

Governance

- cases
- decisions
- reviews

The chat system becomes a consumer of all three service families.

---

# Event Architecture

Structured events become critical.

Events should describe both operational activity and knowledge evolution.

Operational Events

- sync_started
- sync_completed
- pageindex_started
- pageindex_failed

Knowledge Events

- concept_created
- concept_modified
- contradiction_detected
- decision_recorded

These events feed both dashboards and conversational introspection.

---

# Long-Term Evolution

Current Architecture

Web UI

↓

Backend

↓

CogForge CLI

Future Architecture

Web UI

↓

Backend

↓

CogForge Core

↑

CLI

The eventual goal is for both the UI and CLI to consume the same core APIs.

The conversational interface should remain independent of whether operations originate from the CLI or the web application.

---

# Development Priorities

Phase 1

- Dashboard
- Run management
- Report viewing
- Source browsing

Phase 2

- Conversational knowledge access
- Provenance inspection
- Source introspection

Phase 3

- Structured event system
- Knowledge lineage
- Concept history

Phase 4

- Cases
- Contradiction workflows
- Decision tracking

Phase 5

- Full conversational governance
- Knowledge evolution analysis
- Core extraction and shared APIs

The long-term objective is a system where knowledge, observability, and governance are all queryable through the same conversational interface while remaining fully auditable and traceable.