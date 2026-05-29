---
name: process-inbox
description: User asks you to ingest a file, process a raw source, summarize a source into the wiki, or add a document to the knowledge base.
---

Steps:

Sources are all files in ./llm_wiki/inbox.
For each source:

0. Do not run `inbox prepare` during per-source processing. `cogforge inbox run` pre-validates and prepares the selected source before spawning the agent. If the prompt mentions PageIndex or prepared artifacts, use those artifacts while reading the source.

1. Read the source.
2. Identify the source type:
   - article
   - paper
   - book
   - note
   - transcript
3. Determine the relevant domain. Then load its domain-context if available in `./llm_wiki/wiki/domain-context`.
4. Identify:
   - key concepts
   - entities
   - decisions
   - claims
   - open questions
   - operational procedures
   - possible contradictions with existing wiki content
5. Using what you have identified, load the top 10 wiki files you think are most relevant.
6. Create or update relevant pages under `./llm_wiki/wiki/concepts`. Do not create a new page for every minor idea. Prefer enriching existing pages.
7. Add meaningful backlinks between pages.
8. For any new file created, edit the index (described in the structure document)!! super important !!
9. Append the persisted changes to `./llm_wiki/history/history.log`. Create or update the session file.
10. Report:
    - source processed
    - pages created
    - pages modified
    - decisions captured
    - contradictions or uncertainties
    - follow-up questions

11. Move the source to the correct `./llm_wiki/raw` subfolder first.
