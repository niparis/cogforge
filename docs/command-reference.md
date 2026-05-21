# cogforge Command Reference Draft

## Conventions

`cogforge` is an agent-facing CLI. Commands should be non-interactive by default.

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

### `cogforge config validate`

Validate `llm_wiki/sources.yaml`.

```bash
cogforge config validate
```

Output should include:

- Config path.
- Schema version.
- Source counts by connector.
- Invalid entries.
- Suggested fixes.

### `cogforge config show`

Render resolved config after defaults.

```bash
cogforge config show
```

Useful for agents before choosing sync commands.

## `cogforge status`

Show pipeline status.

```bash
cogforge status
```

Output should include:

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
```

Options:

```text
--source-id ID       Sync one configured Substack source.
--all               Sync all enabled Substack sources.
--max N             Stop after N new or updated posts.
--refresh-index     Rebuild discovered post index.
--cookies-txt PATH  Override configured cookies file.
--skip-pdfs         Do not download linked PDFs.
```

Behavior:

- Writes source packages to `inbox/substack`.
- Preserves original HTML.
- Downloads local images.
- Creates or updates source YAML state.
- Emits a structured report.

### `cogforge sync youtube`

Sync YouTube playlists or fetch a single video transcript.

```bash
cogforge sync youtube --source-id miniature-painting
```

Options:

```text
--source-id ID      Sync one configured YouTube source.
--all              Sync all enabled YouTube sources.
--url URL          Fetch a single video URL outside playlist config.
--video-id ID      Fetch a single video ID.
--max N            Stop after N new transcripts.
--include-failed   Retry previously failed items.
```

Behavior:

- Fetches video metadata with `yt-dlp`.
- Fetches transcripts with `youtube-transcript-api`.
- Writes Markdown transcript packages to `inbox/youtube`.
- Marks no-transcript or unavailable videos as `excluded` when appropriate.
- Creates or updates source YAML state.

### `cogforge sync apple-notes`

Export Apple Notes from configured root notes.

```bash
cogforge sync apple-notes --source-id trading-menu
```

Options:

```text
--source-id ID     Export one configured Apple Notes root.
--all             Export all enabled Apple Notes roots.
--root-title TEXT Override configured root note title.
--max-depth N     Limit graph traversal depth.
```

Behavior:

- Reads Apple Notes data through the existing macOS database and AppleScript strategy.
- Exports each note independently.
- Copies PDF attachments.
- Writes source packages to `inbox/apple-notes`.
- Creates or updates source YAML state.

## `cogforge inbox`

Inspect and manage sources waiting for LLM compilation.

### `cogforge inbox list`

List inbox sources.

```bash
cogforge inbox list
```

Options:

```text
--connector substack|youtube|apple-notes|manual
--pageindex pending|complete|failed
--failed
```

### `cogforge inbox show`

Show one source state and package paths.

```bash
cogforge inbox show youtube:TIYnaNaZq4s
```

### `cogforge inbox prepare`

Prepare one or more inbox sources for LLM compilation.

```bash
cogforge inbox prepare youtube:TIYnaNaZq4s
```

Behavior:

- Validates source package.
- Detects long-document status.
- Runs PageIndex when required unless disabled.
- Emits paths the agent should read.

Options:

```text
--no-pageindex       Do not run PageIndex even if required.
--force-pageindex    Re-run PageIndex.
--char-threshold N   Override text long-document threshold.
--page-threshold N   Override page threshold.
```

### `cogforge inbox mark-processed`

Record that an agent processed a source and move its package to raw.

```bash
cogforge inbox mark-processed youtube:TIYnaNaZq4s --session SESSION_PATH
```

Options:

```text
--session PATH       Session file associated with the processing run.
--history-note TEXT  Short reason for history log.
--contribution PATH  Optional LLM-generated contribution report.
```

Behavior:

- Moves source package from inbox to raw.
- Updates source state to `processed`.
- Appends history log entry.
- Updates or references session bookkeeping.

The command name is draft. Alternatives include `archive`, `accept`, or `promote`.

### `cogforge inbox exclude`

Exclude a source from the pipeline.

```bash
cogforge inbox exclude youtube:VIDEO_ID --reason unavailable
```

Reasons:

```text
duplicate
irrelevant
unavailable
user_rejected
unsupported
```

## `cogforge pageindex`

Manage PageIndex artifacts.

### `cogforge pageindex detect`

Detect whether sources require PageIndex.

```bash
cogforge pageindex detect youtube:TIYnaNaZq4s
```

### `cogforge pageindex run`

Run PageIndex for one source.

```bash
cogforge pageindex run substack:paperswithbacktest/2026-05-10-jim-simons-the-mathematician-who
```

Options:

```text
--force             Re-run even when artifacts exist.
--page-threshold N  Override page threshold.
--char-threshold N  Override character threshold.
```

### `cogforge pageindex show`

Show artifact paths and summary metadata for one source.

```bash
cogforge pageindex show SOURCE_ID
```

## `cogforge state`

Inspect and repair source state files.

### `cogforge state show`

Show source state.

```bash
cogforge state show SOURCE_ID
```

### `cogforge state validate`

Validate source state consistency.

```bash
cogforge state validate
```

Checks:

- Duplicate source IDs.
- Missing source package paths.
- Missing PageIndex artifacts.
- Impossible lifecycle/path combinations.
- Invalid status values.

### `cogforge state repair`

Repair safe state drift.

```bash
cogforge state repair --dry-run
```

Potential safe repairs:

- Recompute missing hashes.
- Restore missing report references.
- Mark missing package paths as validation errors.

No destructive repair should run without explicit flags.

## `cogforge wiki`

Deterministic wiki bookkeeping helpers. These commands do not perform semantic compilation.

### `cogforge wiki log`

Append a history log entry.

```bash
cogforge wiki log --message "Processed source youtube:TIYnaNaZq4s" --session PATH
```

### `cogforge wiki session close`

Create or update a session file from a structured report.

```bash
cogforge wiki session close --report PATH
```

### `cogforge wiki validate`

Validate wiki structure.

```bash
cogforge wiki validate
```

Initial checks:

- Required folders.
- Index files.
- Broken wikilinks.
- Missing indexed pages.
- Source state path consistency.

## `cogforge reports`

Inspect canonical run reports.

### `cogforge reports list`

List recent reports.

```bash
cogforge reports list
```

### `cogforge reports show`

Show a report.

```bash
cogforge reports show RUN_ID --format markdown
```

### `cogforge reports render`

Render a stored YAML report to JSON or Markdown.

```bash
cogforge reports render PATH --format markdown
```

## Draft Exit Codes

```text
0 success
1 command error or invalid arguments
2 validation failed
3 partial success with failed source items
4 external dependency failure
5 state conflict
```

## Agent Usage Pattern

A typical agent workflow:

```bash
cogforge sync youtube --source-id miniature-painting
cogforge inbox list
cogforge inbox prepare youtube:VIDEO_ID
```

The agent then reads the source package and PageIndex artifacts, updates wiki pages itself, then calls:

```bash
cogforge inbox mark-processed youtube:VIDEO_ID --session llm_wiki/history/sessions/...
```

The CLI handles deterministic bookkeeping. The LLM handles semantic compilation and contradiction reporting.
