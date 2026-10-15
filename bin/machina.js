#!/usr/bin/env bun

// Deprecated compatibility entry point. Keeping this wrapper separate from
// cli.js makes alias detection reliable through the Windows bin shims, which
// invoke the target JavaScript file rather than preserving the bin name.
process.env.OPENCOMPANY_LEGACY_ALIAS = 'machina';
await import('./cli.js');
