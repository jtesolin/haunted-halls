---
name: Haunted Halls TypeScript Rules
description: Type safety and boundary validation rules for TypeScript in the Next.js gateway and UI.
applyTo: "**/*.ts,**/*.tsx"
---

- Follow the repository TypeScript configuration in tsconfig.json, including strict mode.
- Preserve strong typing; do not introduce any just to suppress errors.
- Use unknown at untrusted boundaries and narrow safely.
- Validate data entering from HTTP payloads, query parameters, environment variables, session data, engine responses, and parsed JSON.
- Prefer explicit transport and domain types where they make gateway contracts safer.
- Avoid unsafe type assertions and non-null assertions unless the invariant is established nearby.
- Preserve the current module/import style and the @/* path alias convention.
- Do not disable lint or TypeScript checks globally to force a change through.
- Keep functions and modules focused and easy to reason about.
- Prefer immutable values when it improves clarity and safety.
- Avoid duplicating contract types in inconsistent forms across app/api, lib, and types.
- Follow existing error typing and mapping patterns such as InternalEngine*Error and auth resolution errors.
