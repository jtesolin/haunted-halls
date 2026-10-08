# Frontend preview IAM and trusted secret preparation for #41

The preview deployer/WIF/IAM prerequisite phase is live-accepted and fully
reconciled for its reviewed scope. The accepted preview project is
`hh-preview-458395246135` (project number `1001419903197`), in `us-east1`.
Keep issue #41 open: this change adds the proposed trusted secret-preparer
identity/IAM, durable ledger and per-PR numeric-version interface, but does not
apply those new permissions, copy images, or implement full 41C lifecycle
automation. The engine repository is unchanged.

The existing parent-project creation grant remains separate. The proposed
prefix-scoped deployer container-lifecycle role adds metadata/IAM reconciliation
and teardown without any version permissions. Its earlier per-PR
version-management grant is removed from the proposed configuration.
A fixed WIF workflow and separate identity
prepare frontend PR versions; that identity can access payloads only on the
existing preview app-password secret. No payload is returned to Terraform or
GitHub. No Terraform apply, live secret-version write, preview deployment,
database operation, or live IAM mutation occurs in this change.

## Principals, scope, and ownership

Existing accepted deployer grants use
`hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com`.
The new proposed preparer is
`hh-preview-secret-preparer@hh-preview-458395246135.iam.gserviceaccount.com`.
All grants use additive `*_iam_member` resources, not authoritative policies
or bindings that replace other members.

The foundation's `preview_project_id` is a fixed-project contract, not a
multi-project configuration option: validation accepts only
`hh-preview-458395246135`, including when explicitly supplied by an operator.
This keeps the foundation-created deployer aligned with the application root's
pinned source-grant principal, the per-PR root's project and state bucket, and
its backend impersonation identity. An otherwise-valid alternate project ID is
rejected before provisioning. Supporting another project would require a
separately reviewed cross-root design; this change preserves all IAM scopes
and pinned identities.

Offline IAM tests evaluate the actual foundation variable validation in a
temporary provider-free Terraform module: the accepted project passes and
`hh-preview-alternate` fails. Source contracts also check alignment with the
source principal, per-PR project, state bucket, and backend impersonation
identity. These checks do not prove live authorization.

| Permission/role | Resource and restriction | Owning Terraform root | Reason |
| --- | --- | --- | --- |
| Custom `previewIapTesterPolicy`: only `iap.webServices.getIamPolicy`, `iap.webServices.setIamPolicy` | Project `hh-preview-458395246135`, with the condition below | `preview-foundation` | Manage tester policies on dynamically created IAP service resources |
| Existing custom `previewPerPrSecretCreator`: only `secretmanager.secrets.create` | Preview project; deployer only | `preview-foundation` | CreateSecret authorizes its parent project, not a nonexistent Secret; trusted Terraform derives names |
| Custom `previewPerPrSecretLifecycle`: `secretmanager.secrets.get/update/delete/getIamPolicy/setIamPolicy` | Secret parent resources under the numeric preview project's `hh-web-pr-*` and `hh-engine-pr-*` prefixes; deployer only | `preview-foundation` | Terraform parent metadata/IAM reconciliation and teardown; no version permissions |
| Custom `previewPerPrSecretPreparer`: `secretmanager.secrets.get`, `secretmanager.versions.add/get/list` | Secret and SecretVersion resources under `projects/1001419903197/secrets/hh-web-pr-*`; exact default-branch workflow identity only | `preview-foundation` | Validate container ownership, create each version once, and inspect version metadata; no payload access or mutation beyond add |
| `roles/secretmanager.secretAccessor` | Only `hh-preview-db-app-password` in the preview project | `preview-foundation` | Read the durable preview app password to assemble the PR-specific DB URL |
| Custom `previewSecretPreparerProjectReader`: only `resourcemanager.projects.get` | Preview project; preparer only | `preview-foundation` | Verify the actual fixed project number before any preparation |
| Custom `previewSecretLedgerWriter`: only `storage.objects.get/create` | Fixed private, versioned `hh-preview-458395246135-pr-secret-ledger` bucket | `preview-foundation` | Immutable create-only markers and exact GET; no overwrite, delete, list or Terraform-state access |
| Custom `previewQuotaConsumer`: only `serviceusage.services.use` | Preview project, unconditional; deployer and preparer | `preview-foundation` | Trusted Google API requests use this quota project; no API enablement or quota administration |
| Custom `previewStagingEngineMetadataReader`: only `run.services.get`, `run.revisions.get` | Individual `haunted-halls-engine-staging` service, `haunted-halls-development/us-east1`; binding created only when staging services are enabled | Existing application root `infra/terraform` | Named reads of the actual serving revision; no listing, invocation, IAM writes, or runtime mutation |
| `roles/artifactregistry.reader` | Existing `haunted-halls` repository, `haunted-halls-development/us-east1` | Existing application root `infra/terraform` | Read the frozen source artifact; no source push, tagging, or delete |

The application-root source grants have preconditions rejecting a different
project or region. The root already owns the source repository and staging
service; foundation and per-PR state do not take ownership of those resources.
There is no new project-level metadata grant, source-registry grant to preview
runtime identities/service agents, or production/staging mutation permission.

The foundation now declares `sqladmin.googleapis.com` in the preview project
with `disable_on_destroy = false`, alongside the existing-project API. This
supports cross-project runtime Cloud SQL connections, not deployer SQL
administration. See [Cloud SQL from Cloud Run](https://cloud.google.com/sql/docs/postgres/connect-run).

## IAP condition and limits

```cel
resource.type == "iap.googleapis.com/WebService" &&
api.getAttribute("iam.googleapis.com/modifiedGrantsByRole", [])
  .hasOnly(["roles/iap.httpsResourceAccessor"])
```

The role contains only service-policy read/write permissions. For policy reads,
the modified-role attribute defaults to an empty list, accepted by `hasOnly`.
For policy writes, only the tester role may be changed. Changing IAP admin or
other roles, including a mixed tester/admin change, must be denied.

Verification against public documentation and the checked-in lock:

- [GCP supported attributes](https://cloud.google.com/iam/docs/conditions-attribute-reference):
  IAP supports `resource.type`, but not `resource.name`; the IAM
  `modifiedGrantsByRole` attribute supports IAP and project allow-policy bindings.
- [GCP resource types](https://cloud.google.com/iam/docs/conditions-resource-attributes):
  `iap.googleapis.com/WebService` is the service-policy resource type.
- [IAP policy permissions](https://cloud.google.com/iap/docs/managing-access#resources_and_permissions):
  administrative policy permissions are separate from tester access.
- [Pinned Google 7.46.1 provider](https://github.com/hashicorp/terraform-provider-google/blob/v7.46.1/google/services/iap/iam_iap_web_cloud_run_service.go):
  the per-PR member uses `getIamPolicy`/`setIamPolicy` at
  `projects/PROJECT/iap_web/cloud_run-REGION/services/SERVICE`.
  The provider requests version-3 policies and submits the service policy;
  it does not enforce or prove IAM Conditions itself.

**Scope disclosures:**

- The IAP condition does **not** enforce PR-name prefixes or tester email
  membership. It allows tester-role changes on IAP WebService resources across
  the dedicated preview project. The trusted per-PR configuration must enforce
  canonical names and explicit tester allowlists. It is not a per-PR admin fence.
- Tester access stays on each frontend's IAP resource as
  `roles/iap.httpsResourceAccessor`; no project-wide tester grant is added.
  IAP service-agent `roles/run.invoker` stays on each frontend separately.
- The deployer's creation-only Secret Manager grant allows **arbitrary new secret names**
  in the preview project. A requested secret-name prefix cannot be restricted by
  the old Secret-resource condition because
  [CreateSecret](https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/create)
  authorizes `secretmanager.secrets.create` on the parent project. It does not
  grant payload access or management of existing non-PR secrets. The separate
  preparer role is conditioned on the `hh-web-pr-*` namespace.
- Source registry reads cover **all packages in that repository**, not just the
  engine package. The future trusted copy code must validate the engine path and
  immutable digest. No source image-copy implementation is included here.

The accepted deployer remains preview-secret-equivalent through its existing
Cloud Run authority and runtime `actAs`; absence of direct Secret Manager
payload permission is not a claim of effective isolation from preview runtime
secrets. The new preparer has no production/staging secret authority and no
provisioner `actAs`.

## Accepted prerequisite scope and limits

Live acceptance confirmed the exact WIF identity; preview Cloud Run
create/delete/service-IAM authority; frontend runtime `actAs`; service-level
IAP policy read and tester add/remove; admin and mixed-role denial; Secret
Manager creation boundary, payload-access denial and secret-management
restriction; quota-use boundary; named staging-engine service/revision reads
and production/list/invocation/runtime/IAM denials; immutable source-manifest
read; and registry-write denial.

Two fail-closed limits remain accepted and must not be repaired by broadening
IAM:

1. There is no approved outside-preview IAP WebService canary.
2. The deployer's source Artifact Registry reader intentionally lacks
   `artifactregistry.repositories.getIamPolicy`.

No per-PR environment was created by that acceptance. It does not authorize
applying the new preparer IAM proposed here. Preserve exact-ref WIF, the
fresh-runner/default-workspace/backend-identity checks, and never execute
PR-controlled Terraform or scripts after authentication.

## Manual WIF acceptance harness

The exact reviewed prerequisite plans at frontend source
`b4b4e1c090916977ea3c591d5d39c6fc07565dfd` were subsequently applied successfully:
foundation 6 add / 1 change / 1 destroy (serial 6 -> 8), application 3 add /
0 change / 0 destroy (serial 27 -> 28). Authoritative inspection found no
unreviewed mutations. **Do not reapply those consumed plans.** The deployer
acceptance is now reconciled for the scope above; only the two documented
fail-closed limitations remain. The local operator has no impersonation grant.

The manual-only [workflow](../../../.github/workflows/preview-deploy.yml) and
[standard-library harness](../../../tools/preview-acceptance/acceptance.py)
are a bounded acceptance precursor, not the automatic 41C lifecycle. They
must be reviewed/merged before a maintainer dispatches from `main`. There are
no privileged dispatch inputs. Job/context gates reject non-main, other
repositories, other workflow refs and invalid run identities before mutation.
Checkout is the dispatch main SHA, verified before authentication; credentials
are not persisted by checkout. Workflow permissions are only `contents: read`
and `id-token: write`, with the repository's existing action-version convention.

Read-only operator inspection on October 7, 2026 confirmed the accepted state
output and ACTIVE live provider are exactly
`projects/1001419903197/locations/global/workloadIdentityPools/hh-preview-github/providers/github-preview`.
The live accepted deployer condition/mapping and service-account policy use the
two documented deployment workflow refs. This change proposes a separate
exact-ref binding for `preview-secret-prepare.yml` and its distinct service
account; that binding is not yet live. No operator impersonation or deployer
self Token Creator is introduced.

### Supported checks and canary boundary

- Verify the access token's exact preview-deployer email and actual project
  number `1001419903197`; fail before canary creation on mismatch.
- Verify existing Run create/delete/service-IAM permissions and frontend runtime
  `actAs`. Live operator inspection confirmed preview `roles/run.admin` and
  that runtime-only grant; no extra permissions are needed for a safe canary.
- Create `hh-web-iam-accept-<run-id>-<attempt>`, not a real PR name, in
  `hh-preview-458395246135/us-east1`. Use only reviewed fixed
  `gcr.io/cloudrun/hello@sha256:ea86b59c787261f424f9de114900e598f19e036c73aa95ff12b6ad5f022122fd`
  (public sample digest resolved read-only during implementation).
  IAP stays enabled with no `allUsers` binding, no env/secrets/SQL mounts,
  no application/provisioner image, min 0 / max 1 and 1 CPU / 256 MiB.
  Only the per-service IAP agent receives invocation.
- Read version-3 service IAP policy; add/remove tester-role membership for the
  deployer service account **on the canary only**, not a human tester grant or
  browser acceptance. Preserve every unrelated binding/condition and fresh etag.
  Seed one expired conditional tester binding as a live preservation control,
  then remove it after restoring the original policy; it grants no current access.
  Attempt admin and mixed-role writes only against this disposable service;
  require HTTP 403 `PERMISSION_DENIED` and verify no policy change.
- Inspect parent IAP policy permissions for the non-WebService denial.
- Create `hh-web-pr-acceptance-<run-id>-<attempt>` and
  `iam-web-acceptance-<run-id>-<attempt>` secret containers. The alphabetic acceptance
  namespace cannot collide with numeric PR names. Append one explicitly
  non-sensitive canary version only to the prefixed container, and require its
  direct access to fail with HTTP 403 `PERMISSION_DENIED`. Do not touch durable
  credentials. Inspect management permissions on the newly existing non-prefixed
  canary and creation permissions on the existing source project.
- Make a quota-billed preview API read. Inspect quota-use with a positive control
  and require enable/disable/quota-update permissions to be absent.
- Read exactly the staging engine service and its sole 100% latest Ready revision.
  Require production named read and source service/revision lists to fail with
  permission denial. Inspect staging update/delete/invoke/IAM permissions with a
  positive named-read control; never issue source mutation/invocation calls.
- Read only the serving engine's existing immutable source manifest, without
  capture/copy or resolving tags. Inspect registry upload/delete/tag permissions
  with a positive download permission control.

The harness retains access tokens only in process memory. It emits no raw HTTP
errors/bodies, credential files, JWTs, payloads, headers or state. Its private
runner-local journal contains allowlisted check results, canary ownership metadata,
and the minimum complete original version-3 IAP policy and attempted policy
candidates needed for rollback. That policy stays only in the private `0600`
runner state, never the Actions summary. Journal updates use atomic replacement
and file/directory synchronization; no cloud results are downloaded as artifacts.

### Fail-closed gaps; do not broaden IAM to pass

1. **Source policy membership audit:** `roles/artifactregistry.reader` does not
   include `artifactregistry.repositories.getIamPolicy`. The deployer cannot
   independently verify other runtimes' grants. The harness attempts the
   read-only audit and reports `FAIL / BLOCKED` on permission denial, not PASS.
   The request explicitly asks for policy version 3 so conditional grants are
   audited with the same membership restrictions as unconditional grants.
   Read-only operator inspection during implementation found no direct repository
   grants to the preview frontend/engine/migration or preview service agents;
   this is separate evidence, not an effective-access test by the deployer.
2. **Outside-project IAP WebService denial:** there is no approved disposable
   source-project IAP WebService. A denial on the parent `iap_web` resource would
   not prove the conditional WebService boundary. The harness reports this
   required check as `FAIL / BLOCKED`; it neither creates a canary outside the
   preview project nor writes production/staging IAP policies.

These two gaps remain visibly blocked in the acceptance evidence; they require
an approved canary or separately reviewed operator disposition, not automatic
role changes. They are not prerequisites to or reasons for widening the trusted
preparer boundary.

### First live run and request-shape follow-up

Live run [37708901189](https://github.com/jtesolin/haunted-halls/actions/runs/37708901189)
used reviewed source `e6e9f3dfee1bcf89db1d33707bd59cd6a4760a20`.
WIF authenticated as the exact preview deployer; project/number, canary
permissions, Secret Manager boundaries, quota checks, staging metadata and
source manifest/write boundaries passed. Both documented gaps reported BLOCKED.
Service-level IAP policy read unexpectedly returned HTTP 404 because the harness
used a GET/query form instead of the IAP v1 `getIamPolicy` POST/request body.
Tester add/remove and admin/mixed-role checks did not run and remain pending.
No IAP policy mutation occurred; live prerequisite acceptance is **not complete**.

The workflow verified deletion of the Cloud Run canary
`projects/hh-preview-458395246135/locations/us-east1/services/hh-web-iam-accept-37708901189-1`
and prefixed secret
`projects/1001419903197/secrets/hh-web-pr-acceptance-37708901189-1`.
On October 8, 2026, operator ADC `jack.tesolin@gmail.com` inspected only metadata
for the remaining
`projects/1001419903197/secrets/iam-web-acceptance-37708901189-1`,
verified project ID/number and labels `hh-purpose=iam-acceptance`,
`hh-repository=web`, `hh-run=37708901189`, `hh-attempt=1`, deleted only that
exact secret, and verified absence (HTTP 404). No payload was accessed.

The focused follow-up corrects IAP policy reads to POST the unchanged Cloud Run
WebService `:getIamPolicy` endpoint with
`{"options":{"requestedPolicyVersion":3}}`. It adds no GET fallback or propagation
retry. Version-3 reconciliation and `setIamPolicy` behavior remain unchanged;
empty/condition-free version-1 responses remain valid. Future summaries render
one sanitized string to both `GITHUB_STEP_SUMMARY` and ordinary job stdout;
the fixed authentication-failure message likewise uses one literal block and
`tee`. Neither path prints the private reconciliation journal or raw policies.
This improves auditable log retrieval without changing nonzero failure semantics.
No new acceptance dispatch occurs before this fix is reviewed and merged.

### Owned canary reconciliation

`always()` invokes cleanup with freshly verified deployer credentials. Only
canaries created/attempted by this run and matching exact ownership labels may
be deleted. Cloud Run long-running creation/deletion is polled before declaring
absence; a lost creation response or ambiguous in-flight result requires operator
reconciliation. Non-prefixed secrets intentionally cannot be deleted by the
deployer, so their exact numeric-project resource names are prominently reported
for later operator cleanup. Even a successful run would leave that known canary
for the operator; a lost runner or hard cancellation may leave other reported
canaries as well. Cleanup never overwrites the original check result.

Before the first IAP write, the harness journals the original bindings,
conditions, version and etag with the exact canary resource identity. Every
submitted policy write is recorded as ambiguous **before** the request, then
as succeeded after its response; restored is recorded only after a confirming
version-3 read. This also covers unexpectedly successful negative-test writes.
Cleanup first verifies service ownership, reads the current IAP policy with
version 3 and a fresh etag, restores the original, and verifies canonical
bindings/conditions before service deletion. A definitively rejected stale-etag
write permits one fresh read and retry; ambiguous writes are not blindly retried.
Unexpected unrelated policy changes are never overwritten. If restoration or
ownership cannot be proven, retain the service for explicit operator
reconciliation and continue safe cleanup of other owned canaries. Deletion
failure after a proven rollback does not erase that proof or the original
acceptance failure. The summary reports only sanitized reconciliation status.

Review the Actions summary for every PASS/FAIL/NOT RUN, expected denial versus
unexpected error, exact canary name and cleanup status. As operator, inspect
reported resources and their `hh-purpose=iam-acceptance`, run and attempt labels
before deleting only those canaries. Verify absence afterward. Never delete by
prefix/wildcard or change runtime/IAM to make a negative test pass.

Offline validation: `make preview-acceptance-test` (workflow trust contracts and
mocked identity, strict denial, policy preservation, source-boundary and cleanup
tests). CI runs the same checks without credentials. This secret-preparation
slice performs no additional cloud acceptance or workflow dispatch.

## Offline validation

```bash
make tf-fmt
make tf-validate
make tf-preview-iam-test
make tf-preview-db-test
make tf-preview-pr-test
make tf-preview-secret-preparer-test
git diff --check
```

The standard-library tests assert source-level permission sets, scopes,
conditions, additive ownership, staging gating, version/preparer boundaries,
tester scope and authentication boundaries. Backend-disabled validation checks
the pinned provider schemas; per-PR tests use mocked plans. **None of these
evaluates the proposed live preparer IAM conditions or authorizes applying them.**

## Trusted per-PR secret preparation and Terraform interface

This slice introduces a dedicated, manual-only
[default-branch workflow](../../../.github/workflows/preview-secret-prepare.yml)
and a fixed preparer identity. The workflow accepts only an open, non-draft frontend PR
number, a 32-character lowercase-hex incarnation, a positive sequential
secret-generation number and `operation=prepare|reconcile`. It checks the
workflow ref, repository, branch and checked-out main SHA before authentication.
Both `prepare` and `reconcile` reject drafts, closed PRs, missing metadata and
repository/number mismatches before WIF authentication. Draft PRs stay CI-only.
It never checks out or executes PR code. Its WIF binding targets only
`hh-preview-secret-preparer@hh-preview-458395246135.iam.gserviceaccount.com`.
The preparer independently validates project ID/number, credential identity,
all identity fields, derived resource names and ownership labels. It accepts no
project ID, Secret Manager path, SQL host/user/database, command or payload.

### Ownership and least privilege

- Per-PR Terraform owns three Secret Manager parent containers, incarnation and
  PR ownership labels, runtime Secret Accessor grants and Cloud Run/job
  references to explicit numeric versions. It no longer declares payload
  variables or `google_secret_manager_secret_version` resources.
- The deployer keeps separate project-parent `secretmanager.secrets.create`
  authority and a prefix-scoped `previewPerPrSecretLifecycle` role containing
  only `secretmanager.secrets.get/update/delete/getIamPolicy/setIamPolicy`.
  The condition permits only Secret parents in the numeric preview project's
  `hh-web-pr-*` and `hh-engine-pr-*` namespaces. `update` reconciles
  Terraform-owned labels; IAM permissions support runtime grants; `delete`
  supports teardown. There are no version permissions or shared-secret grants.
  The old `previewPerPrSecretManager` role/grant is removed.
- `previewPerPrSecretPreparer` grants only
  `secretmanager.secrets.get`, `secretmanager.versions.add/get/list` under the
  numeric preview project `hh-web-pr-*` resource-name prefix. It does not grant
  `secretmanager.versions.access`, container update/delete/IAM management,
  version enable/disable/destroy, or project-wide Secret Manager Admin.
- `roles/secretmanager.secretAccessor` is granted to the preparer only on the
  preview foundation's existing `hh-preview-db-app-password` secret. This is
  the sole source of the shared app password. The former engine/migration
  direct password grants are removed; they consume only their PR DB URL secret.
  The preparer has no production or
  staging project/secret grant and no `actAs` on the SQL provisioner.
- `previewSecretLedgerWriter` grants only `storage.objects.get/create` on the
  fixed `hh-preview-458395246135-pr-secret-ledger` bucket. It has no object
  delete, list, Terraform-state or bucket-administration permission. The
  bucket is private, versioned, preview-project-owned and protected by
  `prevent_destroy`; per-PR teardown cannot erase its history.
- Runtime identities keep Secret Accessor only on their specific PR containers;
  they have no version-creation authority. No live IAM apply is part of this
  pull request.

The role condition restricts the preparer's version metadata/add permissions to
`projects/1001419903197/secrets/hh-web-pr-*`. That is a namespace boundary, not
proof that arbitrary caller-supplied names are safe; trusted code derives each
full name and verifies `app`, `environment`, `repository`, `pull_request` and
`incarnation` labels before any write. The deployer can create arbitrary new
names because Secret Manager authorizes `secrets.create` on the parent project;
this accepted limitation is not widened into version access.

### Incarnation and naming tradeoff

An incarnation is a trusted, non-secret 128-bit lowercase-hex identifier,
immutable for one frontend preview-environment lifetime. For `web` PR `123` and
incarnation `aaaaaaaa...` the three names are derived exactly as:

- `hh-web-pr-123-i-<incarnation>-nextauth`
- `hh-web-pr-123-i-<incarnation>-internal-token`
- `hh-web-pr-123-i-<incarnation>-database-url`

The containers are fixed for that incarnation; each strictly sequential
positive generation appends exactly one version to each. Per-generation
containers are unnecessary when version numbers are recorded and all writes
are serialized; incarnation-qualified parents prevent a destroyed/recreated
lifecycle from adopting old container/version metadata. The 41C lifecycle must
persist the active incarnation and allocate a different random identifier
after completed destruction. Reopen/recreation and tombstone transitions are
not automated here; the preparer does not silently change an old incarnation.

### Payload generation and database URL

The privileged workflow installs only the committed, reviewed
[`requirements.lock`](../../../tools/preview-secret-preparer/requirements.lock),
with `pip --require-hashes --only-binary=:all:` before WIF authentication.
It pins the full transitive closure and SHA-256 wheel hashes for the supported
Ubuntu x86_64 / Python 3.12 runtime. The top-level `requirements.txt` remains
development input only. Resolve/update the lock during development and review
it before committing, never within the privileged job. Credential-free CI
verifies an isolated install, dependency consistency and SDK imports.

The trusted preparer creates independent cryptographically strong 32-byte
NextAuth and internal service-token values. It reads only the fixed preview
secret `hh-preview-db-app-password`, validates the 64-character lowercase-hex
password, and builds exactly:

```text
postgresql+psycopg://haunted_halls_preview_app:<password>@/haunted_halls_web_pr_<N>?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres
```

`N` is the canonical PR number, validated as `1..999999999`; no arbitrary DB
name, host, username or credential fallback is accepted. The payloads exist
only in process memory for the three `addVersion` calls and are best-effort
zeroed after use. No payloads or payload hashes enter Terraform, the ledger,
workflow artifacts, summaries, comments, logs or outputs. The tool returns
only identity and numeric Secret Manager version metadata.

All expected preparation finishes before reservation: derive/validate names,
verify all three ownership labels, generate/validate distinct NextAuth and
internal-token values, read/validate the fixed DB password, construct the exact
PR DB URL, and establish the in-memory payload map. No ledger marker is created
until these steps succeed. A failure here is safe to retry because there is no
intent or external append. A single `finally` path best-effort wipes every
allocated NextAuth, token, password and URL bytearray on every exit, including
preparation failure, reservation conflict and all post-reservation failures.

### Durable ledger, retry ambiguity and reconciliation

The ledger is immutable and append-only. Deterministic paths are rooted at
`secret-preparation/v1/web-pr-<N>/<incarnation>/generations/<G>/`:

- `reservation.json`: identity, expected names and a non-secret random
  reservation ID that distinguishes this invocation's uncertain create from
  another writer's reservation.
- `<role>.intent.json`: durable intent before the external append, for
  `nextauth`, `internal-token` and `database-url`.
- `<role>.result.json`: exact identity/names and only the numeric version
  returned for that role, persisted before the next append.
- `reconciliation-required.json`: non-secret ambiguity marker, when writable.
- `complete.json`: created only after all three results are durable.

Every write creates a new object with `if_generation_match=0` and SDK retries
disabled. Existing objects are never overwritten or deleted. Deterministic
GETs reconstruct state without object listing. Bucket versioning is defense
in depth, not a coordination requirement. If a create has an ambiguous
transport outcome, GET of that exact path must match the expected payload-free
content; otherwise the operation fails closed. A definite create conflict is
never adopted as a fresh reservation or replay.

Generation 1 reserves its marker once. Generation N requires a valid immutable
complete marker plus all results for N-1 before reserving; skips fail closed.
Reservations do not expire. Intent without a result blocks replay even when
the reconciliation marker cannot be written. There is no timeout-based
takeover, automatic reservation stealing or automatic resume.
Once reservation is durable, failures retain this conservative protocol;
pre-reservation retry safety does not allow replay of a reserved generation.

Secret Manager `addVersion` has no caller-supplied idempotency key. The SDK
retry parameter is disabled, each role is submitted at most once per generation,
and the numeric version is durably recorded immediately after a successful
response. A lost/ambiguous response is marked `reconciliation-required` and
stops the operation; no second `addVersion` is issued. If a successful version
write cannot be durably recorded, the generation remains non-terminal and is
also blocked and raises a reconciliation-required failure, not a retryable
reservation conflict. GCS create-only coordination does **not** make Secret
Manager `addVersion` idempotent or fence an external append.

The workflow's read-only `reconcile` mode reads the ledger, container labels,
and Secret Manager version number/state/create-time metadata only; it never
calls `versions.access`. With shared incarnation containers, an unrecorded
version cannot always be attributed to an ambiguous generation. In that case
the report expressly requires operator disposition and does not guess, adopt,
retry or release the reservation. There is no automatic resolution command in
v1. Correctness is preferred over availability.

### Numeric Terraform interface and bootstrap ordering

The root requires three non-sensitive strings:

- `nextauth_secret_version`
- `internal_engine_service_token_version`
- `database_url_secret_version`

Each must be a canonical positive decimal integer; `latest`, aliases, zero,
signs and leading zeroes fail validation. All three must be explicit even for
the targeted container bootstrap, although the bootstrap target does not
consume them. Cloud Run pins the exact inputs. Destroying a PR root deletes the
three parent containers and therefore all versions they contain; it does not
delete the foundation ledger.

The future 41C workflow must enforce this narrow sequence before rollout:

1. Validate trusted default-branch event/repository/PR/head, incarnation and
   generation; verify project ID/number, exact WIF identity and GCS backend
   metadata. Use a private PR-specific directory/`TF_DATA_DIR` and default
   workspace.
2. Create/reconcile containers and runtime access prerequisites using only
   `google_secret_manager_secret.pr` and
   `google_secret_manager_secret_iam_member.runtime`. The reviewed target list
   is emitted by `python3 tools/preview-secret-preparer/terraform_targets.py
   containers`; offline tests lock the exact two addresses. Review the saved
   plan before apply. This is the sole container-bootstrap target exception.
3. Invoke the fixed preparer workflow. It creates one generation, records the
   three numeric versions and returns sanitized metadata.
4. Plan only `google_cloud_run_v2_job.migration`, using the fixed target list
   from `python3 tools/preview-secret-preparer/terraform_targets.py migration`.
   Review the saved plan; run the job explicitly and require successful Alembic
   completion before rollout.
5. Only then perform a fresh full plan/apply for frontend and engine rollout.
   Image provenance/capture/copy, database creation/drop, migration invocation,
   rollout/update/teardown and live acceptance remain full 41C work, not part
   of this secret-preparation slice.

No Terraform apply, live IAM mutation, live Secret Manager write, live backend
initialization, preview creation, database operation or migration occurred in
this change. The two accepted IAP/source-registry limitations above remain
unchanged.
