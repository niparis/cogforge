# CogForge Workbench - Product Vision and User Experience (Revised)

## Executive Summary

CogForge is a knowledge-base maintenance, curation, and exploration system built around an LLM-backed knowledge repository.

The purpose of the system is twofold:

1. Build and maintain a high-quality curated knowledge base.
2. Provide a superior conversational interface over that knowledge base.

These goals are inseparable.

The curation pipeline exists to improve the quality, explainability, and trustworthiness of the conversational experience.

The conversational experience exists to make the knowledge base useful and to allow users to interrogate, validate, and improve the knowledge contained within it.

CogForge therefore combines:

- knowledge retrieval
- knowledge curation
- knowledge observability
- knowledge governance

within a unified experience.

---

# Core Philosophy

Most knowledge systems focus on retrieval.

CogForge focuses on knowledge stewardship.

The system is designed around three complementary activities:

- Accessing knowledge
- Understanding knowledge
- Improving knowledge

Users should be able to move fluidly between these activities.

For example:

Question

↓

Answer

↓

Evidence

↓

Source Documents

↓

Compilation History

↓

Contradictions

↓

User Decision

↓

Updated Knowledge

↓

Revised Answer

The user should never feel forced to switch tools or workflows.

---

# Conversational Interface

Conversation is a first-class capability.

However, conversation is not merely a chat experience.

Conversation is the universal interface through which users access:

- knowledge
- provenance
- observability
- governance
- curation

The conversational interface should support multiple classes of queries.

---

## Knowledge Queries

Questions about the content of the knowledge base.

Examples:

- What do we know about momentum investing?
- Explain PageIndex.
- Summarize hybrid retrieval limitations.
- What are common miniature painting workflows?

These represent a primary use case.

The knowledge base exists to support these conversations.

---

## Meta-Knowledge Queries

Questions about the knowledge base itself.

Examples:

- What documents were added this week?
- What sources discuss this topic?
- Which concepts were updated recently?
- What knowledge comes from this author?
- Which topics are poorly represented?

The system should be able to introspect itself.

---

## Provenance Queries

Questions about how answers were generated.

Examples:

- Why did you answer this way?
- Which documents contributed to this answer?
- Which sources were ignored?
- Why was author X not included?
- Which papers disagree with this conclusion?

Users should be able to interrogate the reasoning path behind any answer.

---

## Governance Queries

Questions that influence future knowledge curation.

Examples:

- Which interpretation should be preferred?
- Is this source trustworthy?
- Should this contradiction be resolved?
- Should this concept be promoted?

Governance queries produce durable decisions.

---

# Conversational Continuity

The user should be able to move seamlessly between:

- asking questions
- inspecting evidence
- inspecting sources
- reviewing compilation
- reviewing decisions
- modifying knowledge

within a single conversation.

Conversation should act as a navigational layer over the entire knowledge ecosystem.

---

# First-Class Objects

## Chat

Chat is a first-class object.

However, Chat is not a standalone chatbot.

Chat is a conversational lens over the entire system.

Through Chat, users should be able to access:

- concepts
- sources
- reports
- runs
- cases
- decisions

without leaving the conversational experience.

---

## Sources

External information entering the system.

Examples:

- YouTube transcripts
- Substack articles
- Apple Notes
- PDFs
- Web pages

Sources remain the foundation of knowledge acquisition.

---

## Concepts

Concepts represent curated knowledge.

Concepts maintain:

- provenance
- supporting evidence
- confidence
- history
- relationships

Concepts are living artifacts.

---

## Cases

Cases represent unresolved issues requiring attention.

Examples:

- contradiction detected
- stale knowledge
- duplicate knowledge
- low-confidence extraction
- failed processing

Cases are the primary mechanism for human review and intervention.

---

## Decisions

Decisions represent durable governance artifacts.

They capture human judgment and become part of the knowledge base history.

---

# Dashboard Philosophy

The dashboard answers:

- What requires attention?
- What changed recently?
- What is new?
- What is unresolved?

The dashboard acts as an operational overview.

The conversational interface acts as the primary exploration interface.

---

# Observability Philosophy

CogForge requires both operational observability and knowledge observability.

Operational observability answers:

- Did processing succeed?
- Did synchronization fail?
- What command executed?

Knowledge observability answers:

- Why does the system believe this?
- Which evidence supports this conclusion?
- What changed?
- Which contradictions exist?
- Which decisions shaped the knowledge base?

Knowledge observability must be accessible both visually and conversationally.

---

# Knowledge Evolution

Knowledge should be treated as an evolving system.

For every concept, users should be able to understand:

- where it originated
- how it changed
- which sources contributed
- which contradictions emerged
- how those contradictions were resolved

The interface should feel closer to a source-controlled knowledge system than a traditional document repository.

---

# Navigation Model

Primary navigation:

- Dashboard
- Chat
- Sources
- Concepts
- Cases
- Runs
- Reports

Chat acts as a universal entry point into the system.

Users should be able to move naturally between knowledge, provenance, observability, and governance through conversation.

---

# Long-Term Vision

CogForge is a knowledge evolution workbench.

Its goal is not merely to answer questions.

Its goal is to help users:

- build knowledge
- maintain knowledge
- understand knowledge
- challenge knowledge
- govern knowledge
- trust knowledge

through a unified conversational and operational experience.