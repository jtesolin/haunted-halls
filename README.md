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

## D6A: custom frontend domain foundation

This D6A change adds the optional Terraform support for a Cloud Run custom-domain mapping on the public frontend without switching the active application authentication URL or altering the private engine URL model.

The domain mapping is intentionally gated behind a non-empty `frontend_custom_domain` value and `application_services_enabled = true`, so the deterministic Cloud Run frontend URL remains the live `NEXTAUTH_URL` default until a later D6 step performs the real cutover.

The current planned operational path is:

```text
Network Solutions
  registrar + manual nameserver delegation
        |
        v
Google Cloud DNS
  authoritative DNS for tesolin.us
  Terraform-owned records
        |
        v
Cloud Run
```

This D6A step only implements the optional Cloud Run domain-mapping Terraform foundation. It does not claim the custom domain is live, and it does not change the production auth configuration.

## D6B1: Google Cloud DNS foundation

This D6B1 phase creates the Google Cloud DNS public managed zone for `tesolin.us`, exposes the authoritative nameservers assigned by Google, and pauses for the manual registrar cutover. ZoneEdit remains the legacy provider until the operator updates the nameserver delegation at Network Solutions.

The sequence is intentionally explicit:

```text
Terraform preparation:
  Google Cloud DNS zone exists

Manual cutover:
  Network Solutions nameservers changed

Only after delegation:
  Google Cloud DNS becomes authoritative
```

This phase is intentionally minimal and does not create application recordsets yet. No A/AAAA/CNAME/TXT/MX/SRV records are added in this phase, and the Google site-verification TXT record is not created until the operator is ready to verify `tesolin.us` ownership after delegation.

### D6B1 sequence

1. Terraform creates the public `tesolin.us` Cloud DNS managed zone.
2. Terraform outputs the authoritative nameservers assigned by Google.
3. MANUAL: update the `tesolin.us` nameservers at Network Solutions to match the exact Google nameservers returned by Terraform.
4. Wait for delegation to propagate.
5. Verify Google Cloud DNS is authoritative for `tesolin.us`.

### ZoneEdit migration behavior

ZoneEdit remains the legacy DNS provider until the operator changes the Network Solutions delegation. There is no record-copying automation, no deletion of the legacy zone, and no effort to wait for support tickets. Because there are no known consumers of `tesolin.us` DNS beyond the Haunted Halls custom-domain work, the migration is intentionally narrow: create the Google Cloud DNS zone, expose the authoritative nameservers, and let the registrar delegation change manually.

### D6B2 / D6C follow-up

After the D6B1 delegation is complete, the next stages are:

1. Obtain Google's exact domain-verification TXT value.
2. Manage the TXT record through Terraform in Google Cloud DNS.
3. Review, merge, and apply the Terraform change.
4. Confirm the TXT record is publicly visible.
5. MANUAL: click Verify in Google and confirm ownership of `tesolin.us`.
6. Only then enable the Cloud Run domain mapping.
7. Retrieve the exact Cloud Run-required DNS records.
8. Manage those DNS record(s) in Google Cloud DNS through Terraform.
9. Wait for managed HTTPS certificate issuance.
10. Verify `https://haunted-halls.tesolin.us/api/health`.
11. Update the Google OAuth origin and callback for the custom domain.
12. In a later D6C step, switch `NEXTAUTH_URL` to the custom domain and verify browser login.

This D6B1 implementation does not enable the Cloud Run custom hostname yet, does not modify `NEXTAUTH_URL`, and does not change the existing Google OAuth configuration or engine base URL settings.

### Domain verification prerequisite

The mapping for `haunted-halls.tesolin.us` requires Google to recognize ownership of the parent domain `tesolin.us`. The operator can confirm the domain state with:

```bash
gcloud domains list-user-verified
gcloud domains verify tesolin.us
```

Google supplies the exact `google-site-verification=...` TXT value through the interactive Search Console flow. Terraform manages that public TXT record in Google Cloud DNS; after it is merged and applied, confirm the TXT is publicly visible before manually clicking Verify in Google. Keep the verification record in Terraform after ownership succeeds. Do not create the Cloud Run domain mapping until ownership is confirmed.

### DNS records after delegation

Once the Network Solutions nameservers point at Google Cloud DNS, the Cloud Run domain mapping will return the required DNS records for the Cloud Run mapping with an equivalent of:

```bash
gcloud beta run domain-mappings describe \
  --domain haunted-halls.tesolin.us \
  --region us-east1 \
  --project haunted-halls-development
```

The exact returned records are authoritative. D6B2 manages those records in Google Cloud DNS, and Google Cloud DNS is the authoritative owner of `tesolin.us` once delegation has been updated.

## Infrastructure and D4A Foundation

Haunted Halls now includes the first Terraform foundation for its planned Google Cloud deployment. This repository owns the shared GCP infrastructure for the browser-facing BFF and the internal engine deployment lifecycle. The D4A scope establishes a safe, reviewable control plane without creating billable Cloud Run or Cloud SQL resources yet.

### D4A architecture

```text
GitHub Actions
     |
     | OIDC
     v
Workload Identity Pool
     |
     +--> frontend deployer
     |       ^
     |       |
     |   haunted-halls repo
     |
     +--> engine deployer
             ^
             |
       haunted-halls-engine repo
```

The eventual runtime architecture is:

```text
Internet
   |
   v
Cloud Run — Next.js BFF
   |
   | authenticated service-to-service request
   v
Cloud Run — FastAPI Engine
   |
   v
Cloud SQL — PostgreSQL
```

D4A establishes the shared foundation for that design without creating the runtime services or the database.

### Local tools required

- Terraform 1.9.x
- Google Cloud CLI (`gcloud`)
- Application Default Credentials configured for a developer account
- An existing Google Cloud project with billing enabled

### GCP project and billing prerequisites

Before running Terraform locally, the developer must already have:

- an existing Google Cloud project ID
- a billing account that can be used for a budget guardrail
- permission sufficient to create GCS state buckets and basic Terraform-managed resources in that project

Set the target project with:

```bash
gcloud config set project <project-id>
gcloud auth application-default login
```

Never use a downloaded JSON service-account key as the default local workflow.

### Terraform state bootstrap

Terraform remote state is stored in a Google Cloud Storage bucket. Because Terraform cannot create the bucket that it already expects to use as its backend, run the bootstrap configuration first:

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply
```

Use the output bucket name in the main configuration:

```bash
cd ../
terraform init \
  -backend-config="bucket=<state-bucket>" \
  -backend-config="prefix=haunted-halls"
```

The bootstrap configuration creates a bucket with:

- uniform bucket-level access enabled
- public access prevention enforced
- versioning enabled
- force_destroy disabled

### Main Terraform workflow

The main stack lives under `infra/terraform` and manages shared foundation resources. Start from the example variables file:

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Fill in placeholders such as:

```hcl
project_id = "your-project-id"
region = "us-east1"
billing_account_id = "000000-000000-000000"
```

The main configuration does not read the state bucket name from `terraform.tfvars`. The bootstrap configuration's `state_bucket_name` variable creates the bucket; the main configuration receives that already-created bucket through backend initialization instead:

```bash
TF_STATE_BUCKET=<actual-state-bucket> make tf-init
```

or equivalently:

```bash
terraform -chdir=infra/terraform init \
  -backend-config="bucket=<actual-state-bucket>" \
  -backend-config="prefix=haunted-halls"
```

You can retrieve the bucket name created by bootstrap with:

```bash
terraform -chdir=infra/terraform/bootstrap \
  output -raw terraform_state_bucket_name
```

Then run:

```bash
make tf-fmt
make tf-validate
make tf-plan
make tf-apply
```

The configuration intentionally does not deploy the app yet; it only provisions the shared platform foundation.
The GCP service account IDs used by Terraform are intentionally short to meet Google Cloud account-id length limits, while each service account display name remains descriptive for future runtime and deployment ownership.
### Artifact Registry

D4A creates a regional Artifact Registry repository in `us-east1` named `haunted-halls`. The repository is suitable for future frontend and engine Docker images, and Terraform exposes the repository path for later CI/CD automation.

### Runtime and deployment identities

Terraform creates the following service-account account IDs:

- runtime service accounts:
  - `hh-frontend-runtime`
  - `hh-engine-runtime`
  - `hh-migration-runtime`
- deployment service accounts:
  - `hh-frontend-deployer`
  - `hh-engine-deployer`

These are the actual Google Cloud account IDs used by Terraform. Service account email addresses are created as `<account-id>@<project-id>.iam.gserviceaccount.com`.

The runtime identities are separated to support future Cloud Run workloads. The deployer identities are separate per repository and are bound to GitHub OIDC identity federation rather than JSON keys. There is intentionally no separate migration deployer service account in this D4A design.

### GitHub Workload Identity Federation

The Terraform configuration creates a GitHub Actions workload identity pool and OIDC provider using `https://token.actions.githubusercontent.com`. The trust is constrained to the trusted GitHub owner namespace and repository/main-branch context:

- `jtesolin/haunted-halls` -> frontend deployer
- `jtesolin/haunted-halls-engine` -> engine deployer

The trust model deliberately does not allow one repo to impersonate the other repo's deployment identity.

### Budget guardrail

D4A defines a project budget with a default monthly cap of `$20 USD` plus 50%, 90%, and 100% threshold alerts. The resource is managed as a billing budget and is skipped only when the billing account lacks permission or the necessary account-level setup is unavailable.

### Security expectations

This D4A foundation follows the security expectations for the project:

- no JSON service-account keys committed
- GitHub uses OIDC / Workload Identity Federation
- separate runtime identities per workload type
- separate frontend and engine deployment identities
- GCS Terraform state remains out of Git
- real `.tfvars` remains uncommitted
- no application Cloud Run / Cloud SQL resources yet

## D4B: Cloud SQL and Secret Manager

D4B adds production-target infrastructure for database and secrets without deploying the runtime services yet.

### Database

D4B creates a Cloud SQL PostgreSQL 16 instance named `haunted-halls-postgres` configured for low-cost development:

- **tier**: `db-f1-micro` (smallest shared-core)
- **availability**: ZONAL (not HA)
- **storage**: 10 GB SSD with autoresize
- **backups**: disabled for development; future production will enable PITR
- **deletion protection**: disabled for cost management; intentional for development

The database `haunted_halls` is managed by Terraform; application schema tables are owned by Alembic migrations, preserving the single source of truth for schema versioning:

```
Cloud SQL database (Terraform)
       ↓
Alembic migration job
       ↓
application schema (tables, constraints, etc.)
```

A PostgreSQL application user `haunted_halls_app` is created with an ephemeral-generated strong password that does not enter Terraform state.

### Secret Manager

D4B creates Secret Manager secrets for:

#### Terraform-generated secrets (written only, not stored in state)

- **hh-database-url** — SQLAlchemy PostgreSQL connection string with embedded application password
- **hh-internal-engine-service-token** — high-entropy bearer token for frontend/engine authentication
- **hh-nextauth-secret** — NextAuth session encryption key

These are generated during `terraform apply` using ephemeral random resources and write-only secret data, so their values never appear in:

- Terraform state
- Terraform plan files
- console output
- logs

Rotate them by incrementing the corresponding version variable in `terraform.tfvars`:

```hcl
database_password_version = 1  # increment to rotate
internal_service_token_version = 1  # increment to rotate
nextauth_secret_version = 1  # increment to rotate
```

Each version variable feeds both the ephemeral value's `password_wo_version` / `secret_data_wo_version` argument, which is what actually triggers the Google provider to write a new value. Incrementing `database_password_version` regenerates the ephemeral database password, updates the Cloud SQL user's password, and writes a new `hh-database-url` secret version (the connection string embeds the same password). Incrementing `internal_service_token_version` or `nextauth_secret_version` regenerates and writes only that corresponding secret. Leaving a version unchanged leaves the corresponding secret untouched.

#### Operator-populated secrets (containers only, no Terraform data)

- **hh-openai-api-key** — OpenAI API credential (populated by operator)
- **hh-google-client-secret** — Google OAuth client secret (populated by operator)

These are created as empty Secret Manager containers during Terraform apply. The operator populates them securely after infrastructure is ready:

```bash
# Example: populate OpenAI API key
read -s OPENAI_SECRET
printf '%s' "$OPENAI_SECRET" | \
  gcloud secrets versions add hh-openai-api-key --data-file=-
unset OPENAI_SECRET
```

### Secret-level IAM

Runtime identities receive `roles/secretmanager.secretAccessor` on only the secrets they need:

| Runtime | Secrets |
|---------|---------|
| `hh-frontend-runtime` | hh-internal-engine-service-token, hh-nextauth-secret, hh-google-client-secret |
| `hh-engine-runtime` | hh-database-url, hh-internal-engine-service-token, hh-openai-api-key |
| `hh-migration-runtime` | hh-database-url |

### Cloud SQL connectivity

Cloud SQL intentionally has a public IPv4 address, restricted to Cloud SQL Auth Proxy / connector-only traffic:

- `ipv4_enabled = true` — the instance has a public IP; this is the intended initial connectivity design, not an oversight
- `connector_enforcement = "REQUIRED"` — direct PostgreSQL connections over that public IP are rejected; only the Cloud SQL Auth Proxy or connector-based connections are accepted
- zero `authorized_networks` entries are configured, so no IP range is separately allowlisted for direct access
- no direct PostgreSQL port exposure

Private IP, Private Service Access, VPC connectors, PSC, or NAT are deliberately out of scope for D4B/D4C and may be evaluated later; introducing them now would materially expand the current staged architecture.

This is compatible with the planned D4C Cloud Run Unix-socket Cloud SQL integration, which connects through the Cloud SQL Auth Proxy sidecar/connector rather than a direct TCP connection.

### Terraform version and provider upgrade

D4B requires:

- **Terraform >= 1.11.0** for write-only arguments (`password_wo`, `password_wo_version`, `secret_data_wo`, `secret_data_wo_version`)
- **Google provider ~> 7.x** for reliable write-only secret support
- **Random provider >= 3.7.0, < 4.0.0** — the `ephemeral "random_password"` resource requires Random provider 3.7.0 or newer

CI updated to Terraform 1.11.0; local `.terraform.lock.hcl` locks the specific Google provider version. Run `terraform init -upgrade` to sync providers after a version constraint change.

The `google` provider explicitly sets `user_project_override = true` and `billing_project = var.project_id`, so API usage (including APIs like Billing Budgets that require an explicit quota project) is billed/quota-charged to the configured GCP project rather than relying on ambient Application Default Credentials configuration.

### No runtime deployment yet

D4C Terraform now configures the first-deployment runtime, but it has not been applied. The code defines:

- public Cloud Run service `haunted-halls-frontend` as the browser-facing boundary
- private IAM-protected Cloud Run service `haunted-halls-engine`
- migration job `haunted-halls-migrate`, using the same engine image and explicit `python -m alembic upgrade head` command
- separate frontend, engine, and migration runtime service accounts
- minimum instances of `0`, maximum instances of `2`, request-based CPU allocation, and modest `1` CPU / `512Mi` resources
- Cloud SQL connector integration mounted at `/cloudsql` for the engine and migration job

The frontend BFF keeps the existing application bearer token in `Authorization`. When `ENGINE_ID_TOKEN_AUDIENCE` is configured, it obtains an ADC-backed Google-signed ID token for that audience and sends it only in `X-Serverless-Authorization`; local Compose leaves that header absent. The engine remains private, and only `hh-frontend-runtime` receives its `roles/run.invoker` binding. The frontend receives public Cloud Run invocation access.

The configured deterministic URLs are derived from the project number and region and are used for `NEXTAUTH_URL`, `ENGINE_BASE_URL`, and `ENGINE_ID_TOKEN_AUDIENCE`. Before a real apply, create the production Google OAuth Web Application using the Terraform output frontend URL and its `/api/auth/callback/google` callback, populate `hh-google-client-secret`, and provide immutable frontend/engine image references plus the operator-managed secret versions in ignored `terraform.tfvars`.

The intended manual first-deployment order is:

1. Build and push reviewed immutable images.
2. Keep `application_services_enabled = false`.
3. Run `terraform plan` and `terraform apply`.
4. Terraform creates or updates `haunted-halls-migrate`, but does not create the engine or frontend services or their IAM bindings.
5. Execute `haunted-halls-migrate` manually and wait for successful completion.
6. Set `application_services_enabled = true` and provide the frontend image and production OAuth values.
7. Run a fresh `terraform plan`.
8. Apply to create or update the engine and frontend services and their IAM bindings.
9. Verify runtime behavior.
10. Run a final `terraform plan`; it should report `No changes`.

Creating the migration job is not equivalent to successfully executing the migration. The gate keeps application service presence separate from migration execution while preserving the normal Terraform workflow. After the first successful migration and deployment, `application_services_enabled = true` is the steady-state value; future D5 automation will still execute migrations before deploying new application revisions. No Cloud Run resources have been created by this implementation pass, and custom domains, DNS, VPC expansion, and GitHub Actions deployment automation remain out of scope.

## D5A: GitHub Actions CD Ownership Foundation

D5A establishes the operational boundary between Terraform-managed infrastructure and GitHub Actions-driven deployment.

### Deployment vs. Configuration Ownership

Terraform owns all Cloud Run configuration:

- Service and job creation and deletion
- Container specifications (ports, startup probes, environment variables)
- Cloud SQL integration and mounting
- Secret Manager integration and versioning
- Scaling configuration
- Service account assignment and IAM

GitHub Actions CD workflows own **only image revisions**:

- Building application Docker images
- Pushing immutable SHA-tagged images to Artifact Registry
- Updating Cloud Run service and job image attributes to point to new revisions
- Executing database migrations before engine rollout

This separation prevents normal application deployments from requiring a Terraform `apply`.

### Deployment Service Accounts

D5A adds least-privilege IAM bindings for the two deployment service accounts:

#### Frontend Deployer (`hh-frontend-deployer`)

- **Artifact Registry**: `roles/artifactregistry.writer` on the `haunted-halls` repository
  - Allows pushing and tagging images from CI/CD
- **Cloud Run**: `roles/run.developer` on `haunted-halls-frontend` service only
  - Allows updating the frontend Cloud Run service (including its image); CD workflows should only change the image field.
- **Service Account User**: `roles/iam.serviceAccountUser` on `hh-frontend-runtime`
  - Allows deployment workflows to run Cloud Run operations as the frontend runtime identity
- **Scope**: Frontend repository only; no access to engine, migrations, or secrets

#### Engine Deployer (`hh-engine-deployer`)

- **Artifact Registry**: `roles/artifactregistry.writer` on the `haunted-halls` repository
  - Allows pushing and tagging images from CI/CD
- **Cloud Run**: `roles/run.developer` on:
  - `haunted-halls-engine` service — allows updating the service (including its image); workflows should only change the image field
  - `haunted-halls-migrate` job — allows updating the job (including its image) and executing migrations
- **Service Account User**: `roles/iam.serviceAccountUser` on `hh-engine-runtime` and `hh-migration-runtime` — allows deployment workflows to impersonate the runtime identities
  - Allows deployment workflows to run Cloud Run operations as those service accounts
- **Scope**: Engine repository only; no access to frontend or user secrets

Neither deployer receives:

- `roles/artifactregistry.admin`, `roles/run.admin`, or project-wide privileges
- Secret Manager accessor roles (deployment does not decrypt secrets; runtime identities do)
- Cloud SQL client access
- Project Editor or Owner

### Workload Identity Federation Hardening

The existing GitHub OIDC provider condition is now restricted to deployment workflows:

```
attribute.repository_owner == "jtesolin"
AND attribute.ref == "refs/heads/main"
AND one of:
  - attribute.repository == "jtesolin/haunted-halls" AND attribute.workflow_ref == "jtesolin/haunted-halls/.github/workflows/deploy.yml@refs/heads/main"
  - attribute.repository == "jtesolin/haunted-halls-engine" AND attribute.workflow_ref == "jtesolin/haunted-halls-engine/.github/workflows/deploy.yml@refs/heads/main"
```

Deployments can only run from `main` branch and only from dedicated `deploy.yml` workflows in each repository. CI workflows, pull requests, arbitrary branches, forks, and other workflow files are not permitted to authenticate.

### Future Deployment Workflow Contract

D5 deployment workflows are not yet implemented. When they are, the expected behavior is:

**Engine deployment workflow:**

1. Trigger on push to `main` or manual dispatch
2. Authenticate using GitHub OIDC → `hh-engine-deployer`
3. Build immutable engine image, tag with commit SHA
4. Push to Artifact Registry, resolve sha256 digest
5. Update `haunted-halls-migrate` job image to new digest
6. Execute migration job and wait for completion
7. If migration fails, stop (do not deploy engine)
8. Update `haunted-halls-engine` service image to new digest
9. Wait for readiness
10. Run authenticated health/smoke test

**Frontend deployment workflow:**

1. Trigger on push to `main` or manual dispatch
2. Authenticate using GitHub OIDC → `hh-frontend-deployer`
3. Build immutable frontend image, tag with commit SHA
4. Push to Artifact Registry, resolve sha256 digest
5. Update `haunted-halls-frontend` service image to new digest
6. Wait for readiness
7. Run public health/smoke test

Each repository deploys only its own application responsibility. The frontend workflow cannot deploy the engine, and the engine workflow cannot deploy the frontend.

### Image Lifecycle Ownership

Cloud Run service and job image attributes are now managed by Terraform's lifecycle `ignore_changes` for the image attribute only. This prevents Terraform from:

- Reverting image changes made by CD workflows
- Forcing unnecessary deployments when no configuration has changed

Terraform preserves all other configuration:

- Environment variables
- Secret references and versions
- Cloud SQL mounts
- Service account assignments
- Scaling
- Probes and startup configuration
- commands and arguments (for the migration job, the alembic command is Terraform-owned)

### Production Deployment Concurrency

Each repository serializes its own production deployments independently using GitHub Actions concurrency groups. The current production deployment groups are:

```yaml
# Frontend
concurrency:
  group: haunted-halls-frontend-production
  cancel-in-progress: false

# Engine
concurrency:
  group: haunted-halls-engine-production
  cancel-in-progress: false
```

GitHub Actions concurrency groups are repository-scoped, so using the same group name in two different repositories would not provide cross-repository serialization. Never use `cancel-in-progress: true` for production deployments; a newer commit must not cancel a migration or rollout halfway through. Queued deployments are preferred to cancellation.

### Rollback Model

Application rollback in D5 means deploying a prior known-good image revision. Database migrations are not automatically downgraded; the system follows the expand-contract principle for schema changes. Rollback automation is out of scope for D5A; it will be addressed in later work.

## CI

GitHub Actions runs the frontend validation workflow on pull requests targeting `main`, on pushes to `main`, and manually via `workflow_dispatch`.

The workflow validates the repository commands used in local development:

- `npm run lint`
- `npm run typecheck`
- `npm test`
- `npm run build`

CI also builds the production Docker image as `Frontend / Docker Build`; it does not push the image.

The workflow now includes a credential-free Terraform validation job that runs:

- `terraform fmt -check -recursive`
- `terraform init -backend=false`
- `terraform validate`

for both the bootstrap and main Terraform stacks.

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
| `make docker-migrate` | `docker compose run --rm --build migrate` |
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
# docker compose run --rm --build migrate
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

PostgreSQL data persists in the Docker-managed `postgres-data` volume. `docker compose down` preserves it across restarts and image rebuilds. To intentionally reset local data, run `docker compose down -v` or `make docker-reset-db` before starting the stack again.

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
