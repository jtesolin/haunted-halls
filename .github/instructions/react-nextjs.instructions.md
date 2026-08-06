---
name: Haunted Halls React and Next.js Rules
description: App Router, client/server boundary, and UI behavior guidance for Next.js application code.
applyTo: "app/**/*.ts,app/**/*.tsx,components/**/*.tsx"
---

- Follow the existing App Router structure under app/.
- Keep secrets, engine calls, trusted identity propagation, and internal-service authentication on the server.
- Use client components only for browser APIs, interactive local state, effects, and event handlers.
- Do not add "use client" to bypass a server/client boundary issue.
- Keep engine communication behind existing server-side gateway helpers in lib/ and route handlers.
- Browser components must not fetch the engine directly.
- Keep route handlers thin; do not implement game rules, orchestration logic, or persistence logic in handlers.
- Follow established data-loading, request-state, and user-visible error-message patterns.
- Preserve accessibility with semantic HTML, labels, keyboard support, and meaningful disabled/loading states.
- Follow the current styling approach (Tailwind via globals.css and utility classes).
- Avoid unnecessary component extraction; extract when a clear reusable responsibility exists.
- Account for loading, empty, success, and failure states when relevant.
- Avoid exposing internal engine error details to browser users.
- Treat API shape changes as explicit contracts that may require engine coordination.
- This project uses Next 16; verify behavior against the local Next docs when introducing framework-level changes.
