---
name: Haunted Halls Auth and Internal Trust Rules
description: Rules for NextAuth session trust, internal user resolution, and server-to-engine authentication boundaries.
applyTo: "lib/auth.ts,lib/internal-user-resolution.ts,lib/route-auth.ts,lib/engine.ts,types/next-auth.d.ts,app/api/auth/**/*.ts,app/api/chat/route.ts,app/api/campaign/**/*.ts,app/api/campaigns/**/*.ts,app/api/character/**/*.ts,app/api/characters/**/*.ts"
---

- Preserve separation between user authentication, session handling, internal-service authentication, and engine-side user resolution.
- Never trust browser-provided user identity fields or trusted-internal headers.
- Derive trusted identity from validated server-side session and established internal user-resolution flow.
- Keep OAuth client secrets, service credentials, and trusted headers server-side only.
- Never expose internal-service credentials in client bundles, browser responses, logs, or errors.
- Preserve existing validation behavior in this code path:
  - canonical Google issuer normalization
  - required provider subject
  - validated email and email_verified true
  - safe redirect filtering
- Normalize identity/profile fields only through existing helpers.
- Do not weaken validation to accept malformed or partial identity data.
- Preserve existing typed auth and gateway error patterns and mapped status behavior.
- Return useful but non-sensitive client errors.
- Do not log raw tokens, authorization headers, cookies, session payloads, or secrets.
- Preserve secure session/cookie behavior provided by current NextAuth configuration.
- Treat auth changes as security-sensitive and add focused rejection-path tests.
- Maintain the trust boundary: browser -> Next.js, then Next.js authenticates calls to the internal engine.
