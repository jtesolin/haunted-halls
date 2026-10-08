# Isolated per-PR preview resources and secret interface

This is a **separate Terraform root**, not a module in the foundation or the
production/staging root. The trusted default-branch workflow now uses it for
frontend PR preview creation and updates. The lifecycle creates/reuses the
database, prepares a new secret generation, migrates before service rollout,
verifies the deployed digests/privacy, and maintains one PR comment. Close/merge
teardown remains intentionally deferred. 41A's merged server-only IAP
authentication is consumed unchanged.

## Ownership and fixed boundary

- Project: `hh-preview-458395246135`; region: `us-east1`.
- Backend bucket: `hh-preview-458395246135-per-pr-tf-state`.
- Backend impersonation: `hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com`.
- State prefix: `previews/<repository_key>-pr-<pull_request_number>`.
- Repository key: exactly `web` (frontend repository) or `engine` (reserved
  namespace matching the foundation DB provisioner). This slice does not
  implement engine PR previews.
- PR identifier: canonical decimal string `1..999999999`; no leading zeros,
  signs, fractions, whitespace, or path components. The longest service/job
  name is 31 characters (below Cloud Run's 49-character bound); the longest
  database name is 33 characters (below PostgreSQL's 63-character bound).

For `web` PR `123`, this state owns only:

| Resource | Name |
| --- | --- |
| Frontend service | `hh-web-pr-123-frontend` |
| Private engine service | `hh-web-pr-123-engine` |
| Alembic job | `hh-web-pr-123-migrate` |
| NextAuth secret container | `hh-web-pr-123-i-<32 lowercase hex incarnation>-nextauth` |
| Internal service-token container | `hh-web-pr-123-i-<32 lowercase hex incarnation>-internal-token` |
| Database URL container | `hh-web-pr-123-i-<32 lowercase hex incarnation>-database-url` |

Terraform owns only the three incarnation-qualified containers, labels,
runtime Secret Accessor grants and consumers pinned to explicit numeric
versions. The trusted preparer creates versions; Terraform has no payload
variables or SecretVersion resources. Runtime and additive resource-scoped IAM
is:
frontend runtime -> engine invoker, IAP service agent -> frontend invoker,
explicit user/group testers -> this frontend's IAP resource, and five secret
accessor grants (frontend: NextAuth/token; engine: token/DB URL; migration: DB
URL only). There are no authoritative IAM policies that replace other members.
No job invoker binding is needed: the existing preview-only `roles/run.admin`
deployer can execute the job. The job has no IAP or public invocation grant.

The foundation owns all APIs, service accounts, Cloud SQL connectivity IAM,
shared preview credentials/OpenAI secret, artifact repository, state buckets,
WIF, and the fixed trusted DB provisioner. This root does not import, query,
modify, or destroy them, create DBs/users, or own project-level IAM.

## Runtime and immutable inputs

Use the accepted foundation metadata for `preview_project_number`; the digits
in the project **ID** are not evidence of its project **number**. The trusted
preflight verifies the fixed preview project number against the generated
frontend URL before deployment.

Runtime service accounts are the existing `hh-preview-frontend`,
`hh-preview-engine`, and `hh-preview-migration` in the preview project.
Engine/job attach only
`haunted-halls-development:us-east1:haunted-halls-postgres`; frontend has no SQL
attachment or credential. Services use 1 CPU, 512 MiB, request-based CPU,
concurrency 20, min instances 0, and max instances 2. The job uses one task,
parallelism 1, 1 CPU/512 MiB, a 600-second timeout and no retries.

Engine ingress remains reachable for authenticated server-to-server calls,
but its IAM invoker check is enabled and only the preview frontend receives a
resource grant. "Private" here means IAM-authenticated, not internal-only ingress:
the existing BFF uses Cloud Run ID tokens plus the existing internal-service
bearer token. The frontend has direct Cloud Run IAP enabled, IAM checks enabled,
and no public grant.

The frontend sets only server-side `AUTH_MODE=iap`, exact
`IAP_EXPECTED_AUDIENCE=/projects/NUMBER/locations/us-east1/services/FRONTEND`,
`NEXTAUTH_URL=https://FRONTEND-NUMBER.us-east1.run.app`, matching
`ENGINE_BASE_URL`/`ENGINE_ID_TOKEN_AUDIENCE` from the engine's computed URI,
and the two required secret references. No Google OAuth credentials, per-PR
callback registration, unsigned-header identity, E2E seam, or public auth
bypass is introduced.

Accepted image formats are strictly:

- `us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/frontend@sha256:<64 lowercase hex>`
- `us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/engine@sha256:<64 lowercase hex>`

Tags, other repositories, partial/uppercase digests, and whitespace are rejected.
There is no mutable image fallback or ignored image drift. The same frozen
engine digest is used by the engine **and** the migration job. The trusted
workflow captures the one Ready/latest serving revision from
`haunted-halls-engine-staging`, verifies the source Artifact Registry digest,
and copies the image into this preview-only repository without rebuilding it.
The copy must retain the exact source manifest digest. The untrusted CI artifact
is bound to its repository, PR, exact head SHA, workflow run and artifact ID
before it is pushed to the frontend repository.

## Trusted secret preparation

The fixed workflow
[`preview-secret-prepare.yml`](../../../.github/workflows/preview-secret-prepare.yml)
can run only as a dispatch on the reviewed default branch (the deployment
workflow invokes it for each successful preview create/update; manual
reconciliation remains available). Before WIF
authentication it requires exact PR number/repository metadata, state `open`
`draft=false`, and the expected exact PR head SHA; missing or stale metadata
fails closed. Draft PRs remain CI-only. It checks out the dispatch's `main` SHA and authenticates
through exact-workflow-ref WIF as
`hh-preview-secret-preparer@hh-preview-458395246135.iam.gserviceaccount.com`.
One fixed-repository eligibility validator checks fresh GitHub API responses
initially, immediately before WIF authentication, and again after authentication
immediately before invoking the preparer. Each metadata file is deleted after
use, including on failure. A late closed/draft or malformed response stops the
job without invoking the preparer or creating preview state.
It accepts only the frontend repository key, canonical PR number, a
32-character lowercase-hex PR incarnation, and a positive generation number.
The tool derives all three Secret Manager container names itself; it accepts no
project, secret path, database, SQL endpoint, command, or payload override.

Before authentication, the privileged job installs its complete Python 3.12
Linux x86_64 runtime dependency closure from the committed, reviewed
[`requirements.lock`](../../../tools/preview-secret-preparer/requirements.lock)
using `pip --require-hashes --only-binary=:all:`. Every package is exactly
pinned with a SHA-256 hash for its compatible wheel. The small
`requirements.txt` is development input only, not a workflow install source;
lock generation never runs in the privileged job. Normal CI verifies the lock
in an isolated environment without cloud credentials.

For `web` PR `123`, the exact database URL payload is:

```text
postgresql+psycopg://haunted_halls_preview_app:<64 lowercase hex>@/haunted_halls_web_pr_123?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres
```

The preparer generates separate cryptographically strong 32-byte NextAuth and
internal-token values. It reads the existing preview-only
`hh-preview-db-app-password` at runtime, validates its 64-hex representation,
and assembles the URL above. It has `secretmanager.versions.access` only on
that exact preview secret. Production/staging secrets, SQL administration and
credential fallback are not permitted.

The preparer verifies the fixed project ID and actual project number, exact
WIF service-account identity, and each derived container's ownership labels.
It returns only the three numeric version identifiers and non-secret identity
metadata. Payloads never enter Terraform variables/state/plans, GitHub
artifacts, PR comments, logs, outputs or summaries. The migration job receives
only the pinned PR DB URL; it runs `alembic upgrade head`, not app startup, and
needs no model or internal-token access.

### Incarnations, generations and durable ledger

The PR incarnation is a trusted, immutable 128-bit lowercase-hex identifier
for one preview-environment lifetime. The three parent containers are fixed
per incarnation; generation numbers distinguish individual appends inside
those containers. This avoids creating extra containers for every ordinary
secret generation while ensuring a fully destroyed/recreated environment has
different container names. The first targeted Terraform apply persists the incarnation with generation
`0` before database creation. After the DB exists, a read-only ledger
reconciliation distinguishes a safe pre-reservation retry from a completed or
ambiguous generation; Terraform persists the attempted generation before the
preparer runs. Later updates increment only after confirming the prior
generation is complete. A migration failure therefore cannot make a completed
generation look unused, and an incomplete append is never replayed. While the state remains, PR
updates and reopenings retain its incarnation and database. A future teardown
must allocate a new identifier only after the old preview is removed.

The preview foundation owns the separate
`hh-preview-458395246135-pr-secret-ledger` bucket. It is private, versioned,
protected from normal Terraform destruction, and separate from both Terraform
state buckets. Immutable objects are keyed by repository, PR, incarnation,
generation and marker:

```text
secret-preparation/v1/web-pr-<N>/<incarnation>/generations/<G>/
  reservation.json
  nextauth.intent.json
  nextauth.result.json
  internal-token.intent.json
  internal-token.result.json
  database-url.intent.json
  database-url.result.json
  reconciliation-required.json  (only on ambiguity, when writable)
  complete.json
```

Markers contain only identity, expected container names and marker kind;
reservation additionally has a non-secret unique reservation ID and results
add only a numeric version. Every create uses `if_generation_match=0` with
retries disabled. No object is replaced or deleted, and exact deterministic
GETs reconstruct state without listing. An ambiguous create is established
only if GET returns exactly the expected content. A definite existing-object
conflict is never adopted as a fresh attempt. Versioning is defense in depth;
correctness does not depend on replacing versioned objects. The preparer has
only `storage.objects.get/create`, never delete/list. PR teardown cannot erase
ledger history.

Before creating any ledger marker, the preparer derives/validates names, checks
all three container labels, generates and validates distinct NextAuth/internal
values, reads and validates the fixed DB password, builds the exact PR DB URL,
and establishes its in-memory payload map. Failure in that preparation is safe
to retry: there is no reservation, intent or external append. A single `finally`
path best-effort wipes all four sensitive bytearrays on success or any failure,
including password/URL preparation and reservation rejection.

After payload preparation, the reservation is non-expiring and exclusive for
the incarnation. A generation
can be reserved only once; generation N requires the immutable complete marker
and results of N-1. Skips fail closed. Before each external append, its intent
is durable; a numeric result must be durable before the next append.
Only after all results may `complete.json` be created.
Reconstructed states are `reserved`, `writing`,
`complete`, and `reconciliation-required`. A crash or unresolved state blocks
new writes; no lease timeout or automatic lock takeover exists.
Failures after durable reservation retain these conservative no-retry and
reconciliation requirements; pre-reservation retry safety does not permit
post-reservation replay.
An unestablished intent also attempts the reconciliation marker and raises
reconciliation-required without appending that role. If that marker fails,
the durable reservation still blocks replay and subsequent generations.

Secret Manager `addVersion` has no operation idempotency key. SDK retries are
disabled. If any response is ambiguous, the preparer makes no second
`addVersion`, marks the generation `reconciliation-required` when possible,
and stops. The read-only `reconcile` mode lists ledger state, container labels
and version numbers/states/create times; it never accesses payloads. Because
shared per-incarnation containers cannot unambiguously correlate an
unrecorded append to one generation, reconciliation reports an operator
disposition requirement instead of guessing. A successful append whose result
cannot be established also raises reconciliation-required, even if the
ambiguity marker cannot be written: the existing intent blocks replay.
GCS create-only coordination does **not** make `addVersion` idempotent or
fence an external append. Reconciliation never resumes or retries an append.
Correctness takes priority over recovery availability.

The deployer separately retains parent-project `secretmanager.secrets.create`
and the Secret-only prefix-conditioned `previewPerPrSecretLifecycle` role
(`secrets.get/update/delete/getIamPolicy/setIamPolicy`) for Terraform metadata,
runtime IAM and teardown. It has no version permissions or shared password
access. The dedicated preparer alone reads the fixed DB app-password secret;
former engine/migration direct grants are removed. Runtime identities instead
read their exact PR secrets (and the engine's existing preview OpenAI secret).

### Numeric Terraform interface

The per-PR root requires:

- `nextauth_secret_version`
- `internal_engine_service_token_version`
- `database_url_secret_version`

Each is a required string containing a canonical positive decimal integer.
`latest`, aliases, zero, signs and leading zeroes are rejected. Cloud Run
services and the migration job pin these exact values. OpenAI remains pinned
separately to its existing preview-only numeric version.

## Backend identity consistency

Backend configuration cannot interpolate input variables. Its bucket and
impersonation identity are fixed here; **prefix must be supplied at init**.
`backend_state_prefix` separately validates agreement with the resource identity,
but Terraform cannot inspect its own selected backend from that input.
The trusted deployment workflow enforces both checks before stateful
operations:

1. Validate trusted repository/PR identity before init. Use a fresh, private,
   PR-specific working directory and `TF_DATA_DIR`, never a shared initialized
   checkout or a Terraform workspace in the foundation backend. Require the
   default workspace; do not let `TF_WORKSPACE` select another state object.
2. Initialize the fixed bucket/identity with
   `-backend-config="prefix=previews/web-pr-123"` and set matching
   `repository_key`, `pull_request_number`, `pr_incarnation`, and
   `backend_state_prefix` inputs. Supply the three numeric version inputs as
   positive decimal strings even for a targeted container bootstrap; they are
   not written by that target.
   Do not use `-migrate-state`, reuse another PR's state, or import resources.
3. Run the offline guard on **backend metadata**, not remote resource state:

   ```bash
   python3 infra/terraform/preview-pr/check_backend.py web 123 \
     --metadata "$TF_DATA_DIR/terraform.tfstate"
   ```

   This checks GCS type, bucket, exact prefix, exact deployer and no impersonation
   delegates without echoing metadata. Missing/malformed metadata or mismatches
   fail closed. Run it again before plan/apply/destroy and before deleting a
   state object. Do not substitute this check for resource-state reconciliation.
4. Ensure the provider's ADC is also the expected preview deployer: backend
   impersonation does not set provider credentials. Authenticate only on a fresh
   trusted default-branch runner via the foundation's exact-workflow-ref WIF.
   Never run PR-controlled Terraform or scripts after authentication.

The workflow runs on a fresh default-branch runner, uses a unique `TF_DATA_DIR`,
and rechecks the backend metadata before every plan/state operation. It never
uses `-migrate-state`, imports resources, or selects a non-default workspace.
This implementation PR itself does not trigger the privileged `workflow_run`
deployment path; a live preview is created only for eligible PRs after the
trusted workflow is present on `main`.

## Create/update lifecycle ordering

Configure the repository Actions variables `PREVIEW_IAP_TESTERS` as a
comma-separated set of explicit `user:email` and/or `group:email` principals
and `PREVIEW_DB_PROVISIONER_URL` as the fixed provisioner's HTTPS `run.app`
URL. The trusted job rejects missing/malformed values and has no public-access
or fallback identity. Do not put credentials or secret payloads in these
variables.

There is deliberately no "migration succeeded" Terraform flag: creating a job
does **not** execute it or prove schema readiness, and an apply dependency
cannot model successful execution. Do not use a runtime-enable toggle that
would destroy a healthy preview during an update.

The required order is:

1. Normal CI must pass. For a ready same-repository PR, a credential-free job
   builds the exact PR-head image and uploads only the image archive and its
   checksum. The trusted `workflow_run` job verifies the run/workflow/PR/SHA,
   unique artifact ID and GitHub artifact digest before authentication. Draft,
   fork, stale-head and closed PR runs do not deploy.
2. In the fresh default-branch runner, revalidate the PR and capture exactly
   one Ready/latest serving staging engine revision. Resolve its immutable
   source digest and copy that artifact into the preview registry without
   rebuilding or mutating staging. Confirm the destination retains the digest.
   Push the exact PR image artifact, and resolve its immutable preview digest.
3. Initialize/reconcile only `previews/web-pr-<N>` in the fixed per-PR bucket.
   Read the incarnation/generation from the three state-owned secret
   containers, or create a new trusted incarnation for the first deployment.
   Reconcile only the fixed container/runtime-IAM target inventory using a
   saved plan that has no destructive or unexpected actions.
4. Create the deterministic empty database if absent, or reuse it unchanged.
   Dispatch the fixed secret-preparation workflow with the expected PR SHA,
   incarnation, and next generation. It writes exactly one generation through
   the dedicated secret preparer and returns only the three numeric versions.
5. Target only the migration job (and its explicit secret/IAM prerequisites),
   using the frozen engine digest and explicit numeric DB URL version. The job
   runs `alembic upgrade head` followed by `alembic current --check-heads`.
   Wait for exactly one successful task and stop on any failure.
6. Only after migration succeeds, create a fresh full plan and reject any
   unexpected resource or delete action before applying. Update the services
   with the exact frontend/engine digests and numeric secret versions. Verify
   both services Ready, exact digests, database/migration success, IAP
   interception, engine unauthenticated denial, and configured IAP testers.
7. Revalidate the PR and create or update its one stable-marker
   `Preview Environment` comment with non-sensitive metadata. A failed
   migration or Terraform operation never triggers an automatic destroy.
   Close/merge teardown, DB drop, and ledger retention remain out of scope.

## Accepted IAM boundaries

The prior preview-deployer/WIF/IAM phase is live-accepted and reconciled for its
reviewed scope. This code-only change does not apply the new preparer identity,
role or ledger grants. Do not weaken either accepted fail-closed limitation:

- No approved outside-preview IAP WebService canary exists. Do not create one
  or broaden IAP authority to force that negative check.
- The deployer's Artifact Registry reader intentionally lacks
  `artifactregistry.repositories.getIamPolicy`. Do not broaden its source
  registry grant.

The preparer identity is deliberately separate from the deployer and preview
runtimes. Its accepted role permits Secret metadata/version metadata and
`versions.add` only under `hh-web-pr-*`; payload access exists only through
`roles/secretmanager.secretAccessor` on `hh-preview-db-app-password`. It cannot
access production/staging secrets or delete containers/ledger records. This
lifecycle reuses those accepted boundaries without granting the deployer
Secret Manager version authority.

See [the prerequisite scope/acceptance guide](../preview-foundation/prerequisites.md)
for operator ordering, backend/provider credential routing, the accepted
permission boundaries, and the proposed preparer IAM. Issue #41 remains open
for the original prerequisite acceptance details and existing permission
boundaries. A separate teardown change completes the lifecycle.

## Offline validation

```bash
make tf-fmt
make tf-validate
make tf-preview-db-test
make tf-preview-pr-test
make tf-preview-secret-preparer-test
git diff --check
```

Offline tests cover identity/name derivation, reservation/replay/concurrency
failure, ambiguous writes without retry, payload-free ledger/output shapes,
read-only reconciliation, IAM contracts, numeric Terraform variables and the
fixed bootstrap targets. Terraform provider-mocked plans verify secret
ownership and exact Cloud Run/job version references. Tests perform no ADC
requests, live backend initialization, secret reads/writes, SQL operations or
Terraform apply. CI runs the checks credential-free.
