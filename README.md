# Cogforge

Cogforge is an agent-facing CLI for maintaining structured LLM-backed knowledge bases. It is intentionally separate from the knowledge-base repositories it manages.

The CLI treats the wiki as a pipeline:

1. **Sync** external sources into `inbox/`
2. **Inspect** what is waiting for processing
3. **Prepare** long documents with PageIndex
4. **Process** sources by compiling them into wiki pages
5. **Bookkeep** sessions, logs, and validation

All commands default to JSON output for machine consumption. Use `--format markdown` for human-readable output.

## Installation

```bash
pip install cogforge
```

## Quick Start

```bash
# Initialize a new knowledge base
cogforge init my-kb
cd my-kb

# Configure sources in sources.yaml, then sync
cogforge sync youtube --all
cogforge sync substack --all

# See what is waiting
cogforge status

# Drain the inbox by spawning agent sessions
cogforge inbox run --max-items 5
```

## Global Options

Every command accepts these flags:

| Option | Description |
|--------|-------------|
| `--wiki-root PATH` | Path to the knowledge base. Defaults to `./llm_wiki` or walks up to find one. |
| `--config PATH` | Override `sources.yaml` location. |
| `--format json\|markdown` | Output format. Defaults to `json`. |
| `--dry-run` | Compute changes without mutating files. |
| `--verbose` | Include debug details. |
| `--quiet` | Suppress non-report output. |

## Operator Commands

These commands are for the human operator or orchestrator. Commands used by skills are documented in the [Command Reference](docs/command-reference.md).

### Setup

#### `cogforge init [TARGET]`

Scaffold a new knowledge-base repository. Creates `sources.yaml`, `.env`, `llm_wiki/` tree, and `AGENTS.md`. Auto-detects installed `claude`/`opencode` CLIs and writes a sensible `agents:` block.

### Sync

Synchronize external sources into `llm_wiki/inbox`.

```bash
cogforge sync substack --all
cogforge sync youtube --source-id miniature-painting
cogforge sync apple-notes --all
```

### Batch Processing

#### `cogforge inbox run [OPTIONS]`

Drain the inbox by spawning external agent sessions, one item at a time. Uses the `agents:` fallback list from `sources.yaml`. Each iteration spawns a fresh `claude` or `opencode` subprocess. If an agent hits a rate limit, the runner advances to the next agent and retries.

```bash
cogforge inbox run --max-items 5 --delay 2.0
```

### Manual Triage

#### `cogforge inbox exclude SOURCE_ID --reason REASON`

Exclude a source from the pipeline. Reasons: `duplicate`, `irrelevant`, `unavailable`, `user_rejected`, `unsupported`.

### PageIndex (Manual)

PageIndex runs automatically during `inbox prepare`. These commands are for manual rebuilds and debugging:

```bash
cogforge pageindex detect              # scan all sources for long documents
cogforge pageindex run SOURCE_ID       # rebuild artifact for one source
```

### Wiki Validation

```bash
cogforge wiki validate                 # check required directories and indexes
```

### Migration

```bash
cogforge migrate youtube-transcripts   # one-time legacy migration
```

## Source Lifecycle

Sources move through these states:

| Status | Meaning |
|--------|---------|
| `inbox` | Source package exists and is waiting for LLM compilation |
| `processed` | Source has been compiled into wiki pages and moved to `raw/` |
| `failed` | A CLI operation failed; includes error phase and retryability |
| `excluded` | Intentionally out of pipeline; requires a reason |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Command error or invalid arguments |
| 2 | Validation failed |
| 3 | Partial success (some sources failed) |

## Development

```bash
uv run pytest
uv run cogforge --help
```

## Release

- Bump `pyproject.toml` version
- Commit
- `git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`
- GitHub Actions auto-drafts a release; publish it to trigger PyPI publish
