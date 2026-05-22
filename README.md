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
uv tool install cogforge
```
later

```bash
uv tool upgrade cogforge
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
cogforge inbox list

# Prepare a source (detects long documents, runs PageIndex)
cogforge inbox prepare youtube:VIDEO_ID

# After you have compiled the source into wiki pages, mark it done
cogforge inbox mark-processed youtube:VIDEO_ID --history-note "Added trading concepts"

# Validate wiki structure
cogforge wiki validate
```

## Global Options

Every command accepts these flags:

| Option | Description |
|--------|-------------|
| `--wiki-root PATH` | Path to the knowledge base. Defaults to `./llm_wiki` or walks up to find one. |
| `--config PATH` | Override `sources.yaml` location. Defaults to `<wiki-root>/sources.yaml`, then falls back to `<CWD>/sources.yaml`. |
| `--format json\|markdown` | Output format. Defaults to `json`. |
| `--dry-run` | Compute changes without mutating files. |
| `--verbose` | Include debug details. |
| `--quiet` | Suppress non-report output. |

## Command Reference

Commands are organized by pipeline phase.

---

### Setup

#### `cogforge init [TARGET]`

Scaffold a new knowledge-base repository at `TARGET` (default: current directory).

Creates:
- `sources.yaml` — configuration for sources, agents, and defaults
- `.env` — placeholder for API keys
- `llm_wiki/` — folder structure (inbox, raw, wiki, history, .llmkb)
- `AGENTS.md` and `README.md` — knowledge-base agent instructions

If `claude` or `opencode` CLIs are installed on the machine, `init` auto-detects them and writes a sensible `agents:` block into `sources.yaml`.

#### `cogforge config validate`

Validate `sources.yaml` and report schema errors, missing env vars, and source counts.

#### `cogforge config show`

Render the resolved configuration after applying defaults.

---

### Sync

Synchronize external sources into `llm_wiki/inbox`. Each sync creates or updates source YAML state files under `.llmkb/state/sources/`.

#### `cogforge sync substack [OPTIONS]`

Sync Substack publications.

```bash
cogforge sync substack --source-id paperswithbacktest
cogforge sync substack --all
```

| Option | Description |
|--------|-------------|
| `--source-id ID` | Sync one configured source |
| `--all` | Sync all enabled Substack sources |
| `--max N` | Stop after N new posts |
| `--refresh-index` | Rebuild post discovery index |
| `--cookies-txt PATH` | Override cookies file for auth |
| `--skip-pdfs` | Do not download linked PDFs |
| `--force` | Re-fetch posts already on disk |

#### `cogforge sync youtube [OPTIONS]`

Sync YouTube playlists or single videos.

```bash
cogforge sync youtube --source-id miniature-painting
cogforge sync youtube --url https://youtube.com/watch?v=...
```

| Option | Description |
|--------|-------------|
| `--source-id ID` | Sync one configured playlist |
| `--all` | Sync all enabled YouTube sources |
| `--url URL` | Fetch a single video URL |
| `--video-id ID` | Fetch a single video ID |
| `--max N` | Stop after N new transcripts |
| `--include-failed` | Retry previously failed items |

#### `cogforge sync apple-notes [OPTIONS]`

Export Apple Notes from configured root notes.

```bash
cogforge sync apple-notes --source-id trading-menu
cogforge sync apple-notes --all
```

| Option | Description |
|--------|-------------|
| `--source-id ID` | Export one configured root |
| `--all` | Export all enabled roots |
| `--root-title TEXT` | Override root note title |
| `--max-depth N` | Limit graph traversal depth |

---

### Inspect

#### `cogforge status`

Show pipeline status: source counts by status and connector, failed sources, inbox backlog, pending PageIndex jobs, and recent reports.

#### `cogforge inbox list [OPTIONS]`

List sources waiting for LLM compilation.

```bash
cogforge inbox list --status inbox          # default: pending sources only
cogforge inbox list --status all            # all sources regardless of status
cogforge inbox list --failed                # failed sources only
cogforge inbox list --connector youtube     # filter by connector
cogforge inbox list --limit 5               # cap results
```

#### `cogforge inbox show SOURCE_ID`

Show full state, paths, and metadata for one source.

---

### Prepare

#### `cogforge inbox prepare SOURCE_ID [OPTIONS]`

Prepare a source for LLM compilation. Validates the package, detects long documents, runs PageIndex when needed, and (for PDF sources) runs PDF enrichment.

```bash
cogforge inbox prepare youtube:VIDEO_ID
cogforge inbox prepare substack:paperswithbacktest/2026-05-10-post --force-pageindex
```

| Option | Description |
|--------|-------------|
| `--no-pageindex` | Skip PageIndex even if required |
| `--force-pageindex` | Re-run PageIndex |
| `--char-threshold N` | Override character threshold |
| `--page-threshold N` | Override page threshold |
| `--no-pdf-enrich` | Skip PDF preprocessing |
| `--force-pdf-enrich` | Re-run PDF enrichment |
| `--allow-missing-vlm-key` | Proceed text-only if VLM key is missing |

#### `cogforge pageindex detect [SOURCE_ID]`

Detect whether sources require PageIndex based on document length. Without `SOURCE_ID`, scans all sources.

#### `cogforge pageindex run SOURCE_ID [OPTIONS]`

Run PageIndex for one source, producing a structured document tree artifact.

| Option | Description |
|--------|-------------|
| `--force` | Re-run even when artifacts exist |
| `--char-threshold N` | Override threshold |
| `--page-threshold N` | Override threshold |

#### `cogforge pageindex show SOURCE_ID`

Show PageIndex artifact paths and summary metadata.

---

### Process

#### `cogforge inbox mark-processed SOURCE_ID [OPTIONS]`

Record that an agent processed a source and move its package from `inbox/` to `raw/`.

```bash
cogforge inbox mark-processed youtube:VIDEO_ID --history-note "Added concepts"
```

| Option | Description |
|--------|-------------|
| `--session PATH` | Associate with a session file |
| `--history-note TEXT` | Short reason for the history log |

#### `cogforge inbox exclude SOURCE_ID [OPTIONS]`

Exclude a source from the pipeline with a reason.

```bash
cogforge inbox exclude youtube:VIDEO_ID --reason irrelevant
```

Reasons: `duplicate`, `irrelevant`, `unavailable`, `user_rejected`, `unsupported`.

#### `cogforge inbox run [OPTIONS]`

Drain the inbox by spawning external agent sessions, one item at a time. Uses the `agents:` fallback list from `sources.yaml`. Each iteration spawns a fresh `claude` or `opencode` subprocess. If an agent hits a rate limit, the runner advances to the next agent and retries.

```bash
cogforge inbox run --max-items 5 --delay 2.0
```

| Option | Description |
|--------|-------------|
| `--max-items N` | Stop after N items |
| `--delay SECONDS` | Sleep between items |
| `--cli claude\|opencode` | Restrict to one CLI |

---

### Bookkeeping

#### `cogforge wiki validate`

Validate wiki structure: checks required directories and index files.

#### `cogforge wiki log --message "TEXT"`

Append a timestamped entry to `history/YYYY-MM-DD.log`.

#### `cogforge wiki session-new [OPTIONS]`

Create a session YAML for tracking agent work.

```bash
cogforge wiki session-new \
  --summary "Processed trading sources" \
  --domain trading \
  --files-changed "wiki/concepts/momentum.md,wiki/decisions/backtesting.md" \
  --decisions "Use RSI framework,Adopt walk-forward testing" \
  --next-steps "Implement portfolio constraints,Write synthesis"
```

#### `cogforge wiki session-close --report PATH`

Create a session from a structured run report.

---

### Debug and Repair

#### `cogforge state show [SOURCE_ID]`

Show source state for one source, or list all source IDs if omitted.

#### `cogforge state validate`

Validate all source state files for consistency: duplicate IDs, invalid statuses, missing paths.

#### `cogforge state repair [--dry-run]`

Repair safe state drift: recompute missing hashes, restore missing references.

#### `cogforge reports list`

List recent run reports from `.llmkb/reports/`.

#### `cogforge reports show RUN_ID`

Show a stored report.

#### `cogforge reports render PATH`

Render a stored YAML report to JSON or Markdown.

---

### Migration

#### `cogforge migrate youtube-transcripts`

One-time migration of legacy `raw/transcripts/*.md` files to the new source-state model.

---

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
uv run cogforge status --wiki-root /path/to/llm_wiki
```

## Release

- Bump `pyproject.toml` version
- Commit
- `git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`
- GitHub Actions auto-drafts a release; publish it to trigger PyPI publish
