# Isolated per-PR preview resources (41B)

This is a **separate Terraform root**, not a module in the foundation or the
production/staging root. It implements only issue #41 slice 41B. No deployment
workflow, database creation, migration execution, or live acceptance is provided.
41A's merged server-only IAP authentication is consumed unchanged.

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
| NextAuth secret | `hh-web-pr-123-nextauth` |
| Internal service-token secret | `hh-web-pr-123-internal-token` |
| Database URL secret | `hh-web-pr-123-database-url` |

It also owns versions of those three secrets and additive, resource-scoped IAM:
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

## Secret handling

Provide sensitive ephemeral `TF_VAR_nextauth_secret`,
`TF_VAR_internal_engine_service_token`, and `TF_VAR_database_url` only through
a trusted process environment. Generate independent strong 64-character
lowercase hexadecimal NextAuth/token values. The DB URL must be exactly:

```text
postgresql+psycopg://haunted_halls_preview_app:<64 lowercase hex>@/haunted_halls_web_pr_123?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres
```

The shared preview app password is assembled outside this root through an
approved trusted provisioning path. No SQL credential lookup, SQL admin access,
secret payload data source, or production/staging credential fallback exists.
The migration job receives only the PR DB URL; it runs `alembic upgrade head`,
not app startup, and needs no model or internal-token access.

All payloads go through provider `secret_data_wo`; ephemeral inputs are omitted
from Terraform plans/state. `secret_revision` is a positive write-only rotation
trigger, **not** a Secret Manager version number. Cloud Run pins the actual
created version returned by the provider; OpenAI pins the existing preview-only
secret's explicit enabled numeric version (default `1`, never `latest`).

Keep exact secret payloads available securely and identical across plan, apply,
and retry at a given revision. Do not regenerate them on each update. Increase
the revision only for intentional rotation. Versions use `ABANDON` so replacing
a version does not revoke a still-serving revision's secret after a failed
rollout. Teardown deletes the parent PR secret and therefore all its retained
versions. No secret payloads or secret IDs are emitted in outputs. Do not log
environments, raw plans/state, credentials, or Terraform debug traces.

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
   `repository_key`, `pull_request_number`, and `backend_state_prefix` inputs.
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

Only `init -backend=false`, `validate`, and mocked tests are used for 41B.
The live init sequence above is a future integration contract, not authorization
to initialize/deploy from this branch.

## Required lifecycle ordering for 41C (not implemented)

There is deliberately no "migration succeeded" Terraform flag: creating a job
does **not** execute it or prove schema readiness, and an apply dependency
cannot model successful execution. Do not use a runtime-enable toggle that
would destroy a healthy preview during an update.

41C must serialize operations by repository/PR state key and:

1. Validate event/repository/PR/head/provenance, freeze both immutable artifacts,
   check prerequisites/identity/backend, and use the trusted provisioner to
   create the empty DB if absent (preserve an existing DB; no seeds).
2. Apply only migration prerequisites via a reviewed targeted plan for
   `google_cloud_run_v2_job.migration`. Terraform's dependency closure includes
   PR secrets and their minimal runtime IAM. Inspect the saved targeted plan
   for unexpected actions before applying; this deliberate bootstrap exception
   must not become a general targeted deployment/destroy practice.
   Updates must leave currently serving engine/frontend revisions untouched.
3. Execute that fixed job explicitly, without command/env overrides; reconcile
   uncertain outcomes from actual execution state and require Alembic success.
   A failed migration stops rollout and must not destroy a healthy preview.
4. Only after successful migration, perform a fresh **full** plan/apply to roll
   out the engine and frontend on the frozen inputs. Verify readiness, exact
   digests, engine unauthenticated denial, frontend IAP interception, allowed
   tester sign-in/gameplay/persistence, and update the single PR status comment.
5. On close, destroy this root with the same identity/backend; reconcile jobs
   and retained runtime executions; drop only this generated DB via the trusted
   provisioner; then remove only this PR's state objects/locks after successful
   teardown. Retry safely; never delete foundation state or reset another PR.

41C must verify live update continuity and teardown. These phases and targeted
plans are not executed or automated in 41B.

## Concrete prerequisite gaps: fail, do not broaden authority

The reviewed foundation does not yet demonstrate all permissions/inputs needed
by the future deployer. Static validation is not live authorization evidence:

- `roles/run.admin` alone does not grant direct Cloud Run IAP policy permissions.
  The follow-up foundation prerequisite now declares a separate custom
  `iap.webServices.getIamPolicy` / `iap.webServices.setIamPolicy` role with a
  service-type/tester-role condition. Its operator apply and positive/negative
  live checks remain pending; configuration is not authorization evidence.
  Do not add project-wide tester access or repair foundation IAM here.
- The preview Cloud Run service agent needs Artifact Registry reader access to
  the accepted **existing engine repository** for the frozen staging image.
  The foundation's preview-repository grants do not supply that cross-project
  read. Staging Ready/serving-revision metadata capture also needs an explicitly
  approved narrow read path. The existing application root now declares named
  staging-engine metadata reads and source-repository reader access for the
  deployer only. The recommended future copy into the preview registry still
  needs separate implementation and image-input validation changes; this root's
  accepted source-only image input is unchanged. No existing-project IAM is
  owned here.
- The deployer has no `secretmanager.versions.access`, including on the durable
  preview DB app password. It cannot independently assemble `DATABASE_URL`.
  41C needs an approved trusted secret-assembly/input path; no SQL admin,
  provisioner impersonation, secret-access broadening, or credential logging
  is a workaround.
- Confirm the actual preview project number, tester allowlist, enabled
  preview OpenAI version, foundation runtime/SQL grants, and direct-IAP bootstrap
  compatibility for new frontend resources. A disposable bootstrap proved IAP
  in #40, not this undeployed per-PR stack. If new services require interactive
  Custom OAuth setup, stop for the operator; never fall back to public access.
- Exact-ref WIF requires the reviewed default-branch `preview-deploy.yml`.
  That workflow intentionally does not exist until 41C.

Surface each denied permission or missing prerequisite explicitly in 41C rather
than attempting foundation repair from per-PR state. No deploy, cloud/secret
mutation, live plan/backend initialization, or canonical engine-doc edit is
performed in this slice. The canonical cross-repo status follow-up should record
41B's merge while keeping #41 open pending 41C; it is deferred under the explicit
frontend-only scope, without changing planning-sync metadata.

See [the prerequisite scope/acceptance guide](../preview-foundation/prerequisites.md)
for operator ordering, backend/provider credential routing (no deployer self Token
Creator), IAM limitations, and the pending metadata-only secret/interface design.
Neither secret ownership nor lifecycle configuration changes in this prerequisite.

## Offline validation

```bash
make tf-fmt
make tf-validate
make tf-preview-db-test
make tf-preview-pr-test
git diff --check
```

The focused target uses Python standard-library tests (backend mismatch,
identity/provisioner agreement, ownership inventory, ephemeral/write-only
constraints) and Terraform provider-mocked plans (names/limits/IAM/runtime
config/images/migration and fail-closed inputs). It needs provider installation
but no ADC, Google/engine requests, live backend, SQL, secret reads, or apply.
CI runs these checks in the existing credential-free Terraform job.
Terraform **1.11.4 or later** is required: 1.11.0's internal mocked provider
returns write-only values in plans incorrectly; 1.11.4 fixes this upstream
([hashicorp/terraform#36824](https://github.com/hashicorp/terraform/pull/36824)).
CI is pinned to 1.11.4 so the new tests exercise write-only secrets without
weakening their handling or working around the provider.
