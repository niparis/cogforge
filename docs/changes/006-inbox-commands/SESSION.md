# Sprint 2 Follow-up: Inbox CLI Commands

## Date
2026-05-14

## Summary
Implemented four new `cogforge inbox` commands in `src/cogforge/cli.py`:

### `cogforge inbox list`
- Lists all source states from `.llmkb/state/sources/`
- Filters: `--connector`, `--pageindex` (pending/complete/failed), `--failed`
- JSON output: array of source objects with id, connector, status, origin, content, pageindex, paths, errors
- Markdown output: formatted list with status icons

### `cogforge inbox show <source_id>`
- Shows full detail for one source: connector, status, document_type, origin, content hashes, paths, pageindex, excluded info, last error, last sync
- JSON or markdown output

### `cogforge inbox mark-processed <source_id>`
- Moves source package from `inbox/<connector>/<folder>` to `raw/<connector>/<folder>`
- Updates state status to `processed`, sets `paths.raw`
- Appends history log entry with optional `--history-note`
- Supports `--dry-run` to preview without changes
- Supports `--session` (reserved for future use)

### `cogforge inbox exclude <source_id>`
- Marks source as `excluded` with required `--reason` (duplicate, irrelevant, unavailable, user_rejected, unsupported)
- Optional `--note` for additional context
- Supports `--dry-run`

## Changes
- `src/cogforge/cli.py`: Added `shutil`, `datetime`, `timezone` imports; added `inbox_group` command group with 4 subcommands (283 lines added, 3 lines removed for import additions)

## Testing
- All 99 existing tests pass
- 10 custom integration tests verified: empty list, markdown format, filtering, show, mark-processed (with move), dry-run modes, exclude, no-prompt behavior

## Commit
- `a04983f feat(inbox): add inbox list, show, mark-processed, exclude commands`