---
name: wiki-bootstrap
description: Scaffold the wiki/ folder in this workflow's workspace on first use — meta files, inbox/raw/assets dirs, and the first-session interview that fixes the wiki's purpose, reader, and voice in WIKI.md.
allowed-tools: data
metadata:
  author: opencompany
  version: "1.0"
  category: wiki

---

# Wiki Bootstrap Skill

Create the wiki scaffold inside this workflow's workspace. **Idempotent**:
check before writing so an existing wiki is never clobbered.

## Step 1 — Detect

Call `data` with `operation: list` and an empty `path` to see the workspace
root. If `wiki/` already exists with an `index.md`, the wiki is live — do
NOT re-scaffold. Read `wiki/WIKI.md` and `wiki/log.md` (last entries) to
load context, then continue with whatever the user asked.

## Step 2 — First-session interview (only for a fresh wiki)

Before creating anything, ask the user (keep it short, follow up where
answers are thin):

1. What is this wiki **for**? (domain: tax research, project decisions,
   competitive analysis, personal thinking map...)
2. Who reads it — just the user, the team, or future readers?
3. What voice and tone should pages have — the user's own voice, neutral
   analytical, briefing-style?

Do not guess these. The answers go into `WIKI.md` verbatim-ish.

## Step 3 — Scaffold via the `data` tool

Create the files with `operation: write` (workspace-relative paths):

- `wiki/WIKI.md` — the domain schema: purpose, audience, voice (from the
  interview), plus any folder decisions and conventions the user wants.
  Start it with a line telling a future agent: "this file plus the
  wiki-* skills are all you need; read index.md, then log.md next."
- `wiki/index.md` — empty catalog skeleton: `## Meta` group listing the
  special files, ready for page groups.
- `wiki/log.md` — first entry: `## [YYYY-MM-DD] schema | Wiki created`,
  one line noting the interview answers.
- `wiki/home.md` — human entry point; link `WIKI.md`-declared starting
  topics (red links are fine).
- `wiki/provenance.md` — why this exists; lineage: Vannevar Bush's Memex,
  Karpathy's LLM Wiki, the v2 lifecycle extension, the digital-garden
  conventions; and how a future maintainer continues it.
- `wiki/references.md` — empty catalog grouped to mirror `index.md`.
- `wiki/ideas-to-explore.md` — empty brainstorm menu (tools, conventions,
  process moves worth trying) so `WIKI.md` stays lean.

Directories (`inbox/`, `raw/`, `assets/`) materialize on first use — the
`data` tool creates parent folders on write. If the platform's Data panel
supports creating empty folders, do so; otherwise write a `.gitkeep`-style
placeholder only if listing empty dirs matters.

## Step 4 — Seed and confirm

- If the user already named sources or topics, capture the first one now
  (hand off to the `wiki-ingest` flow) — a wiki born empty stays empty.
- Suggest running the graph view (`wiki-graph`) once a handful of pages
  exist, not immediately.
- Append the bootstrap to `log.md`.

## WIKI.md is co-evolutionary

When a convention stops working, change it — and record the change in
`WIKI.md` plus a `## [YYYY-MM-DD] schema | ...` log entry explaining why.
The first version will be rough; a few dozen real cycles shape it into
something that reflects how this domain actually works.
