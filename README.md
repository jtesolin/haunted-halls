This is the public-facing Next.js Backend-for-Frontend for Haunted Halls.

## Project Status

Canonical project status for the two-repo system lives in the engine repository:

- [../haunted-halls-engine/docs/project-status.md](../haunted-halls-engine/docs/project-status.md)

This avoids duplicating roadmap and architecture status across both repositories.

## Getting Started

1. Install dependencies:

```bash
npm install
```

2. Copy environment defaults:

```bash
cp .env.example .env
```

3. Generate a strong `NEXTAUTH_SECRET`:

```bash
openssl rand -base64 32
```

4. Start the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Google Sign-In Setup

1. In Google Cloud Console, create or select a project.
2. Configure the OAuth consent screen (External or Internal, based on your org policy).
3. Create credentials of type OAuth 2.0 Client ID, selecting Web application.
4. Configure OAuth client values:

- Authorized JavaScript origin (local): `http://localhost:3000`
- Authorized redirect URI (local): `http://localhost:3000/api/auth/callback/google`
- Production redirect URI pattern: `https://<your-domain>/api/auth/callback/google`

5. Set these variables in `.env`:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `NEXTAUTH_SECRET`
- `NEXTAUTH_URL` (for local default: `http://localhost:3000`)

If you run the app on a different port, update `NEXTAUTH_URL` and register the matching origin and redirect URI in Google Cloud.

## Auth Notes

- Authentication uses Auth.js/NextAuth with Google OpenID Connect scopes: `openid email profile`.
- Session strategy is stateless JWT managed by NextAuth cookies.
- No Google tokens are stored in browser storage.
- After successful Google authentication, Next.js resolves an internal Haunted Halls user by calling the private FastAPI endpoint `POST /internal/auth/users/resolve` with the existing internal service credential.
- For user-scoped BFF requests, Next.js requires an authenticated Auth.js session with a resolved internal user ID and propagates that ID to FastAPI via `X-Haunted-Halls-User-Id`.
- User-scoped engine calls also include the existing service bearer credential; FastAPI trusts the user ID header only after service authentication succeeds.
- Browser-supplied identity headers are ignored and overwritten server-side.
- Browser-controlled identity inputs such as `user_id`, `owner_user_id`, `player_id`, email, provider subject hints, browser `Authorization`, and browser-supplied trusted-user headers are never authoritative.
- FastAPI owns the internal user record and identity keying. Users are keyed by canonical OIDC issuer + provider subject, while email/display name/avatar are mutable profile fields.
- Internal user resolution runs during initial sign-in and the returned internal user ID is stored in the server-managed Auth.js token/session for reuse.
- Existing development sessions created before this flow may lack an internal user ID; sign out and sign back in to refresh those sessions.
- Campaign ownership is persisted server-side in the FastAPI engine and comes from the trusted authenticated internal user context; the browser never supplies campaign ownership.
- FastAPI enforces domain authorization. Users can only list, read, update, delete, or play campaigns they own. Cross-user access and nonexistent resources both return `404`. Child resources (turns, events, memories) inherit authorization through their campaign. Legacy unowned campaigns are inaccessible through normal user APIs.
- Browser request payloads and query parameters do not carry account identity. User identity is derived from Auth.js session state and propagated internally as trusted server context only.
- Stateful BFF routes validate same-origin `Origin` headers when present, while keeping GET requests side-effect free.
- Unexpected internal auth/context failures are sanitized before reaching the browser, and generic `404` behavior is preserved for missing, cross-user, and legacy unowned campaign resources.
- Chat authorization and quota checks complete before turns, events, memories, summaries, or model-usage records are persisted.
- Semantic and summary memory retrieval stay scoped to an already-authorized campaign before prompt assembly.

## Internal Engine Token

- Generate the shared service token with `openssl rand -hex 32`.
- Set `INTERNAL_ENGINE_SERVICE_TOKEN` in the Next.js environment file and the engine `.env` file to the exact same value.
- Restart both servers after changing the token.
- Next.js is the only public application service; the FastAPI engine is intended to have no public ingress.
- Network isolation and the shared bearer token are complementary controls, not substitutes.
- To verify the protection, call the engine directly without the token and expect `401`, then call the same flow through Next.js and expect success.

## Local Security Verification

- `npm run test -- tests/api.auth-guard.test.ts`
- `npm run test`
- `npm run typecheck`
- `npm run lint`
- `npm run build`

## CI

GitHub Actions runs the frontend validation workflow on pull requests targeting `main`, on pushes to `main`, and manually via `workflow_dispatch`.

The workflow validates the repository commands used in local development:

- `npm run lint`
- `npm run typecheck`
- `npm test`
- `npm run build`

CI also builds the production Docker image as `Frontend / Docker Build`; it does not push the image.

## Local Docker Stack

The frontend repository owns the local Compose configuration and builds the sibling engine repository from `../haunted-halls-engine`.

Build and start both services:

```bash
docker compose build
docker compose up -d
```

The frontend is available at [http://localhost:3000](http://localhost:3000). View logs with `docker compose logs -f`, stop the stack with `docker compose down`, and rebuild after source changes with `docker compose up -d --build`.

Compose connects the BFF to FastAPI at `http://engine:8000` and injects the same local-only service token into both containers. Set `INTERNAL_ENGINE_SERVICE_TOKEN` in `.env` to replace the documented development default before testing authenticated flows. Google sign-in still requires real local OAuth settings; Compose does not bypass authentication.

SQLite is stored in the Docker-managed `engine-data` volume. `docker compose down` and image rebuilds preserve it. To intentionally reset local data, run `docker compose down -v` before starting the stack again.

These checks run on Node 24.18.0 (as configured in the workflow) and a standard GitHub-hosted Linux runner.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## License

The source code in this repository is licensed under the MIT License.

Game content, lore, prompts, characters, and narrative text are not included
under the MIT License unless explicitly stated otherwise.
