# Frontend Test Suite

Locks in the user-facing invariants from [docs-internal/ARCHIVE/credentials_panel.md §5](../../../docs-internal/ARCHIVE/credentials_panel.md).

## Run

```bash
cd client
npm install            # picks up the new devDependencies
npm run test           # one-shot (vitest run)
npm run test:watch     # watch mode
npm run test:coverage  # with v8 coverage report
```

## Layout

51 test files live beside their subjects, almost all under `__tests__/` directories, across adapters/, assets/icons/, components/ (and its subfolders auth/, onboarding/, parameterPanel/, parameterPanel/canvas/, ui/), contexts/, hooks/, lib/, store/, stores/, types/, utils/. Targeted subsets: `npm run test:credentials`, `npm run test:nodepanels`.

## Tooling

- **Vitest** + **jsdom** for fast component tests
- **@testing-library/react** + **@testing-library/user-event** for behaviour assertions
- **builders.ts** for test-data factories — keep test bodies focused on deltas, not boilerplate
- **setup.ts** stubs `matchMedia` / `ResizeObserver` / `IntersectionObserver` (jsdom doesn't ship them; antd needs them)

## What this suite does NOT test

- Antd internals (Modal, Form, Input, Select)
- `react-flow` rendering
- Backend handlers (covered by `server/tests/credentials/`)
- Full OAuth round-trip with real X / Google (no network)
