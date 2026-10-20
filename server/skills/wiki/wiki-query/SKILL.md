---
name: wiki-query
description: Answer questions against the wiki — index-first navigation, cross-page synthesis with citations, and filing good answers back into the wiki as new pages so exploration compounds.
allowed-tools: data jev
metadata:
  author: opencompany
  version: "1.0"
  category: wiki

---

# Wiki Query Skill

Answer the user's questions from the wiki under `wiki/` — and file
valuable answers back so they compound like ingested sources do.

## Navigation: index-first

1. Read `wiki/index.md` — it catalogs every page with a one-line summary,
   grouped by cluster. Find candidate pages there before any file search.
2. Read the candidates with `data` (`operation: read`). Pages are small
   by design (leaves, not hubs); read several rather than guessing from
   one.
3. If the index is not enough (200+ pages), use `data` with
   `operation: search` on terms, and follow `[[wikilinks]]` outward —
   the links ARE the graph. Note for `WIKI.md`: past a few hundred pages
   the wiki needs real search tooling; record that observation in
   `ideas-to-explore.md` rather than silently degrading.

## Synthesis rules

- Cite pages: every claim in the answer names the `[[page]]` it came
  from. A claim the wiki cannot support is stated as such — "the wiki
  doesn't cover this yet" is a good answer; a confident guess is not.
- Respect supersession headers: content marked superseded is history,
  not current belief. Answer from the live claim, and say when the
  answer depends on something recently superseded.
- Check the `sources` count in frontmatter: a claim backed by one source
  is reported with that caveat when the question is consequential.
- Contradictions stay visible: if pages disagree, present both sides
  with their sources (the "Disagreements & open questions" sections) —
  do not silently pick a winner.

## Answer shapes

Match the form to the question: a direct chat answer, a markdown page, a
comparison table, a timeline, a briefing. Rich visual answers (a graph or
dashboard of wiki content) go through the `wiki-graph` skill's Canvas
path.

## Crystallize: file good answers back

A synthesis the user engaged with — a comparison, an analysis, a
connection discovered — should not vanish into chat history. Before
filing, call `jev` ONCE (contract per the `jev-decisions` skill):

```json
{
  "worth_filing": {
    "type": "noul",
    "instructions": "Is this answer valuable enough to keep as a wiki page — it synthesizes multiple pages, settles a question, or produces a new connection"
  },
  "page_type": {
    "type": "choice",
    "instructions": "If filed, what kind of page does this answer become",
    "criteria": {
      "comparison": "A side-by-side analysis worth keeping as its own page",
      "synthesis": "A cross-page conclusion or consolidated view",
      "question": "A refined open question that replaces or refines an existing question page",
      "none": "The answer is disposable chat content"
    }
  }
}
```

If `worth_filing` clears the bar (noul above your threshold AND a
non-`none` page type), write the page (frontmatter, `sources` = number of
wiki pages it drew from, `## References` = the wiki pages used), update
`index.md`, and append a `## [YYYY-MM-DD] query | <Topic>` entry to
`log.md`. If `worth_filing` is low-confidence, offer it to the user
instead of filing unilaterally.

## Conversation is a source

A session that produces a real insight — a research thread, a chain of
reasoning, a change of mind — is treated exactly like an ingested
document: distill it into pages (what was the question, what changed and
why) without waiting to be asked. That is crystallization in the ingest
sense; use the `wiki-ingest` flow when the insight is substantial.
