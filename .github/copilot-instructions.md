# Haunted Halls Web Application Instructions

## Repository Role

- This repository is the public Haunted Halls Next.js web application.
- It is the browser-facing application and the server-side gateway to the internal engine.
- It owns web UI, browser interaction, session-aware behavior, and server-to-engine request forwarding.
- It does not own game rules, AI-agent orchestration, narration logic, long-term memory processing, or engine persistence.

## Architectural Boundaries

- Browser code must not call the internal engine directly.
- Keep engine credentials, service bearer tokens, secrets, and trusted identity headers server-side.
- Treat request or response shape changes between this repo and the engine as cross-repository API contract changes.
- Do not move game-domain logic into React components or Next.js route handlers.
- Keep route handlers and gateway helpers focused on transport, authentication, validation, mapping, and error translation.
- Reuse existing abstractions in app/api and lib before adding new architectural layers.
- Preserve current Google sign-in, session handling, internal-service auth, and internal user-resolution boundaries.

## Working Practices

- Inspect nearby code and tests before changing behavior.
- Prefer small, focused changes.
- Do not silently change public behavior or API contracts.
- Do not add dependencies when the existing stack is sufficient.
- Never commit secrets or real credentials.
- Use verified commands:
  - `npm run dev`
  - `npm run lint`
  - `npm run typecheck`
  - `npm run test`
  - `npm run build`
  - `make dev`, `make lint`, `make test`, `make build`
- Run the narrowest relevant validation first, then broader validation when appropriate.
