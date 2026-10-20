---
name: wiki-ingest
description: Ingest a source into the wiki — read it, discuss takeaways, classify page type and maturity with the JEV tool, write or update pages with explicit supersession, and keep index.md and log.md current. One source typically touches several pages.
allowed-tools: data jev
metadata:
  author: opencompany
  version: "1.0"
  category: wiki

---

# Wiki Ingest Skill

Integrate a new source into the wiki so its knowledge **compiles** into
the existing structure instead of piling up. The wiki pages live under
`wiki/` in the workspace (see `wiki-schema` for conventions).

## The flow

### 1. Read the source

Sources live in `wiki/raw/` (curated) or `wiki/inbox/` (user drops).
Use `data` with `operation: read` — page with `offset`/`limit` and check
`truncated` before summarizing; a truncated read is a sample. Copy
nothing: raw files are immutable and stay where they are.

### 2. Discuss before writing

Engage as a thinking partner: surface the key takeaways, what challenges
existing pages, what is genuinely new. If the input is surface-level,
push for the thought underneath. Write only after the substance is on the
table — but do not stall: for obvious mechanical captures (a clipped
article, a transcript) summarize and proceed, flagging what deserves
discussion later.

### 3. Classify with JEV (required)

Before creating or updating pages, call the `jev` tool ONCE per source
with `state` = your synthesis of the source plus the relevant wiki
context, and `questions` following the contract taught by the
`jev-decisions` skill:

```json
{
  "page_type": {
    "type": "choice",
    "instructions": "What kind of wiki page does this source primarily become",
    "criteria": {
      "entity": "A thing with identity: person, company, product, file, system",
      "concept": "An idea, mechanism, or domain topic explained across sources",
      "source": "A per-source summary page tied to one raw document",
      "question": "An open question the source raises but does not settle",
      "comparison": "A side-by-side analysis of two or more entities/concepts",
      "synthesis": "A cross-source conclusion drawn from several pages"
    }
  },
  "maturity": {
    "type": "score",
    "instructions": "How settled is the knowledge this source contributes, on a seed-to-fruit rubric",
    "criteria": ["Seed: raw capture, barely processed", "Sapling: real content with open sections", "Fruit: settled, corroborated understanding"]
  },
  "is_superseding": {
    "type": "noul",
    "instructions": "Does this source contradict or update a claim already present in the wiki, rather than only adding to it"
  }
}
```

Read the answers as taught by `jev-decisions`: a near-tie `choice`
(confidence below ~0.6) means classify conservatively (`source` page,
`seed` status) and say so; the `score` can land between levels — use the
number, not the label, when setting `status`.

### 4. Write or update pages

With `data` (`operation: write` for new files, `append` to grow existing
ones):

- New page: frontmatter (`title`, `created`, `updated`, `tags`,
  `status`, `sources: N`), kebab-case filename, one topic per page,
  `[[wikilinks]]` by concept, `## References` section citing the source
  (by name, never absolute paths).
- The `sources` count = distinct raw documents supporting the page.
  Increment it on every reinforcing ingest.
- Touch 10–15 pages if the source warrants it — updating cross-references
  and summaries across the wiki is exactly the bookkeeping you exist to
  do. Do not ask permission for obvious connection edits.

### 5. Supersession (when `is_superseding` says yes)

Never silently overwrite. In the affected page:

- Facts: keep the old claim, prefix it with a supersession header —
  `> Superseded YYYY-MM-DD by [[new-page]]: <reason>` — and write the
  new claim in the live section. Old versions are preserved, not
  deleted; the platform has no delete and that is deliberate.
- Opinions or values: do NOT supersede — move both claims into the
  page's **"Disagreements & open questions"** section, each with its
  source. Classify this split yourself; if unsure, prefer the open
  question and flag it to the user.

### 6. Index and log

- Update `wiki/index.md`: new pages get a link + one-line summary in the
  right cluster; changed pages get their summaries refreshed.
- Append to `wiki/log.md`: `## [YYYY-MM-DD] ingest | <Source title>`,
  then one line per page touched (created vs updated).

### 7. Connection pass

For every page you touched, check existing pages for links that should
now point to it (and red links it resolves). The value of the wiki is in
the connections — make them without being asked.

## Batch mode

With several sources queued, ingest them one at a time in a single
session: read → classify → write → index → log, per source. Keep the
user's involvement level as they direct it, and record each source
separately in the log so the timeline stays honest.
