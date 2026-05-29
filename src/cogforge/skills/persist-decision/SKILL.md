---
name: persist-decision
description: Record a durable decision in the wiki
---

## Workflow: create or update decision


Steps:

1. Read `./system/structure.md`.
2. Use `./templates/decisions.md`.
3. Check whether a related decision already exists under `./wiki/decisions`.
4. If yes, update the existing decision instead of creating a duplicate.
5. Capture:
   - context
   - options considered
   - decision made
   - rationale
   - trade-offs
   - expected outcome
   - revisit trigger
   - related concepts
   - related sources or sessions
6. Link the decision from the relevant domain-context page.
7. Link the decision to related concepts or synthesis pages.
8. Log changes:
   ```
   cogforge wiki log --message "Decision: <title>" --session SESSION_PATH
   ```
9. Create session record:
   ```
   cogforge wiki session-new --summary "Decision: <title>" --domain "<domain>" --decisions "<title>"
   ```
10. If the outcome becomes known later, update the decision page rather than creating a new page.

Decision pages exist to prevent re-litigating the same question in future sessions.
