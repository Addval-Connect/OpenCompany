---
name: wiki-lint
description: Health-check the wiki — find contradictions, stale claims, orphan pages, missing frontmatter, rotted references, and topics that deserve their own page; fix what is safe with JEV-classified contradiction triage, report the rest.
allowed-tools: data jev
metadata:
  author: opencompany
  version: "1.0"
  category: wiki

---

# Wiki Lint Skill

Periodically health-check the wiki under `wiki/` so it tends toward
health on its own instead of rotting. Fix what is safe; report what
needs the user.

## The sweep

Use `data` (`operation: list` on `wiki/`, then `operation: read` per
page — page contents, not just names). Check every page for:

1. **Frontmatter**: missing or incomplete `title/created/updated/tags/
   status/sources`; dates in a non-ISO format.
2. **Maturity drift**: pages whose content has outgrown (or fallen below)
   their `status`. A `seed` with three corroborating sources and full
   sections wants promotion to `sapling` or `fruit`.
3. **Orphans**: pages with zero inbound links. Either find the pages
   that should link to them (fix), or flag them as candidates for
   merging into a neighbor (report).
4. **Resolved red links**: `[[wikilinks]]` that now point at existing
   pages — fine; but red links that have sat unresolved for a long time
   across many pages are demand signals — list them for the user.
5. **Stale claims**: claims contradicted by newer sources (check
   `updated` dates and the `sources` counts), supersession headers whose
   replacement page never got written.
6. **Contradictions between pages**: two live claims that cannot both
   hold. See the triage below.
7. **Rotted references**: URLs in `references.md` and per-page reference
   sections. Flag them — do not delete; the user decides.
8. **Mentioned but unwritten**: topics referenced repeatedly across
   pages that never got their own page.
9. **Data gaps**: questions the wiki cannot answer that a targeted
   source (a web search, a document the user holds) would fill.

## Contradiction triage — JEV required

For each detected contradiction, call `jev` ONCE (contract per the
`jev-decisions` skill) with `state` = both claims, their sources with
dates and `sources` counts, and the relevant page context:

```json
{
  "resolution": {
    "type": "choice",
    "instructions": "How should this contradiction between two live wiki claims be handled",
    "criteria": {
      "supersede": "One claim is clearly newer/better-sourced — mark the old one superseded with a header pointing to the replacement",
      "coexist-open-question": "Both sides have real support or the claims are opinions — file both under Disagreements & open questions with their sources",
      "update-both": "Neither is wrong; each is partial — merge into an integrated claim on both pages"
    }
  },
  "strength": {
    "type": "score",
    "instructions": "How one-sided is the evidence between the two claims, on a balanced-to-clear rubric",
    "criteria": ["Balanced: evidence genuinely split", "Leaning: one side has recency or an extra source", "Clear: one side dominates on recency and corroboration"]
  }
}
```

Let `strength` temper `resolution`: a `supersede` decision on a weak
`strength` should degrade to `coexist-open-question`. Near-tie choices
(confidence below ~0.6) go to the user, not to an automatic edit.

## Fix vs report

**Fix autonomously** (then log): frontmatter completion, maturity
promotions, inbound links for orphans, supersession headers whose
replacement exists, merging duplicate entities, obvious connection
edits.

**Report to the user** (a lint digest in chat, then logged): rotted
references, contradictions that stayed open questions, red-link demand
signals, data gaps with suggested sources, deletions (you cannot delete
— propose what should be removed and why; removal is a human action in
the Data panel).

## Log it

Append one entry per pass: `## [YYYY-MM-DD] lint | <one-line verdict>`,
then a bullet list of fixes applied and items escalated. A lint pass that
fixes nothing but finds nothing is also worth its line — it is evidence
of health.
