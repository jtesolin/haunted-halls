<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Haunted Halls Frontend Agent Context

Use this as a short navigation map; repository-specific instructions remain
authoritative for local engineering practice.

## Primary references

- [.github/copilot-instructions.md](.github/copilot-instructions.md) — web
  role, BFF/auth boundary, and working practices.
- [.github/agents/local-developer.agent.md](.github/agents/local-developer.agent.md)
  — local implementation and review-remediation workflow.
- Canonical cross-repository status:
  [`jtesolin/haunted-halls-engine/docs/project-status.md`](https://github.com/jtesolin/haunted-halls-engine/blob/main/docs/project-status.md).
- Canonical architecture and authority invariants:
  [`jtesolin/haunted-halls-engine/docs/architecture.md`](https://github.com/jtesolin/haunted-halls-engine/blob/main/docs/architecture.md).
- Canonical review-disposition policy:
  [`jtesolin/haunted-halls-engine/docs/review-triage-policy.md`](https://github.com/jtesolin/haunted-halls-engine/blob/main/docs/review-triage-policy.md).

When the sibling engine repository is present locally, its usual convenience
path is `../haunted-halls-engine`; do not require that path to exist. The
GitHub repository above is canonical.

## Review and planning source hierarchy

When evaluating a current change, use sources in this order:

1. Current repository code and tests for implemented behavior.
2. The linked GitHub implementation issue for the change's intended scope and
   acceptance criteria.
3. The engine's canonical `docs/project-status.md`.
4. The engine's canonical `docs/architecture.md`.
5. This repository's `.github/copilot-instructions.md`.
6. Older PR descriptions, historical issues, and conversational context only
   as supporting history when needed.

If durable sources conflict, surface the current code and explicit issue intent
for human escalation rather than silently reconciling the conflict.
