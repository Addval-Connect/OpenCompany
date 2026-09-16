# Diagrams

One set, dark theme, all SVG. This folder is the only copy; nothing under
`docs-internal/` vendors these files.

**Overview diagrams** (linked from the README and CONTRIBUTING):

- `how-it-works.svg`, `default-workflows.svg` (README)
- `system-overview.svg`, `execution-flow.svg`, `ai-agent-routing.svg`, `node-anatomy.svg` (CONTRIBUTING)

**Architecture and product-panel diagrams** (indexed in CONTRIBUTING under
"More Diagrams"): `system-context`, `runtime-trust-topology`,
`workflow-execution-routing`, `durable-deployment-events`,
`plugin-agent-team-composition`, `persistence-secret-plane`,
`workspace-anatomy`, `node-configuration-anatomy`, `credentials-architecture`,
`team-operations`, `agent-context-memory`, `master-skill-editor`,
`workspace-files`, `runtime-observability-dock`. Each file's `<desc>` lists
the source files it was drawn from.

Facts on every diagram were checked against the code in September 2026.
Counts come from the live registries (`len(NODE_METADATA)`,
`len(CREDENTIAL_REGISTRY)`, `config/llm_defaults.json`), and ports are
named by their `.env.template` variables rather than numbers.
