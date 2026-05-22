# cogforge Command Reference

> **Key:** 🤖 = executed by skills (agents follow skill instructions to invoke these). Commands without the badge are for operators or orchestrators.

## Conventions

`cogforge` is an agent-facing CLI. Commands are non-interactive by default.

Default output format:

```text
json
```

Optional Markdown rendering:

```bash
cogforge <command> --format markdown
```

Global options:

```text
--wiki-root PATH        Path to llm_wiki. Defaults to ./llm_wiki when run from repo root.
--config PATH           Override source config path. Defaults to llm_wiki/sources.yaml.
--format json|markdown  Output rendering. Defaults to json.
--report PATH           Persist canonical report to a specific path.
--dry-run               Compute intended changes without mutating files.
--verbose               Include debug details.
--quiet                 Suppress non-report chatter.
```

## `cogforge config`

### 🤖 `cogforge config validate`

Validate `sources.yaml` and report schema errors, missing env vars, and source counts.

```bash
cogforge config validate
```

Output includes:

- Config path.
- Schema version.
- Source counts by connector.
- Invalid entries.
- Missing env var warnings (e.g. `OPENROUTER_API_KEY`).

### `cogforge config show`

Render resolved config after defaults.

```bash
cogforge config show
```

## 🤖 `cogforge status`

Show pipeline status.

```bash
cogforge status
```

Output includes:

- Source counts by status.
- Source counts by connector.
- Failed sources.
- Sources waiting in inbox.
- Sources with PageIndex pending or failed.
- Recent reports.

## `cogforge sync`

Synchronize configured external sources into `llm_wiki/inbox`.

### `cogforge sync substack`

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

### `cogforge sync youtube`

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

### `cogforge sync apple-notes`

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

## `cogforge inbox`

Inspect and manage sources waiting for LLM compilation.

### 🤖 `cogforge inbox list`

List inbox sources (pending by default).

```bash
cogforge inbox list --status inbox          # default: pending only
cogforge inbox list --status all            # all sources
cogforge inbox list --failed                # failed only
cogforge inbox list --connector youtube     # filter by connector
cogforge inbox list --limit 5               # cap results
```

### 🤖 `cogforge inbox show`

Show one source state and package paths.

```bash
cogforge inbox show youtube:TIYnaNaZq4s
```

### 🤖 `cogforge inbox prepare`

Prepare a source for LLM compilation. Validates the package, detects long documents, and runs PageIndex when needed. For PDF sources, also runs PDF enrichment (VLM visual summaries, table extraction).

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

### 🤖 `cogforge inbox mark-processed`

Record that an agent processed a source and move its package from `inbox/` to `raw/`.

```bash
cogforge inbox mark-processed youtube:TIYnaNaZq4s --history-note "Added trading concepts"
```

| Option | Description |
|--------|-------------|
| `--session PATH` | Associate with a session file |
| `--history-note TEXT` | Short reason for history log |

### `cogforge inbox exclude`

Exclude a source from the pipeline with a reason.

```bash
cogforge inbox exclude youtube:VIDEO_ID --reason irrelevant
```

Reasons: `duplicate`, `irrelevant`, `unavailable`, `user_rejected`, `unsupported`.

### `cogforge inbox run`

Drain the inbox by spawning external agent sessions, one item at a time. Uses the `agents:` fallback list from `sources.yaml`. Each iteration spawns a fresh `claude` or `opencode` subprocess that processes exactly one source. If an agent hits a rate limit, the runner advances to the next agent and retries.

```bash
cogforge inbox run --max-items 5 --delay 2.0
```

| Option | Description |
|--------|-------------|
| `--max-items N` | Stop after N items |
| `--delay SECONDS` | Sleep between items |
| `--cli claude\|opencode` | Restrict to one CLI |

## `cogforge pageindex`

Manage PageIndex artifacts for long documents.

> **Note:** `inbox prepare` calls `pageindex run` internally when a source exceeds length thresholds. Skills use `pageindex show` to read structured artifacts. The `pageindex` CLI commands are exposed for manual use and debugging.

### `cogforge pageindex detect`

Detect whether sources require PageIndex based on document length. Without `SOURCE_ID`, scans all sources.

```bash
cogforge pageindex detect
cogforge pageindex detect youtube:VIDEO_ID
```

### `cogforge pageindex run`

Run PageIndex for one source, producing a structured document tree artifact.

```bash
cogforge pageindex run SOURCE_ID --force
```

| Option | Description |
|--------|-------------|
| `--force` | Re-run even when artifacts exist |
| `--char-threshold N` | Override threshold |
| `--page-threshold N` | Override threshold |

### 🤖 `cogforge pageindex show`

Show PageIndex artifact paths and summary metadata for one source.

```bash
cogforge pageindex show SOURCE_ID
```

## `cogforge state`

Inspect and repair source state files.

### 🤖 `cogforge state show`

Show source state for one source, or list all source IDs if omitted.

```bash
cogforge state show youtube:TIYnaNaZq4s
cogforge state show                           # list all IDs
```

### 🤖 `cogforge state validate`

Validate all source state files for consistency: duplicate IDs, invalid statuses, missing paths.

```bash
cogforge state validate
```

### 🤖 `cogforge state repair`

Repair safe state drift: recompute missing hashes, restore missing references.

```bash
cogforge state repair --dry-run
cogforge state repair
```

## `cogforge wiki`

Deterministic wiki bookkeeping helpers.

### 🤖 `cogforge wiki log`

Append a timestamped entry to `history/YYYY-MM-DD.log`.

```bash
cogforge wiki log --message "Processed source youtube:VIDEO_ID"
```

### 🤖 `cogforge wiki session-new`

Create a session YAML for tracking agent work.

```bash
cogforge wiki session-new \
  --summary "Processed trading sources" \
  --domain trading \
  --files-changed "wiki/concepts/momentum.md,wiki/decisions/backtesting.md" \
  --decisions "Use RSI framework,Adopt walk-forward testing" \
  --next-steps "Implement portfolio constraints,Write synthesis"
```

### `cogforge wiki session-close`

Create a session from a structured run report.

```bash
cogforge wiki session-close --report PATH
```

### `cogforge wiki validate`

Validate wiki structure: required directories and index files.

```bash
cogforge wiki validate
```

## `cogforge reports`

Inspect canonical run reports.

### 🤖 `cogforge reports list`

List recent run reports from `.llmkb/reports/`.

```bash
cogforge reports list
```

### 🤖 `cogforge reports show`

Show a stored report by run ID.

```bash
cogforge reports show RUN_ID --format markdown
```

### `cogforge reports render`

Render a stored YAML report to JSON or Markdown.

```bash
cogforge reports render PATH --format markdown
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Command error or invalid arguments |
| 2 | Validation failed |
| 3 | Partial success (some sources failed) |

## Typical Agent Workflow

An agent processes one source end-to-end:

```bash
cogforge status                                   # overview
cogforge inbox list --limit 1                     # next pending source
cogforge inbox show <source_id>                   # inspect source
cogforge inbox prepare <source_id>                # enrich + pageindex
cogforge pageindex show <source_id>               # read structured artifact
# (agent reads source and edits wiki pages)
cogforge inbox mark-processed <source_id> --history-note "Added concepts"
cogforge wiki session-new --summary "..." --files-changed "..."
cogforge wiki log --message "Processed <source_id>"
```

Or drain the inbox automatically:

```bash
cogforge inbox run --max-items 5
```

The CLI handles deterministic bookkeeping. The LLM handles semantic compilation.
