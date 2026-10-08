# Isolated per-PR preview resources and secret interface

This is a **separate Terraform root**, not a module in the foundation or the
production/staging root. This change replaces the 41B per-PR payload/version
ownership model with a trusted secret-preparation interface. It does not
implement image copying, database provisioning, migration execution, preview
rollout/teardown, or the complete 41C lifecycle. 41A's merged server-only IAP
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

Use accepted foundation metadata for `preview_project_number`; the digits in
the project **ID** are not evidence of its project **number**. The trusted
41C preflight must check that number against the project, IAP service agent,
and the generated URL before deployment.

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
- `us-east1-docker.pkg.dev/haunted-halls-development/haunted-halls/engine@sha256:<64 lowercase hex>`

Tags, other repositories, partial/uppercase digests, and whitespace are rejected.
There is no mutable image fallback or ignored image drift. The same frozen
engine digest is used by the engine **and** the migration job.
Terraform syntax validation cannot establish artifact provenance or current
staging readiness: 41C must freeze/verify the Ready/serving staging digest and
verify the frontend digest against the exact PR head before providing inputs.

## Trusted secret preparation

The fixed workflow
[`preview-secret-prepare.yml`](../../../.github/workflows/preview-secret-prepare.yml)
can run only as a manual dispatch on the reviewed default branch. It checks
that the PR is open, checks out the dispatch's `main` SHA, and authenticates
through exact-workflow-ref WIF as
`hh-preview-secret-preparer@hh-preview-458395246135.iam.gserviceaccount.com`.
It accepts only the frontend repository key, canonical PR number, a
32-character lowercase-hex PR incarnation, and a positive generation number.
The tool derives all three Secret Manager container names itself; it accepts no
project, secret path, database, SQL endpoint, command, or payload override.

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
different container names. 41C must persist the active incarnation and allocate
a new identifier only after a reviewed teardown/reopen transition. This
workflow does not automatically take over an older incarnation.

The preview foundation owns the separate
`hh-preview-458395246135-pr-secret-ledger` bucket. It is private, versioned,
protected from normal Terraform destruction, and separate from both Terraform
state buckets. Each object is keyed by repository, PR and incarnation and stores
only identity, expected container names, current state/generation, any
in-flight role, and numeric version IDs. Before each individual Secret Manager
append, the matching role intent is persisted; its returned version is recorded
before the next role begins. GCS generation-match writes provide optimistic
concurrency; bucket object versioning preserves prior state transitions. The
preparer can read and create/update ledger objects but cannot delete them.
Per-PR Terraform destroy does not delete ledger history.

The reservation is non-expiring and exclusive for the incarnation. A generation
can be reserved only once; a later generation is allowed only after the prior
one is complete and only in sequence. States are `reserved`, `writing`,
`complete`, and `reconciliation-required`. A crash or unresolved state blocks
new writes; no lease timeout or automatic lock takeover exists.

Secret Manager `addVersion` has no operation idempotency key. SDK retries are
disabled. If any response is ambiguous, the preparer makes no second
`addVersion`, marks the generation `reconciliation-required` when possible,
and stops. The read-only `reconcile` mode lists ledger state, container labels
and version numbers/states/create times; it never accesses payloads. Because
shared per-incarnation containers cannot unambiguously correlate an
unrecorded append to one generation, reconciliation reports an operator
disposition requirement instead of guessing. GCS compare-and-swap protects
ledger transitions only; it does **not** fence an external Secret Manager
write. Reconciliation never resumes or retries an append. Correctness takes
priority over recovery availability.

### Numeric Terraform interface

The per-PR root requires:

- `nextauth_secret_version`
- `internal_engine_service_token_version`
- `database_url_secret_version`

Each is a required string containing a canonical positive decimal integer.
`latest`, aliases, zero, signs and leading zeroes are rejected. Cloud Run
services and the migration job pin these exact values. OpenAI remains pinned
separately to its existing preview-only numeric version.

## Backend identity consistency (41C integration contract)

Backend configuration cannot interpolate input variables. Its bucket and
impersonation identity are fixed here; **prefix must be supplied at init**.
`backend_state_prefix` separately validates agreement with the resource identity,
but Terraform cannot inspect its own selected backend from that input.
Consequently 41C must enforce both checks before any stateful operation:

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

Only backend-disabled init, `validate`, and mocked tests are used for this
change. The live init sequence above remains a future integration contract, not
authorization to initialize/deploy from this branch.

## Bootstrap and 41C lifecycle ordering

There is deliberately no "migration succeeded" Terraform flag: creating a job
does **not** execute it or prove schema readiness, and an apply dependency
cannot model successful execution. Do not use a runtime-enable toggle that
would destroy a healthy preview during an update.

The required order is:

1. Before cloud access, validate the trusted default-branch event, repository,
   open PR, incarnation/generation, fixed project identity, WIF identity and
   backend metadata. Freeze artifact digests and use a fresh private working
   directory/`TF_DATA_DIR`.
2. Create/reconcile just the three secret containers and their runtime access
   grants using a reviewed targeted plan for exactly:
   `google_secret_manager_secret.pr` and
   `google_secret_manager_secret_iam_member.runtime`. The fixed inventory is
   exposed by `python3 tools/preview-secret-preparer/terraform_targets.py
   containers` and contract-tested; it is a narrow bootstrap exception, not a
   general targeted apply/destroy pattern. Review the saved plan for any
   unexpected actions before applying.
3. Dispatch the fixed secret-preparation workflow with the same PR incarnation
   and the next generation number. It writes versions once, records each
   numeric result, and returns only non-secret metadata.
4. Use the reviewed migration target from
   `python3 tools/preview-secret-preparer/terraform_targets.py migration`:
   exactly `google_cloud_run_v2_job.migration`. Its dependencies consume the
   explicit DB version and already-created container/IAM prerequisites. Review
   the saved targeted plan before applying; no general target expansion is
   allowed.
5. Create the empty PR database through the fixed trusted provisioner if absent
   (preserve an existing DB; no seeds), then execute the fixed migration job
   explicitly without command/env overrides. Reconcile uncertain execution
   outcomes from actual execution state and require Alembic success. A failed
   migration stops rollout and must not destroy a healthy preview.
6. Only after successful migration, perform a fresh **full** plan/apply to roll
   out the engine and frontend. Verify readiness, exact digests, engine
   unauthenticated denial, frontend IAP interception, allowed tester
   sign-in/gameplay/persistence, and update the single PR status comment.
7. On close, destroy this root with the same identity/backend; reconcile jobs
   and retained runtime executions; drop only this generated DB; retain
   unresolved ledger history. A fully recreated environment must use a new
   incarnation. Never delete foundation state or reset another PR's state.

The targeted bootstrap contract and secret preparer are implemented here;
database lifecycle, migration invocation, artifact provenance/copy,
rollout/update/teardown and end-to-end verification remain 41C work. No live
backend, preview environment or migration is executed by this change.

## Accepted IAM boundaries and remaining 41C work

The prior preview-deployer/WIF/IAM phase is live-accepted and reconciled for its
reviewed scope. This code-only change does not apply the new preparer identity,
role or ledger grants. Do not weaken either accepted fail-closed limitation:

- No approved outside-preview IAP WebService canary exists. Do not create one
  or broaden IAP authority to force that negative check.
- The deployer's Artifact Registry reader intentionally lacks
  `artifactregistry.repositories.getIamPolicy`. Do not broaden its source
  registry grant.

The new preparer identity is deliberately separate from the deployer and
preview runtimes. Its proposed role permits Secret metadata/version metadata
and `versions.add` only under `hh-web-pr-*`; payload access exists only through
`roles/secretmanager.secretAccessor` on
`hh-preview-db-app-password`. It cannot access production/staging secrets or
delete containers/ledger records. This proposed IAM is not yet live.

See [the prerequisite scope/acceptance guide](../preview-foundation/prerequisites.md)
for operator ordering, backend/provider credential routing, the accepted
permission boundaries, and the proposed preparer IAM. Issue #41 remains open
for 41C and live end-to-end acceptance.

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
