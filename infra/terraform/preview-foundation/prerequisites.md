# Frontend preview IAM/API prerequisites for #41

This is the first prerequisite change after accepted foundation #40 and merged
41A/41B (#47/#50). It does not reopen their acceptance or claim a live deployment.
Secret preparation, the per-PR interface update, image copying, and the trusted
41C lifecycle remain **pending**. Keep #41 open.

The original prerequisite PR added only IAM/API configuration. No apply, cloud-backed plan,
secret access, migration, or live permission test was performed. Existing
deployer version-management permissions remain until a replacement path exists.
No provisioner permissions, ledger, runtime, WIF, or per-PR resource ownership
change was included. Subsequent operator applies and the new manual acceptance
harness are recorded below. The engine repository is unchanged.

## Principal, scope, and ownership

The principal in every new grant is
`hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com`.
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
| Existing custom `previewPerPrSecretCreator`: only `secretmanager.secrets.create` | Preview project, unconditional creation-only grant | `preview-foundation` | CreateSecret authorizes its parent project, not a nonexistent Secret |
| Existing custom `previewPerPrSecretManager` | Existing Secret/SecretVersion resources under numeric preview project paths `hh-web-pr-*` / `hh-engine-pr-*`; unchanged condition and permissions | `preview-foundation` | Preserve metadata/version/IAM management, without direct payload access |
| Custom `previewQuotaConsumer`: only `serviceusage.services.use` | Preview project, unconditional | `preview-foundation` | Provider requests use this quota project; no API enablement or quota administration |
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
- The creation-only Secret Manager grant allows **arbitrary new secret names**
  in the preview project. A requested secret-name prefix cannot be restricted by
  the old Secret-resource condition because
  [CreateSecret](https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/create)
  authorizes `secretmanager.secrets.create` on the parent project. It does not
  grant payload access or management of existing non-PR secrets. Existing
  prefix-scoped management grants remain unchanged.
- Source registry reads cover **all packages in that repository**, not just the
  engine package. The future trusted copy code must validate the engine path and
  immutable digest. No source image-copy implementation is included here.

The accepted deployer remains preview-secret-equivalent through its existing
Cloud Run authority and runtime `actAs`; absence of direct Secret Manager
payload permission is not a claim of effective isolation from preview runtime
secrets. No production/staging secret authority or provisioner `actAs` is added.

## Operator ordering and live acceptance (not executed)

After review/merge, an authorized operator must:

1. Confirm both root backends and project IDs using their existing state.
   Do not move/import resources or initialize either root into per-PR state.
2. Plan the preview foundation with the existing accepted inputs, image, and
   password rotation triggers. Preserve `provisioner_image` and do not reset the
   accepted provisioner or rotate credentials. Review only the new IAP/quota
   roles/grants, creation-grant correction, and preview SQL API declaration.
   Stop on unrelated SQL/runtime/secret changes; apply only an approved plan.
   Foundation inputs remain ephemeral/write-only and operator-held.
3. Plan the existing application root with staging services still enabled and
   current inputs. Review the new metadata role/service member and repository
   reader member only. Stop on runtime, image, DB, secret, or existing-policy
   changes. Apply only the approved plan after the deployer identity exists.
4. Allow for IAM propagation and run explicit authorization acceptance below
   as the intended deployer, not as a project Owner. Only then consider the
   separately reviewed secret/interface follow-up and 41C.

Future backend/provider credential routing remains distinct: use direct
federated credential configuration as the GCS backend's credential source, so
its fixed `impersonate_service_account` performs one impersonation to the preview
deployer. Supply service-account-impersonated ADC to the Google provider.
Do not feed already-impersonated deployer credentials through a second backend
impersonation and repair the failure with deployer self Token Creator.
No such grant is added. Keep exact-ref WIF, a fresh trusted runner,
PR-specific `TF_DATA_DIR`, the default workspace, and the existing backend guard.
Never execute PR-controlled Terraform/scripts after authentication.

Live acceptance must isolate the new grants from broader inherited grants:

| Positive check | Negative check |
| --- | --- |
| Read a disposable preview frontend IAP service policy; add/remove an approved tester while preserving other roles/members | Reject adding/removing `roles/iap.admin`, mixed tester/admin changes, non-service IAP policies, and IAP writes outside the preview project |
| Preview-prefixed container creation works; a disposable non-prefixed container can be created, documenting the intended limitation | Reject managing existing non-prefixed/shared containers and direct durable-secret payload access; creation outside the preview project remains denied |
| Quota-billed preview provider requests work | No service enable/disable or quota-update authority from the new quota role |
| Read staging engine service and named serving revision metadata | No source production-service access, service/revision listing, invocation, runtime changes, deletion, or IAM writes from the new role |
| Read an existing source-repository image manifest as deployer | No source push/tag/delete, and no new source grant to preview runtime/service-agent identities |

For negative mutations, use IAM policy simulation/troubleshooter where supported
and safe operator-owned disposable resources where an actual API call is needed.
Do not probe destructive calls against production/staging. For payload-denial
checks, use authorization tooling or a non-sensitive canary; do not request real
durable payloads. The operator cleans up disposable non-prefixed secrets, since
the deployer intentionally cannot manage them.

Also verify the actual preview project number (not its ID suffix), enabled APIs,
IAP service agent and project-level no-org/external-user OAuth bootstrap, tester
allowlist, OpenAI version, effective runtime/SQL grants and cross-project socket
connection. Do not add per-PR OAuth callbacks, OAuth admin roles, or public access.
The SQL API declaration is not evidence of working connectivity.

## Manual WIF acceptance harness

The exact reviewed prerequisite plans at frontend source
`b4b4e1c090916977ea3c591d5d39c6fc07565dfd` were subsequently applied successfully:
foundation 6 add / 1 change / 1 destroy (serial 6 -> 8), application 3 add /
0 change / 0 destroy (serial 27 -> 28). Authoritative inspection found no
unreviewed mutations. **Do not reapply those consumed plans.** Effective
deployer acceptance remains pending; the local operator has no impersonation
grant by design.

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
The live condition/mapping and deployer service-account policy still accept
only the two documented main workflow refs. No operator impersonation or
deployer self Token Creator is introduced.

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

Under current permissions/evidence these required gaps make the overall workflow
fail, even if supported tests pass. They require a separately reviewed acceptance
disposition/operator authorization-tooling procedure, not automatic role changes.
The broader prerequisite checks for IAP OAuth/browser bootstrap, tester allowlist,
OpenAI version metadata, effective SQL grants and cross-project `SELECT 1` are
still operator/runtime acceptance and are **not** claimed by this workflow.

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
tests). CI runs the same checks without credentials. No cloud acceptance or
workflow dispatch occurs in this PR.

## Offline validation

```bash
make tf-fmt
make tf-validate
make tf-preview-iam-test
make tf-preview-db-test
make tf-preview-pr-test
git diff --check
```

The new standard-library tests assert source-level permission sets, scopes,
conditions, additive ownership, staging gating, existing version permissions,
tester scope and authentication boundaries. Backend-disabled validation checks
the pinned provider schemas. Existing per-PR tests use mocked plans. **None of
these evaluates live IAM conditions or proves effective cloud authorization.**

## Next secret preparation/interface PR: proposed, not implemented

Recommend one coherent follow-up containing the fixed provisioner and its
per-PR interface, rather than deploying a broker that the root cannot consume.
It needs separate approval for provisioner access to the preview app-password
version, per-PR version writes/metadata, and private metadata-ledger storage.
It must not return DATABASE_URL, NextAuth, or service-token payloads to a runner.
The current provisioner only creates/drops databases; it does not already have
these capabilities.

### Three distinct identities

- **Lifecycle/incarnation:** `(repository key, canonical PR number, incarnation
  UUID)`. Trusted control-plane state assigns a new UUID only after completed
  close/teardown and an explicitly validated reopen. Commit SHA and workflow
  attempt are not incarnation IDs. An incarnation remains closing/tombstoned
  until in-flight writes, executions, runtime, secrets and DB are reconciled.
- **Secret generation:** `(incarnation, generation UUID)`, with an explicit
  rotation request and pinned durable app-password version. Initial creation
  allocates one generation; pushes reuse it. Generation identities are never
  recycled or inferred from `latest` or Secret Manager version numbers.
- **Operation:** durable UUID plus immutable request tuple `(incarnation,
  generation, prepare|rotate|close, expected lifecycle revision)`. An HTTP retry
  uses the same operation ID; reusing it with a different tuple is a conflict.
  GitHub run/attempt IDs are audit metadata, not idempotency identities.

### Candidate identification and lost responses

Use distinct generation/incarnation-qualified candidate containers for each
secret kind, with bounded canonical names owned by per-PR Terraform. This is
an intentional future per-PR interface/name change, not a change in this PR.
The metadata ledger records exact container IDs, operation/generation identity,
pre-write version inventory, append intent and returned numeric version IDs.
It records no payloads, credential hashes, or encoded credentials.

The [addVersion request](https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/addVersion)
has no caller-defined idempotency key/operation label.
Do not correlate retries by creation time, `latest`, highest version number,
or a version watermark in a shared container. Dedicated containers, an exclusive
writer and a recorded initially empty inventory make an otherwise unattributed
successful append identifiable only if exactly one candidate exists.

Before each `addVersion`, persist an append intent and disable SDK/transport
automatic retries for that non-idempotent call. Permit at most one submitted
append per kind/operation; retrying an HTTP prepare request must not reissue it.
If the call succeeds but the response or ledger commit is lost, do not immediately
append again. Once writer
quiescence and a complete inventory are established, adopt the sole enabled
candidate for that exact operation's dedicated container, record its numeric ID,
and publish the generation only after all three kinds are complete. Reuse the
mapping without reading payloads on pushes/retries. If a previous generation
exists, leave it serving while preparing a new one.

If an append is definitively known not to have been submitted, it can be retried.
An ambiguous submitted request with no visible version is **not** evidence that
it failed: a late commit may still arrive. Multiple candidates, unexpected
writers, destroyed/disabled candidates, mismatched identities or uncertain
in-flight completion require `RECONCILIATION_REQUIRED`, no rollout and no
automatic regeneration. Operator reconciliation may abandon the generation and
allocate a fresh one only after quiescence, without reusing its containers.

### Fencing and stale workers

GCS compare-and-swap can serialize ledger changes but **cannot fence Secret
Manager writes**. Cloud Run concurrency/max-instance settings are not a global
writer lock across revisions. An expiring lease followed by automatic takeover
is therefore not a safe protocol.

The smallest safe v1 is a durable, **non-expiring exclusive operation reservation**
per repository/PR, with no automatic lock stealing. Expiration of a request,
worker heartbeat or workflow only marks the operation indeterminate; it does
not authorize a replacement writer, teardown or reopen. A worker may continue
reconciliation for its operation while the lifecycle remains reserved; check
the immutable operation/incarnation before every side effect and publication.
Teardown and reopen cannot transition past that reservation.

Record a unique service-internal owner-session ID separately from the operation
idempotency key. Duplicate HTTP requests may observe committed/pending metadata
but may not become another writer merely because their operation ID matches.
Persist and compare the owner-session ID when claiming each append intent.
The same reservation must serialize the fixed provisioner's DB create/drop
operations and close/reopen transitions, not just secret preparation, because
the logical DB name is reused across incarnations.

Release only after confirmed API outcomes and no in-flight side effects. If the
worker/session is lost, fail closed until an operator establishes the old writer
cannot resume and outstanding Secret Manager requests have been reconciled.
This can require stopping/draining all old provisioner revisions, temporarily
revoking their version-write authority and verifying propagation before repair.
Revocation alone does not cancel already accepted writes. Waiting for a lease
timeout, inspecting a stale heartbeat, or a single zero-version listing is not
proof of quiescence. If that proof cannot be established, retain the blocked
reservation; do not claim unattended recovery. Reopen stays blocked.

Generation/incarnation-qualified destinations additionally keep old candidates
out of a new runtime's references, but are not authorization fencing by
themselves. If automatic takeover is required, design and review a genuinely
fenced sole writer or operation-scoped identity/resource isolation first; do not
patch it with another GCS CAS. This conservative v1 trades availability during
ambiguous failures for correctness and makes operator recovery explicit.

### Ownership, rotation, teardown and tests

The follow-up should atomically introduce provisioner version ownership and
numeric version inputs in the per-PR root, remove its payload/version resources,
and create/retain generation-qualified containers and runtime grants there.
Foundation still owns durable credentials, the fixed trusted image/identity and
metadata storage. Drop unnecessary deployer version-mutation permissions only
with the working replacement path. No payload data source, Terraform output,
runner response, artifact, ledger object or log is permitted.

After successful migration and rollout, commit the serving mapping; retain old
versions/containers until no runtime references them. Internal-token rotation
needs a reviewed coordinated window with the current single-token contract;
NextAuth rotation invalidates sessions. Shared SQL-password rotation requires
coordination across every active preview; retaining old URL secrets does not
keep old SQL passwords valid. Close tombstones the incarnation, drains work,
destroys runtime/parent secrets, drops the DB through the fixed provisioner,
then removes only that incarnation's metadata/state. Delayed old requests must
be rejected before a reopen can allocate a new incarnation.

Test crash points before/after every append/ledger commit, lost HTTP responses,
duplicate/conflicting operation IDs, simultaneous calls, stopped/stale workers,
uncertain API completion, failed rotation, closed/reopened PRs, and late writes.
Assert metadata-only responses and fail-closed ambiguous recovery. Preserve old
runtime/DB on failed preparation. Live gates later prove exact-image migration
success before rollout, IAP/private-engine behavior, update continuity and
idempotent teardown. Image capture/copy and the 41C workflow remain separate.
