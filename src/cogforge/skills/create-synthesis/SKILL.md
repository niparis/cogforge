---
name: create-synthesis
description: Create or update a synthesis for one domain
---


Use this when the user asks for analysis that combines several concepts, sources, decisions, or domains, or when ingesting material changes the overall picture.

Steps:

1. Read `./llm_wiki/system/structure.md`.
2. Use `./llm_wiki/templates/synthesis.md`.
3. Determine the domain.
4. Read the relevant domain-context page.
5. Read the relevant concept and decision pages.
6. Identify:
   - thesis
   - supporting evidence
   - counterpoints
   - contradictions
   - implications
   - open questions
7. Create or update a page under `./llm_wiki/wiki/synthesis`.
8. Link the synthesis to supporting concepts and decisions.
9. Update the domain-context page if this synthesis changes the domain-level briefing.
10. Log changes:
   ```
   cogforge wiki log --message "Updated synthesis: <topic>" --session SESSION_PATH
   ```
11. Create session record:
   ```
   cogforge wiki session-new --summary "<topic>" --domain "<domain>" --files-changed "path1,path2"
   ```

A synthesis page should not simply summarize one source. It should combine multiple pieces of knowledge.
