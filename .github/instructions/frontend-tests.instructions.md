---
name: Haunted Halls Frontend Test Rules
description: Vitest and Testing Library guidance for frontend and Next.js gateway tests.
applyTo: "tests/**/*.test.ts,tests/**/*.test.tsx"
---

- Use the existing test stack: Vitest with jsdom and Testing Library setup from tests/setup.ts.
- Test observable behavior and response contracts, not implementation internals.
- Keep tests deterministic and independent.
- Add a focused regression test when fixing a defect.
- Cover success, validation failure, authorization failure, and dependency failure when relevant.
- For React tests, prefer user-visible behavior and accessible queries.
- Mock external boundaries (engine fetch calls, auth provider/session behavior) instead of mocking the unit internals.
- Do not call real external services.
- Prefer focused assertions over broad snapshots.
- Reuse existing setup/helpers and keep test data minimal and explicit.
- Run the narrowest relevant test first, then broader coverage:
  - `npm run test -- tests/<target-file>.test.ts`
  - `npm run test`
- Do not weaken assertions just to make a failing test pass.
