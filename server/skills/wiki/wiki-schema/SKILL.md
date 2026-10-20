---
name: wiki-schema
description: Conventions and stance for maintaining an LLM-built wiki inside the workflow workspace — three layers (raw / wiki / schema), ingest-query-lint loop, digital-garden page conventions, and the never-silently-overwrite rule. Load first; every other wiki skill assumes it.
allowed-tools: data
metadata:
  author: opencompany
  version: "1.0"
  category: wiki

---

# Wiki Schema Skill

You maintain a **persistent, compounding wiki** inside this workflow's
workspace, built on the LLM Wiki pattern (Karpathy) + lifecycle guidance
(rohitg00's v2) + digital-garden conventions (learnopengles' mindmap
extension). This file is the schema. The user curates sources, asks
questions, and directs; **you do all the writing and bookkeeping**.

## The three layers

- **Raw sources** — `wiki/raw/` (fetched articles, exports, transcripts)
  and `wiki/inbox/` (unsorted drops the user made). **Immutable**: read
  from them, never modify or rewrite them. If a file must be corrected,
  tell the user — deletion is a human action in this platform.
- **The wiki** — every other page under `wiki/`. You own this layer
  entirely: create pages, update them, keep cross-references and the
  index current.
- **The schema** — this skill plus `wiki/WIKI.md`. The skill holds the
  general contract; `WIKI.md` records the *domain-specific instantiation*
  (what this wiki is for, who reads it, voice, folder decisions). You and
  the user co-evolve `WIKI.md`; when a convention changes, update it and
  say why in the log.

## Folder layout

Everything lives under `wiki/` in the workspace (one self-contained,
portable unit):

```
wiki/
├── WIKI.md               # domain schema (co-evolved with the user)
├── index.md              # content catalog: every page + one-line summary
├── log.md                # append-only chronology: ingest | query | lint | ...
├── home.md               # human entry point: a few starting pages
├── provenance.md         # why this exists, lineage, how to continue it
├── references.md         # catalog of external sources
├── ideas-to-explore.md   # brainstorm menu of conventions/tools worth trying
├── graph.html            # generated graph view (see the wiki-graph skill)
├── inbox/                # staging area for user drops (not wiki pages)
├── raw/                  # immutable source material
├── assets/               # images and attachments referenced by pages
└── <page>.md             # the wiki pages themselves — FLAT, kebab-case
```

No subfolders for pages unless a clear cluster emerges organically — and
then only with a note in `WIKI.md` explaining it.

## Page conventions

- YAML frontmatter on every page: `title`, `created` (ISO date),
  `updated` (ISO date), `tags` (list), `status` (`seed | sapling |
  fruit`), `sources` (count of distinct raw sources supporting the page).
  `index.md` and `log.md` are meta files and skip `status`/`sources`.
- Filenames in lowercase kebab-case (`quarterly-tax-notes.md`), never
  renamed silently — a rename means updating every inbound `[[link]]`
  and the index, and a `rename` log entry.
- One topic per page. Link out instead of embedding tangents.
- **Leaves, not hubs.** Prefer many small focused pages over hub pages
  that summarize a cluster. If a page accumulates several distinct ideas,
  split it into linked leaves.
- **Maturity markers.** `status: seed` (raw capture or stub), `sapling`
  (real content, open sections), `fruit` (settled, still allowed to
  evolve). Pages can move backward when thinking shifts.
- **Red links are good.** `[[a-page-that-does-not-exist-yet]]` is a
  growth prompt, not an error. But a gesture at unprocessed material
  stays a one-line mention, not a stub page — every page must stand as a
  leaf on its own.
- **Questions are pages too.** An open question the user is sitting with
  gets its own page tagged `question` (status seed or sapling).
- **Link by concept, not by keyword.** Two pages can deserve a link with
  no shared term. A `See also:` section at the bottom holds looser
  associations.

## Never silently overwrite

This platform's `data` tool has **no delete operation** — deletion is
deliberately a human action. That matches the wiki's core rule:

- When new information contradicts or updates an existing claim, the old
  version is preserved and **explicitly superseded**: a header note links
  to the replacement, with the date and the reason. Nothing disappears;
  git history plus the header note is the audit trail.
- For *opinions* (not facts), supersession is wrong — both claims move to
  a **"Disagreements & open questions"** section with both sources. That
  section is frequently the most valuable part of a page.
- Capture pipelines fail open: if a source can't be fully processed, file
  what you have, mark the page `seed`, and note the gap in the log —
  never drop the raw content silently.

## References and portability

- The user provides references; do not go hunting for citations. A
  citation that shaped a page goes in its `## References` section and is
  catalogued centrally in `references.md`. Referencing is not
  endorsement — no disclaimers.
- Describe external files and systems by name ("the cartolas archive"),
  never by absolute path or `file://` link. The wiki must survive being
  copied elsewhere. Web URLs are fine.

## No secrets

The wiki must never contain passwords, API keys, tokens, account
numbers, or PII beyond what the user explicitly directs. Writing *about*
sensitive topics is fine; the specifics live elsewhere.

## Stance

- **Thinking partner, not stenographer.** Engage before writing: ask
  why, challenge assumptions, flag contradictions with existing pages.
  Push surface-level statements for the thought underneath.
- **Write what the user actually thinks**, not what you infer they
  think. When unsure, ask.
- **Show the trail.** When a view changes, keep the movement visible
  ("I used to think X, now Y because...") — how thinking moved is as
  interesting as where it landed.
- **Just make obvious connections.** When a cross-reference clearly
  belongs on an existing page, edit it — graph maintenance does not need
  permission.

## The two special files

- `index.md` is content-oriented: every page with a link, a one-line
  summary, grouped by the clusters that emerge from the content, with a
  `## Meta` group for the special files. Update on every ingest.
- `log.md` is chronological and append-only. Every entry starts with
  `## [YYYY-MM-DD] <verb> | Title` — verbs: `ingest`, `query`, `lint`,
  `connect`, `rename`, `schema`, `graph`. The prefix keeps the log
  parseable (`grep "^## \[" log.md | tail -5`).

## What this wiki is not

Not a file backup, not a task tracker, not a diary of events, not a
mirror of documents that live in other tools. It captures what the user
*thinks* about things — synthesis, not storage.
