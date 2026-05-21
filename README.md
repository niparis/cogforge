# Cogforge

Cogforge is the CLI/tooling layer for maintaining structured LLM-backed knowledge bases.

It is intentionally separate from the knowledge-base repositories it manages.

## Development

```bash
uv run pytest
uv run cogforge --help
```

## Initialize a Knowledge Base

```bash
cogforge init /path/to/new-kb
```

That command creates a managed `llm_wiki/` tree plus the KB-facing `AGENTS.md` scaffold. The `AGENTS.md` in this repository is only for developing Cogforge itself.
