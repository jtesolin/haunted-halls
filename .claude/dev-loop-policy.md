# Haunted Halls Frontend dev-loop policy

This file extends the project-agnostic `jt-dev-loop` plugin with requirements specific to the Haunted Halls frontend. Generic review, Director disposition, retry, durable PR-state, external-evidence reconciliation, and readiness mechanics belong to the plugin and are intentionally not duplicated here.

## Architecture and ownership

- This repository, `jtesolin/haunted-halls`, is the public Next.js application and server-side gateway/BFF.
- The related engine repository is `jtesolin/haunted-halls-engine`.
- The frontend owns presentation, browser interaction, session-aware behavior, BFF transport, and authentication integration.
- The engine owns authoritative game/domain state, deterministic game behavior, AI-agent orchestration, narration, memory, guardrails, persistence, and internal APIs.
- Browser code must not call the internal engine directly. Engine credentials, service bearer tokens, secrets, and trusted identity headers remain server-side.
- Preserve Google sign-in, session handling, internal-service authentication, and internal user-resolution boundaries.
- Do not move game-domain rules into React components or Next.js route handlers.
- Treat frontend/engine request or response shape changes as cross-repository API contract changes.

## Runtime lifecycle invariants

For every material user-visible or cross-repository capability, trace the supported production lifecycle from a real user/application entry point through frontend/BFF behavior, prerequisite engine state producers, persistence/service/API boundaries, and the final UI consumer.

A frontend feature that consumes engine state is not production-reachable merely because its UI and types are locally correct. The engine must expose the required contract and normal engine execution must create/update the prerequisite state. Fixtures, manually seeded rows, mocks, direct database edits, and read APIs without a normal producer do not prove reachability.

When engine behavior is material, inspect enough trusted evidence from `jtesolin/haunted-halls-engine` to establish the producer, API contract, authority boundary, and persistence lifecycle. The sibling repository may be at `../haunted-halls-engine`, but that local path is optional; use the GitHub repository when needed.

Historical example:

`create campaign -> create/associate character -> campaign exposes character_id -> frontend enables Character Sheet -> character API returns character data`

## Canonical cross-repository context

For stable cross-repository architecture, authority, and project status, use trusted-base/current canonical documents from `jtesolin/haunted-halls-engine`:

- `docs/architecture.md`
- `docs/project-status.md`

The engine no longer owns a mirrored copy of generic Claude review-loop mechanics. This frontend policy plus the external `jt-dev-loop` plugin define the frontend review boundary.

## Validation requirements

Use the current trusted repository instructions to select validation appropriate to the change. Available verified commands include:

- `npm run lint`
- `npm run typecheck`
- `npm run test`
- `npm run build`
- equivalent `make` targets

Run the narrowest relevant validation first, then broader validation. Changes to BFF/auth/API integration should include focused boundary/error-path tests where practical. Required CI checks for the PR head must pass before readiness under the generic loop.

## Documentation and status

- Update the canonical engine `docs/project-status.md` when a frontend change materially changes cross-repository architecture, behavior, roadmap, or phase-progress status.
- Do not change `Last synchronized (planning memory sync)` unless the user explicitly confirms a planning-memory synchronization.
- Cross-repository stable invariants belong in the canonical engine architecture/status documents; frontend implementation details remain in this repository.

## Cross-repository dependencies

- Validate each repository's implementation and CI independently.
- A change spanning both repositories requires separate branches/PRs and explicit evidence for the prerequisite/consumer contract in each repository.
- Do not make mirrored or speculative engine changes merely because the engine repository is available.
- If the current frontend scope cannot make a claimed capability reachable without unresolved engine/product/architecture work, escalate rather than silently defer the missing prerequisite.

## Human validation

Reserve `human validation required` for checks that genuinely require a person or external environment, such as deployed preview UX, authentication/IAP behavior that cannot be reproduced locally, responsive/mobile interaction, or narrative coherence. Do not use human validation to defer implementable code, tests, build/type/lint validation, or documentation.

## Project-specific escalation

Escalate rather than invent or autonomously choose:

- undocumented game/product semantics that require an authoritative product value;
- significant architecture or repository-responsibility changes;
- authentication, authorization, IAP, trusted-identity, or secret-boundary redesign;
- public/cross-repository compatibility breaks without explicit scope;
- destructive persistence/data-recovery behavior in coordinated engine work;
- model/tool privilege or world-authority changes exposed through frontend work;
- substantial cross-repository scope expansion.

The user retains final merge authority. Never merge autonomously.
