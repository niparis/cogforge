# Knowledge Base Agent Instructions

You are maintaining a Cogforge-managed knowledge base.

The folder structure and meaning of each directory is defined in:

- `./llm_wiki/system/structure.md`

Read that file before doing any file operations. Treat it as authoritative.

This repository is not the Cogforge source repository. It is a durable, structured, interlinked markdown knowledge base.

## Tool Boundary

Use the installed `cogforge` command to perform deterministic bookkeeping and source lifecycle operations.

Do not edit Cogforge source code from inside this repository. Code, packaging, and CLI architecture decisions belong in the Cogforge repository, not in this knowledge base.

## Global Rules

- Preserve the domain boundaries defined by the user.
- Do not create new domains without explicit user approval.
- Keep indexes updated when wiki pages are created, renamed, or substantially changed.
- Keep durable claims in concept/domain/synthesis pages, not in ad hoc notes.
- Use `llm_wiki/system/structure.md` as the source of truth for data layout.

## Session Bookkeeping

At the end of a substantial knowledge-base interaction, run:

```bash
cogforge wiki session-new --summary "<intent>" --domain "<domain>" --files-changed "path1,path2" --next-steps "step1,step2"
```

A substantial knowledge-base interaction is one where KB files, durable knowledge, domain context, decisions, synthesis, contradictions, or unresolved next steps changed.

Do not run KB session bookkeeping for Cogforge code changes.

## Inbox Processing

Process inbox sources one at a time. Use:

```bash
cogforge inbox list --limit 1 --format json
cogforge inbox show <id> --format json
```

Then update the wiki according to the KB's domain instructions, mark the source processed, create a session, and log the change with `cogforge`.
