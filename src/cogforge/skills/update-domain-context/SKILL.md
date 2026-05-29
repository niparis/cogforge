# Workflow: update domain context


There should be one domain-context file per domain, no more and no less.

Steps:

1. Read `./system/structure.md`.
2. Use `./templates/domain-context.md`.
3. Identify the relevant domain.
4. Open the existing domain-context page.
5. Update it with:
   - current state
   - important concepts
   - active decisions
   - known constraints
   - recurring preferences
   - operational facts
   - known pitfalls
   - open questions
   - relevant derived outputs
6. Keep the page concise. It is a briefing, not a full dump.
7. Link to deeper concept, decision, synthesis, or derived-output pages.
8. Log changes:
   ```
   cogforge wiki log --message "Updated domain-context: <domain>" --session SESSION_PATH
   ```
9. Create session record:
   ```
   cogforge wiki session-new --summary "Domain context update: <domain>" --domain "<domain>"
   ```

Domain-context pages are the first pages future agents should read.
