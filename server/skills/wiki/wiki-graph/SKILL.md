---
name: wiki-graph
description: Generate the wiki's graph view — extract [[wikilinks]] and page metadata from all wiki pages into wiki/graph.html (self-contained, no dependencies) and push it to the Canvas node so the user sees the shape of the wiki (hubs, orphans, red links).
allowed-tools: data canvas
metadata:
  author: opencompany
  version: "1.0"
  category: wiki

---

# Wiki Graph Skill

Produce the "Obsidian graph view" of the wiki: a single self-contained
HTML file the user opens from the Canvas. Regenerate it after structural
changes (ingests, renames, lint merges) or when asked.

## Step 1 — Collect pages and links

- `data` `operation: list` on `wiki/` → the page list (ignore `raw/`,
  `inbox/`, `assets/`, and the meta files except `index.md`).
- `data` `operation: read` each page (text tier). From each page extract:
  - `title` and `status` from the frontmatter (`seed | sapling | fruit`;
    meta files and missing status render as plain nodes).
  - `tags` (for hover tooltips).
  - Every `[[wikilink]]` target (normalize to kebab-case; strip display
    aliases like `[[page|shown text]]`).

## Step 2 — Build the graph model

- **Nodes**: one per real page (`id` = filename without `.md`).
- **Edges**: one per wikilink (deduplicated, direction page → target).
- **Red links**: targets that do not exist as pages become *virtual*
  nodes (`virtual: true`) drawn smaller and hollow; their edges are
  dashed. Red links are demand signals, not errors — showing them is the
  point.
- **Orphans**: real nodes with zero edges get flagged in the stats.

## Step 3 — Write `wiki/graph.html`

Write it with `data` (`operation: write`, path `wiki/graph.html`). The
file must be **self-contained**: inline CSS + JS, no CDN, no external
fetches, no absolute paths — it must render when copied to any machine
(portability rule). Structure:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Wiki graph</title>
<style>
  /* dark canvas, fixed header with stats, hover tooltip div */
</style></head>
<body>
  <div id="stats"></div>
  <svg id="graph"></svg>
  <div id="tip"></div>
  <script>
    const GRAPH = /*__GRAPH_JSON__*/;
    // simple force-directed simulation in vanilla JS:
    //   repulsion between nodes, spring attraction on edges,
    //   centering force; run ~300 ticks, then stop and render.
    // Node radius: degree-scaled (hubs bigger). Color by status:
    //   seed amber / sapling blue / fruit green / meta gray;
    //   virtual (red-link) nodes: smaller, hollow, dashed edges.
    // Click a node -> location.hash = page name (harmless offline);
    //   hover -> tooltip with title, status, tags, degree.
  </script>
</body></html>
```

Rules for the JSON blob: page count is modest (tens to low hundreds) —
embed the full `{"nodes": [...], "edges": [...]}` array; keep ids short;
escape `</` in embedded strings as `<\/`. Keep the simulation plain
vanilla JS (a ~40-line verlet loop is enough); no libraries.

Header stats: total pages, total links, red-link count, orphan count —
the same numbers a lint pass reports.

## Step 4 — Push to the Canvas

Call the `canvas` tool with:

- `path`: `wiki/graph.html` (a workspace file reference — the board
  renders it; bytes never travel through the tool).
- `mode`: `replace` (the board holds the current graph, not a history).
- `caption`: `Wiki graph — N pages · M links · R red links`.

## Step 5 — Log

Append to `wiki/log.md`:
`## [YYYY-MM-DD] graph | N pages, M links, R red links` — plus one line
if the shape changed meaningfully (a new hub emerged, an orphan got
connected, red links resolved).

## Interpretation (offer, don't lecture)

After rendering, offer one or two observations max: the hub pages (many
inbound links) and the biggest red-link clusters — those are "what the
wiki wants to become next". Defer deep analysis to the `wiki-lint`
skill; the graph is a view, not the audit.
