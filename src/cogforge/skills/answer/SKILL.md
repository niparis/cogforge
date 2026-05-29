---
name: answer
description: User asks a question
---

Steps:

2. Identify the likely domain.
3. Read the relevant domain-context page first.
4. Search or inspect relevant pages under:
   - `./llm_wiki/wiki/concepts`
   - `./llm_wiki/wiki/decisions`
   - `./llm_wiki/wiki/synthesis`
   - `./llm_wiki/wiki/derived-outputs`
   - `./llm_wiki/history/sessions`, if recent continuity matters
5. If necessary, consult raw sources, but prefer compiled wiki pages for orientation.
6. Answer the user clearly.
7. Distinguish:
   - known facts
   - prior decisions
   - current assumptions
   - uncertainty
   - suggested next steps
8. Decide whether the answer produced durable knowledge.

Persist the answer only if it contains one or more of:

- a reusable explanation
- a durable decision
- a correction from the user
- a new synthesis
- a useful troubleshooting pattern
- a reusable output
- domain context that future agents should know

If the answer is durable:

9. Update relevant concept pages.
10. Create or update a decision page if a decision was made.
11. Create or update a synthesis page if the answer combines multiple concepts.
12. Save shareable or multi-domain outputs under `.//llm_wikiwiki/derived-outputs`.
13. Update the relevant domain-context page.
14. Log changes:
   ```
   cogforge wiki log --message "Persisted answer: <topic>" --session SESSION_PATH
   ```
15. Create session record:
   ```
   cogforge wiki session-new --summary "<topic>" --domain "<domain>" --files-changed "path1,path2"
   ```

ALWAYS INFORM THE USER IF YOU PERSIST NEW FACTS
