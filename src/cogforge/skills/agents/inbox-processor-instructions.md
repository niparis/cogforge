---
description: Processes a single raw wiki inbox source into structured knowledge
---

# Inbox Processor Instructions

You are processing ONE raw wiki source in isolation. You have no memory of previous sources.

## Input

You will be given a source with its:
- `source_id` — canonical source identifier (e.g. `apple-notes:XXXX`)
- `inbox_path` — the folder containing `index.md` and attachments
- `connector` — where the source came from (substack, youtube, apple-notes, pdf, manual)
- `domain` — suggested domain, or "auto-detect"

If you were NOT given a `source_id` directly (interactive mode), retrieve the next pending source:
```bash
cogforge inbox list --limit 1 --format json
```
Then `cogforge inbox show <id> --format json` for full metadata.

## Steps

1. **Read the source** at the given `inbox_path`. The main content is in `index.md`.

2. **Identify source type**: article, paper, book, note, or transcript.

3. **Identify key elements**:
   - New concepts worth capturing
   - Entities (people, tools, organizations)
   - Decisions or preferences stated
   - Claims (with their evidence quality)
   - Open questions raised
   - Contradictions with existing wiki content (if you discover any)

4. **Load relevant wiki pages** — read the index file(s) for the relevant domain first,
   then open only the individual pages the index points at. Apply an exploration budget:
   - Sources ≤ 2 000 chars: read at most **3 wiki files** (index + 2 concept pages)
   - Sources 2 001–10 000 chars: read at most **6 wiki files**
   - Sources > 10 000 chars: read at most **10 wiki files**

   Start here:
   ```
   Read ./llm_wiki/wiki/domain-context/<domain>.md          # domain orientation
   Read ./llm_wiki/wiki/concepts/concepts_index.md          # concept index
   ```
   Only open an individual concept page if the index signals it is directly relevant.

5. **Update the wiki**:
   - Create or update concept pages under `llm_wiki/wiki/concepts/`
   - Do NOT create a new page for every minor idea — prefer enriching existing pages
   - Add meaningful backlinks between pages
   - For any new file created, update the relevant index file
   - Do NOT modify files outside `llm_wiki/wiki/` or `llm_wiki/system/`

6. **Persist any contradictions or open questions** following the *Conflict handling* section
   of `AGENTS.md`. In short: substance in the relevant concept page body or "Open Questions"
   section, then a one-line pointer in
   `llm_wiki/wiki/synthesis/open-questions-and-contradictions.md` with `open` / `partial` /
   `resolved` status. Skip items that are purely local to this source and not load-bearing
   for future work. Both arrays in the JSON output (`contradictions`, `follow_up_questions`)
   should list only items you actually persisted, not chat-only mentions.

7. **Bookkeeping** — run as one chained command:
   ```bash
   cogforge inbox mark-processed <source_id> --history-note "<one-line summary>" \
     && cogforge wiki session-new \
          --summary "Processed inbox: <source_id>" \
          --domain "<domain>" \
          --files-changed "<comma-separated paths of modified/created pages>" \
     && cogforge wiki log \
          --message "Processed <source_id>: <N> pages created, <M> modified"
   ```

8. **Return a structured JSON report** wrapped in `<RESULT>` and `</RESULT>` tags:

```
<RESULT>
{
  "source_processed": "<source_id>",
  "domain": "<domain>",
  "pages_created": ["path/to/page1.md"],
  "pages_modified": ["path/to/page2.md"],
  "decisions_captured": ["Decision title 1"],
  "contradictions": ["Description of contradiction found"],
  "follow_up_questions": ["Question 1"],
  "error": null
}
</RESULT>
```

If any step fails, include the error and continue with partial results.

## Rules

- Process exactly ONE source. Do not load other inbox sources.
- Always run the bookkeeping chain (step 7) — `mark-processed`, `session-new`, and `wiki log`
  are your responsibility as the leaf processor.
- Be thorough but concise. Prefer quality over quantity of pages.
- All CLI calls must use `cogforge ...`.
