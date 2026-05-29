# Sprint 10: Inbox Pipeline Hardening

## Purpose

Make `cogforge inbox run` fully deterministic and auditable by:

1. Forcing `inbox prepare` before spawning every agent, so the agent never skips or forgets preprocessing.
2. Adding structured file logging to `.llmkb/logs/` so every CLI invocation leaves a durable trace.

References:

- [Product specification](../../specs/PRODUCT.md)
- [Command reference](../../architecture/command-reference.md)
- [AGENTS.md](../../../AGENTS.md)

## Context

### Current Problems

1. **`inbox run` trusts spawned agents to call `inbox prepare`**
   Agents sometimes skip `prepare` (see item 2 in a real run: no `prepare` call, only `inbox show`). For short sources this is harmless, but for PDFs or long documents it means enrichment and PageIndex are missed.

2. **`inbox run` reports are ephemeral**
   The `LoopReport` produced by `run_loop()` is emitted to stdout and never persisted. If the user closes the terminal, the full run history (agents attempted, rate-limit events, per-item details) is lost.

3. **No central log of CLI invocations**
   Side effects are scattered: state files, session files, history log entries. There is no single place to answer "what did cogforge do yesterday?"

### Existing Sprint(s) This Builds On

- Sprint 8 introduced `inbox run` and the agent fallback mechanism.
- Sprint 9 added PDF enrichment.

## Workstream 1: Structured File Logging

### Current State

- `loguru` is already a dependency and logs to stderr.
- The global `--report PATH` option is parsed but not used by `inbox run`.
- No file logging is configured.

### Desired State

Every CLI invocation writes a structured JSON log line to `.llmkb/logs/YYYY-MM-DD.log`:

```json
{
  "timestamp": "2026-05-29T12:34:56.789Z",
  "command": "inbox run",
  "args": {"max_items": 2, "delay": 2.0},
  "result": "max_items_reached",
  "items_processed": 2,
  "items_attempted": 2,
  "rate_limit_events": 0,
  "failures": 0,
  "duration_ms": 45230,
  "wiki_root": "/Users/nicolasparis/code/llm-kb/llm_wiki"
}
```

### Implementation Steps

1. **Add `logs` to `Paths`**
   - `paths.py`: add `@property def logs(self) -> Path: return self.root / ".llmkb" / "logs"`
   - `paths.ensure()`: add `self.logs` to the mkdir list

2. **Configure loguru file sink at CLI startup**
   - In `CogforgeGroup.parse_args`, after resolving `paths`:
     ```python
     from loguru import logger
     log_file = paths.logs / f"{datetime.now():%Y-%m-%d}.log"
     logger.add(
         str(log_file),
         level="INFO",
         format="{time:YYYY-MM-DDTHH:mm:ss.SSS}  {message}",
         rotation=None,  # daily rotation handled by filename
     )
     ```
   - This makes `logger.info(...)` write to both stderr and the file.

3. **Add `log_command_result` helper**
   - In `cli.py`, add a small function that each command calls before exiting:
     ```python
     def _log_result(cmd_name: str, result: dict[str, Any], duration_ms: int) -> None:
         logger.info(json.dumps({
             "command": cmd_name,
             "result": result,
             "duration_ms": duration_ms,
         }))
     ```

4. **Wire logging into major commands**
   - `inbox run`: log the full `LoopReport.to_dict()` plus duration.
   - `sync substack/youtube/apple-notes`: log `SyncResult` summary.
   - `config validate/show`: lightweight, skip or log minimal.
   - `status`: skip (too frequent, no mutation).

5. **Update `inbox run` to also respect `--report PATH`**
   - If `cli_ctx["report_path"]` is set, additionally write the JSON payload there.
   - This makes `--report` useful for CI or automation.

## Workstream 2: Inbox Prepare Refactor

### Current State

- `inbox prepare` is a Click command with all logic inline.
- `inbox run` spawns agents and trusts them to call `prepare`.
- Agents sometimes skip it, especially for short non-PDF sources.

### Desired State

`inbox run` is the deterministic orchestrator:

1. Select next inbox source.
2. **Run `prepare_inbox_source(...)` internally** — no agent involvement.
3. If prepare fails, log the failure and skip to next source (or abort on critical error).
4. Spawn agent with prompt: *"Source has already been prepared. Read it and compile it into the wiki."*
5. Agent calls `mark-processed` and `wiki log` as before.
6. `inbox run` verifies inbox count decreased.

### Implementation Steps

1. **Extract pure function from `inbox prepare` command**
   - Move the core logic (package validation, PDF enrichment, long-document detection, PageIndex) into a new module, e.g. `src/cogforge/prepare.py`.
   - Define `PrepareResult` dataclass:
     ```python
     @dataclass
     class PrepareResult:
         source_id: str
         package_valid: bool
         package_issues: list[str]
         pdf_enrich_status: str | None  # skipped | success | failed
         long_document_detected: bool
         pageindex_status: str | None  # skipped | complete | failed
         pageindex_artifact_path: str | None
     ```
   - Define `prepare_inbox_source(source_id, paths, config, **options) -> PrepareResult`.

2. **Keep `inbox prepare` CLI command**
   - Make it a thin wrapper around `prepare_inbox_source(...)`.
   - Same options, same output format.

3. **Update `inbox run` to call prepare internally**
   - In `inbox_runner.py`, after selecting `next_source`:
     ```python
     prepare_result = prepare_inbox_source(
         next_source.id, paths, config,
         no_pageindex=False,  # let defaults apply
         no_pdf_enrich=False,
     )
     # Log prepare result
     logger.info(json.dumps({
         "phase": "prepare",
         "source_id": next_source.id,
         "package_valid": prepare_result.package_valid,
         "long_document": prepare_result.long_document_detected,
     }))
     ```
   - If `not prepare_result.package_valid`, record failure and continue to next source.

4. **Update agent prompt template**
   - Remove: *"Run `inbox prepare` before anything else"*
   - Replace with: *"The source has been pre-validated and prepared by cogforge. Read the source package and compile it into the wiki."*
   - Add: *"Estimated chars: {estimated_chars}. PageIndex required: {pageindex_required}."*

5. **Include prepare result in `LoopReport`**
   - Add `prepare_result: PrepareResult | None` field to `LoopReport`.
   - Include it in `to_dict()` so the final report shows per-item preparation status.

6. **Update `process-inbox/SKILL.md`**
   - Remove the "Run `inbox prepare`" instruction (it's no longer the agent's job).
   - Add: *"The CLI has already prepared the source. Check the prepare output for PageIndex artifacts if the source is long."*

## Changes to Existing Commands

| Command | Change |
|---------|--------|
| `inbox run` | Forces `prepare_inbox_source()` before each agent spawn; logs to file |
| `inbox prepare` | Becomes thin wrapper around `prepare_inbox_source()` |
| All commands | If they produce a report, also log it to `.llmkb/logs/` |

## Files to Create / Modify

- `src/cogforge/paths.py` — add `logs` property
- `src/cogforge/prepare.py` — new module with `PrepareResult` and `prepare_inbox_source()`
- `src/cogforge/cli.py` — wire logging, refactor `inbox_prepare` command
- `src/cogforge/inbox_runner.py` — call `prepare_inbox_source()`, update prompt, include result in report
- `src/cogforge/reports.py` — optionally update `Report` schema if needed
- `tests/` — add tests for `prepare_inbox_source()`, logging, and refactored `inbox run`
- Skills: `process-inbox/SKILL.md` — remove prepare instruction

## Implementation Order

1. **Add `logs` to `Paths`** + `paths.ensure()`
2. **Configure loguru file sink** in `CogforgeGroup.parse_args`
3. **Extract `prepare_inbox_source()`** into `src/cogforge/prepare.py`
4. **Refactor `inbox prepare` command** to use `prepare_inbox_source()`
5. **Update `inbox run`** to call `prepare_inbox_source()` before spawning agent
6. **Update agent prompt** in `inbox_runner.py`
7. **Add `_log_result` helper** and wire into major commands
8. **Write tests** for new prepare module and logging
9. **Update `process-inbox/SKILL.md`**
10. **Commit all changes**

## Acceptance Criteria

- [ ] `cogforge inbox prepare <source_id>` still works identically for PDF and non-PDF sources
- [ ] `cogforge inbox run` internally calls prepare before every agent spawn
- [ ] Short sources (e.g. Apple Notes) produce a prepare result showing `long_document: false`
- [ ] PDF sources trigger PDF enrichment during the forced prepare
- [ ] Every `inbox run` invocation appends a JSON log line to `.llmkb/logs/YYYY-MM-DD.log`
- [ ] The log line contains command name, args, result, duration, and items processed
- [ ] The spawned agent prompt no longer tells the agent to run `inbox prepare`
- [ ] `process-inbox/SKILL.md` updated to reflect that prepare is CLI-driven
- [ ] All existing 275+ tests still pass
- [ ] New tests cover `prepare_inbox_source()` and logging behavior
