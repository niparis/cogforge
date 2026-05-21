# Cogforge Agent Instructions

You are working on Cogforge, the CLI/tooling repository.

Cogforge is code, not a knowledge base. Do not apply knowledge-base agent instructions from a managed wiki repository while editing this repo.

## Boundaries

- Product, architecture, packaging, and migration decisions belong in this repository, not in a user's `llm_wiki/wiki/decisions`.
- Knowledge-base sessions, domain context, inbox processing logs, and wiki bookkeeping belong only to the managed KB repository.
- Do not write to a managed KB unless the user explicitly asks you to operate on that KB.
- Do not run `cogforge wiki session-new` or `cogforge wiki log` merely because you changed Cogforge code.

## Project Shape

- Python package: `src/cogforge`
- CLI command: `cogforge`
- Tests: `tests`
- Documentation: `docs`

The managed wiki data layout may still contain `.llmkb` for backward compatibility. Treat that as a KB schema detail, not as the package name.

## Common Commands

```bash
uv run pytest
uv run cogforge --help
uv run cogforge status --wiki-root /path/to/llm_wiki
```

## Migration Rule

Keep the tool repo and KB repos strictly separate:

- `cogforge/AGENTS.md` tells agents how to code the tool.
- The KB `AGENTS.md` tells agents how to maintain that KB.
- The KB `AGENTS.md` template lives in Cogforge only as generated user-facing project scaffolding.
