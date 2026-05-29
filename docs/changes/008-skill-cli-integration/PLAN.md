# Sprint 8: Skill-to-CLI Integration & Subagent Inbox Processing

## Purpose

Replace all manual bookkeeping in the agent skill definitions with `cogforge` CLI commands, and refactor `process-inbox` to use isolated subagents for source-by-source processing to avoid context pollution.

References:

- [Product specification](../../specs/PRODUCT.md)
- [Command reference](../../architecture/command-reference.md)
- [AGENTS.md](../../../AGENTS.md)
- Skills: `.opencode/skills/*/SKILL.md`

## Context

All CLI commands are now implemented. Skills still instruct agents to do manual file operations (append to `history.log`, create session YAML by hand, run bash pipelines for YouTube). This sprint replaces those instructions with `cogforge` CLI calls and introduces a subagent-based inbox processing loop.

## Planning Principles

- The CLI owns all deterministic bookkeeping. Skills describe intent and parameter choices, not shell snippets.
- Inbox sources are processed one at a time in fresh subagent contexts.
- Skills are updated in-place. No new skill directories are created.
- Each change is atomic enough to be committed independently.

## CLI Enhancements

### `cogforge inbox list --limit N`

Add `--limit` option to constrain the number of returned sources. Used by the processing loop to retrieve exactly one next source.

**Behavior:**
- `cogforge inbox list --limit 1` returns the first matching source
- `--limit 0` returns an empty list
- No `--limit` retains existing behavior (return all)
- Works with all existing filters (`--connector`, `--pageindex`, `--failed`)
- JSON output: `{"sources": [...], "count": N}` clipped to limit

**Implementation:**
- Modify `inbox_list` in `src/cogforge/cli.py`: add `--limit` click option, slice sources list before output

### `cogforge wiki session-new`

Create a new session YAML from metadata flags, without requiring a pre-existing report file. The existing `wiki session-close` requires a report file — this is for the common case where the agent creates a session from in-memory metadata.

**Options:**
```
--summary TEXT       One-line summary of the session
--domain TEXT        Domain name (trading, miniature-painting, etc.)
--files-changed TEXT Comma-separated list of changed file paths  
--decisions TEXT     Comma-separated list of decisions made
--next-steps TEXT    Comma-separated list of next steps
--session-id TEXT    Optional explicit session ID (defaults to timestamp)
```

**Behavior:**
- Creates `<wiki_root>/history/sessions/<timestamp>.yaml` with YAML frontmatter-style structure
- Returns JSON: `{"session_id": "...", "session_file": "..."}`
- Markdown output shows summary + file list

**Implementation:**
- Add `wiki session-new` command to `src/cogforge/cli.py`
- No new Python dependencies needed (YAML already available)

## Skill Updates

For each skill, replace manual bookkeeping steps with CLI commands. Core mapping:

| Old instruction | New instruction |
|---|---|
| `Append changes to ./llm_wiki/history/history.log` | `cogforge wiki log --message "..." --session PATH` |
| `Create or update the session file` | `cogforge wiki session-new --summary "..." --files-changed "..." --domain "..."` |
| `Validate wiki structure` (manual checks) | `cogforge wiki validate` (plus manual checks for content quality) |
| `Move the source to ./llm_wiki/raw` | `cogforge inbox mark-processed SOURCE_ID --history-note "..."` |

### 1. `answer/SKILL.md`

**Replace Step 14:** `Append changes to ./llm_wiki/history/history.log`
→ `cogforge wiki log --message "Persisted answer: <topic>" --session SESSION_PATH`

**Replace Step 15:** `Create or update the session file`
→ `cogforge wiki session-new --summary "<topic>" --domain "<domain>" --files-changed "path1,path2"`

### 2. `create-synthesis/SKILL.md`

**Replace Step 10:** `Append changes to ./llm_wiki/history/history.log`
→ `cogforge wiki log --message "Updated synthesis: <topic>" --session SESSION_PATH`

**Replace Step 11:** `Create or update the session file`
→ `cogforge wiki session-new --summary "<topic>" --domain "<domain>" --files-changed "path1,path2"`

### 3. `lint-wiki/SKILL.md`

**Replace Step 2 skeleton checks:**
→ Add: `Run cogforge wiki validate to check required directories exist.`

**Replace Step 11:** `Append findings and changes to ./llm_wiki/history/history.log`
→ `cogforge wiki log --message "Wiki lint: <summary>" --session SESSION_PATH`

**Replace Step 12:** `Produce a maintenance report that you will save in a session file`
→ `cogforge wiki session-new --summary "Wiki lint report" --domain "<domain>" --next-steps "fix1,fix2"`

### 4. `log-change/SKILL.md`

**Full rewrite.** The entire skill becomes:

```
After any persisted change, run:

cogforge wiki log --message "<reason for change>" --session <session-path>

Log at minimum: reason for the change, related session file.
The CLI handles timestamping and file placement automatically.
```

### 5. `persist-decision/SKILL.md`

**Replace Step 8:** `Append changes to ./history/history.log`
→ `cogforge wiki log --message "Decision: <title>" --session SESSION_PATH`

**Replace Step 9:** `Create or update the session file`
→ `cogforge wiki session-new --summary "Decision: <title>" --domain "<domain>" --decisions "<title>"`

### 6. `process-inbox/SKILL.md`

**Full rewrite — subagent loop.** See dedicated section below.

### 7. `session-memory/SKILL.md`

**Replace manual file creation:**
→ `cogforge wiki session-new --summary "<intent>" --files-changed "path1,path2" --next-steps "step1,step2" --domain "<domain>"`

Keep the list of what the session must capture (user intent, sources consulted, etc.) — these become `--summary` content.

### 8. `update-domain-context/SKILL.md`

**Replace Step 8:** `Append changes to ./history/history.log`
→ `cogforge wiki log --message "Updated domain-context: <domain>" --session SESSION_PATH`

**Replace Step 9:** `Create or update the session file`
→ `cogforge wiki session-new --summary "Domain context update: <domain>" --domain "<domain>"`

### 9. `youtube-transcript/SKILL.md`

**Replace entire bash workflow with:**

```
1. Run: `cogforge sync youtube --url <URL> --format json`
2. If exit code 0: the transcript is saved to inbox/youtube/<video-id>.md
3. If exit code != 0: check errors in JSON output for the failure reason
```

Keep the Rules section (no video/audio download, no claim of watching) but remove all bash commands, python inline scripts, and manual frontmatter assembly. The CLI handles all of that.

## Subagent Inbox Processing Loop

### Design

The main agent loops over inbox sources one at a time. For each source, it spawns a `general` subagent (via the `task` tool) that processes exactly one source in isolation. The subagent has no context from previous sources, avoiding context pollution.

```
MAIN AGENT LOOP:
  while true:
    result = cogforge inbox list --limit 1 --format json
    
    if result.count == 0:
      break  # inbox empty
    
    source = result.sources[0]
    source_id = source.id
    
    # Read full source details
    details = cogforge inbox show {source_id} --format json
    
    # Load domain-context if identifiable from source
    domain = determine_domain(details)
    domain_context = read llm_wiki/wiki/domain-context/{domain}.md if exists
    
    # Spawn isolated subagent
    subagent_output = task(
      subagent_type="general",
      prompt=f"""You are processing ONE raw wiki source in isolation.
      
      SOURCE PATH: {details.inbox_path}
      SOURCE ID: {source_id}
      CONNECTOR: {details.connector}
      DOMAIN: {domain if domain else 'auto-detect'}
      
      DOMAIN CONTEXT (if loaded):
      {domain_context or 'Not available. Auto-detect domain from source content.'}
      
      TASK:
      1. Read the source file at the given inbox path
      2. Identify source type (article, paper, note, transcript)
      3. Identify key concepts, claims, decisions, contradictions
      4. Load the top 10 most relevant existing wiki files under llm_wiki/wiki/
      5. Create or update concept pages under llm_wiki/wiki/concepts/
      6. Add meaningful backlinks between pages
      7. For any new file created, update the relevant index file
      8. Do NOT modify files outside llm_wiki/wiki/ or llm_wiki/system/
      
      OUTPUT (return as JSON):
      {{
        "source_processed": "<source_id>",
        "domain": "<domain>",
        "pages_created": ["path1", "path2"],
        "pages_modified": ["path3"],
        "decisions_captured": ["title1", "title2"],
        "contradictions": ["description"],
        "follow_up_questions": ["q1"],
        "error": null
      }}
      
      If any step fails, include the error and continue with partial results.
      """
    )
    
    # Parse subagent output
    report = parse_json(subagent_output)
    
    # Mark source as processed via CLI
    cogforge inbox mark-processed {source_id} --history-note "{report.summary}"
    
    # Log the processing
    cogforge wiki log --message "Processed {source_id}: {report.pages_created|length} new, {report.pages_modified|length} modified" --session <session-path>
    
    # Create processing session
    cogforge wiki session-new --summary "Processed inbox: {source_id}" --domain "{report.domain}" --files-changed "{join report.all_changes}"
```

### Why Subagents

| Problem | Solution |
|---|---|
| Context pollution — opinions from article A affect reading of article B | Each source gets a fresh `general` subagent with no prior context |
| Token cost — long conversations bloat context | Subagent runs with minimal context (source + domain-context + relevant wiki pages only) |
| Error isolation — one bad source shouldn't crash the batch | Each subagent failure is captured as structured JSON, loop continues |
| Parallel potential — future optimization | Subagents could be spawned in parallel batches (not in this sprint) |

### Updated `process-inbox/SKILL.md` Content

```markdown
---
name: process-inbox
description: Process raw inbox sources into structured wiki knowledge using isolated subagents
---

## Processing Loop

Process sources ONE AT A TIME. For each source:

1. Get next unprocessed source:
   `cogforge inbox list --limit 1 --format json`

2. If empty, stop. Otherwise, read full state:
   `cogforge inbox show <source_id> --format json`

3. Determine domain from source metadata. Load domain-context if available:
   `./llm_wiki/wiki/domain-context/<domain>.md`

4. Spawn a `general` subagent (Task tool) with:
   - The source path from state
   - The domain-context (if loaded)
   - Instructions to: read source, identify concepts/claims/decisions/contradictions, update wiki pages, update index files
   - Required JSON output: `{source_processed, domain, pages_created, pages_modified, decisions_captured, contradictions, follow_up_questions}`

5. Wait for subagent to complete. Parse its JSON output.

6. Run:
   `cogforge inbox mark-processed <source_id> --history-note "<summary>"`

7. Run:
   `cogforge wiki log --message "Processed <source_id>: <N> pages created, <M> modified"`

8. Create session record:
   `cogforge wiki session-new --summary "Processed inbox: <source_id>" --domain "<domain>" --files-changed "<pages>"`

9. Repeat from step 1.

## Subagent Instructions Template

See `./.opencode/agents/inbox-processor-instructions.md` for the canonical subagent prompt template.

## Output Report

After each source, report:
- source processed
- pages created
- pages modified
- decisions captured
- contradictions or uncertainties
- follow-up questions
```

## AGENTS.md Updates

Add a new section documenting the inbox processing loop and the CLI-first approach:

```markdown
### Inbox Processing Loop

To process inbox sources, use a one-at-a-time subagent loop:

1. `cogforge inbox list --limit 1 --format json` → get next source
2. `cogforge inbox show <id>` → read source state + paths
3. Load domain-context for the relevant domain
4. Spawn a `general` subagent (Task tool) with source path + domain-context
5. `cogforge inbox mark-processed <id> --history-note "..."` → finalize
6. `cogforge wiki log --message "..."` → record in history
7. `cogforge wiki session-new --summary "..." --domain "..."` → session YAML
8. Repeat until inbox is empty

This ensures each source is processed in isolation with no context leakage
from previous sources. The CLI handles all deterministic bookkeeping.
```

And update the skills section to reference CLI commands:

```markdown
## Skills and their usage

### session-memory
At the end of every substantial interaction, call:
  `cogforge wiki session-new --summary "..." --domain "..." --files-changed "..."`

### persist-decision
After recording a decision in the wiki, call:
  `cogforge wiki log --message "Decision: <title>"`

### log-changes
After any persisted change, call:
  `cogforge wiki log --message "<reason>" --session <session-path>`

### process-inbox
Use the one-at-a-time subagent loop described in the Inbox Processing section.
Never process multiple sources in the same agent context.
```

## Subagent Instructions File

Create `.opencode/agents/inbox-processor-instructions.md` as a standalone reference for the subagent prompt. This is not a skill — it's the canonical prompt template injected into each `general` subagent tasked with processing one inbox source.

## Implementation Order

1. **CLI enhancements** — `--limit` on `inbox list`, `wiki session-new` command
2. **Tests** — add tests for new CLI options and commands
3. **Commit**
4. **Subagent instructions** — create `.opencode/agents/inbox-processor-instructions.md`
5. **Rewrite `process-inbox/SKILL.md`** — subagent loop
6. **Update remaining 8 skills** — CLI integration
7. **Append CLI references to skill sections** — add `cogforge wiki log` and `cogforge wiki session-new` calls
8. **Update `AGENTS.md`** — inbox loop + CLI-first approach
9. **Commit**

## Acceptance Criteria

- `cogforge inbox list --limit 1` returns at most one source
- `cogforge wiki session-new --summary "test" --domain "trading"` creates a valid YAML session file
- Each SKILL.md references `cogforge` commands instead of manual file paths
- `youtube-transcript/SKILL.md` contains no bash snippets
- `process-inbox/SKILL.md` describes the subagent loop with CLI commands
- AGENTS.md documents the inbox processing loop and CLI-bookkeeping mapping
- All existing 157 tests still pass
