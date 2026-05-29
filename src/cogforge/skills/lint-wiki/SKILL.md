---
name: lint-wiki
description: User asks you to ingest a file, process a raw source, summarize a source into the wiki, or add a document to the knowledge base.
---


1. Read `./llm_wiki/system/structure.md`.
2. Run `cogforge wiki validate` to check required directories exist.
3. Check if all the indexes files have been created. (cf structure file)
4. Check if all files are present in their respective indexes
5. Check for wiki pages missing required template sections.
6. Check for broken wikilinks.
7. Check for orphan pages.
8. Check for duplicate or near-duplicate concepts.
9. Check for stale or overly long domain-context pages.
10. Check for synthesis pages that only summarize one source.
11. Fix safe issues directly if the user requested cleanup. For ambiguous issues, list recommendations instead of making destructive changes.
12. Log findings:
   ```
   cogforge wiki log --message "Wiki lint: <summary>" --session SESSION_PATH
   ```
13. Save maintenance report as session:
   ```
   cogforge wiki session-new --summary "Wiki lint report" --domain "<domain>" --next-steps "fix1,fix2"
   ```

Never perform large reorganizations silently.
