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

The Compose stack includes:

* **PostgreSQL 16** — persistent database service with health check.
* **Migrate** — one-shot service that runs `alembic upgrade head` before the engine starts.
* **Engine** — FastAPI application, depends on migration success.
* **Frontend** — Next.js BFF, depends on engine health.

The frontend is available at [http://localhost:3000](http://localhost:3000). View logs with `docker compose logs -f`, stop the stack with `docker compose down`, and rebuild after source changes with `docker compose up -d --build`.

Compose connects the BFF to FastAPI at `http://engine:8000` and injects the same local-only service token into both containers. PostgreSQL data persists across normal `docker compose down` / `docker compose up` cycles; use `make docker-reset-db` to destroy the database and start fresh. Set `INTERNAL_ENGINE_SERVICE_TOKEN` in `.env` to replace the documented development default before testing authenticated flows. Google sign-in still requires real local OAuth settings; Compose does not bypass authentication.

### Runtime Configuration

The images are environment-agnostic; local configuration is injected at container runtime from two host files that are never copied into the images:

- `haunted-halls/.env` — frontend and Compose-level configuration (`INTERNAL_ENGINE_SERVICE_TOKEN`, NextAuth, Google OAuth, ports).
- `haunted-halls-engine/.env` — engine-local runtime configuration such as `OPENAI_API_KEY`, `AI_ENABLED`, and `DEFAULT_MODEL_NAME`, loaded through Compose `env_file` (optional; the stack still starts without it).

Compose values declared under `environment:` take precedence over `env_file:`, so `DATABASE_URL` is pinned to the PostgreSQL service connection string and `INTERNAL_ENGINE_SERVICE_TOKEN` always comes from the frontend `.env`, keeping both services in agreement. PostgreSQL credentials default to development-only values; see the `postgres` service in [docker-compose.yml](docker-compose.yml) for configuration options. Without a valid `OPENAI_API_KEY` or `AI_ENABLED=true` in the engine `.env`, the engine responds with stub narration.

### Make Targets

The frontend repository owns the Compose lifecycle; each target is a thin wrapper over the Docker command shown next to it.

| Target | Command |
| --- | --- |
| `make docker-build` | `docker compose build` |
| `make docker-up` | `docker compose up -d` |
| `make docker-down` | `docker compose down` |
| `make docker-logs` | `docker compose logs -f` |
| `make docker-ps` | `docker compose ps` |
| `make docker-config` | `docker compose config` |
| `make docker-migrate` | `docker compose run --rm migrate` |
| `make debug-build` | `docker compose -f docker-compose.yml -f docker-compose.debug.yml build` |
| `make debug-up` | `docker compose -f docker-compose.yml -f docker-compose.debug.yml up` |
| `make debug-down` | `docker compose -f docker-compose.yml -f docker-compose.debug.yml down` |
| `make debug-logs` | `docker compose -f docker-compose.yml -f docker-compose.debug.yml logs -f` |
| `make debug-config` | `docker compose -f docker-compose.yml -f docker-compose.debug.yml config` |
| `make docker-reset-db` | `docker compose down -v` — **destructive**, deletes all Compose volumes (including `postgres-data`) |

`make docker-down` and `make debug-down` never remove volumes; only `make docker-reset-db` does.

### Migration Service

The `migrate` service is a one-shot container that runs before the engine starts:

```bash
alembic upgrade head
```

It uses the same engine image, configuration, and PostgreSQL connection as the running engine, ensuring migrations stay synchronized with application code. If migrations fail, the engine does not start and the Compose stack will not reach healthy status.

To run migrations explicitly:

```bash
make docker-migrate
# docker compose run --rm migrate
```

### Local Debugging

[docker-compose.debug.yml](docker-compose.debug.yml) layers development-only settings on top of the base file: debug Dockerfile stages, source bind mounts, and debugger ports. Everything else (environment, engine URL, auth, PostgreSQL database, health checks) stays in [docker-compose.yml](docker-compose.yml).

Start the debug stack:

```bash
make debug-up
# docker compose -f docker-compose.yml -f docker-compose.debug.yml up
```

Then attach the debuggers from VS Code's Run and Debug view:

- **Attach: Haunted Halls Frontend (Docker)** — Node inspector on `127.0.0.1:9229`, mapping `${workspaceFolder}` to `/app`. Use it for server components, route handlers, and other BFF code.
- **Attach: Haunted Halls Engine (Docker)** — `debugpy` on `127.0.0.1:5678`, defined in the engine repository's `.vscode/launch.json`.

Both debuggers listen without blocking startup, so containers become healthy before you attach, and you can attach or detach at any time. Because the repositories are separate VS Code folders, attach each configuration from its own folder rather than through a compound configuration. Client-side React code is debugged with browser dev tools or the **Debug: Haunted Halls Client (Chrome)** configuration; the Node debugger only covers server-side code.

Debugger ports bind to `127.0.0.1` and exist only in the debug override, never in the production image or the normal stack.

Frontend source edits hot-reload through the bind mount, so rebuilds are not needed for ordinary changes. Engine source is bind-mounted read-only and runs without Uvicorn reload (subprocess reloading makes breakpoints unreliable), so restart the engine container to pick up Python changes:

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml restart engine
```

Run `make debug-build` after Dockerfile or dependency changes. The normal and debug stacks use distinct image tags (`:local` and `:debug`) so they never reuse each other's images.

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
