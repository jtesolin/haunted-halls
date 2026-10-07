"""Manual main-only authorization checks. Never run locally against cloud resources."""

import copy
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT = "hh-preview-458395246135"
NUMBER = "1001419903197"
REGION = "us-east1"
DEPLOYER = f"hh-preview-deployer@{PROJECT}.iam.gserviceaccount.com"
RUNTIME = f"hh-preview-frontend@{PROJECT}.iam.gserviceaccount.com"
WORKFLOW_REF = "jtesolin/haunted-halls/.github/workflows/preview-deploy.yml@refs/heads/main"
PROVIDER = f"projects/{NUMBER}/locations/global/workloadIdentityPools/hh-preview-github/providers/github-preview"
SOURCE_PROJECT = "haunted-halls-development"
SOURCE_REPOSITORY = f"projects/{SOURCE_PROJECT}/locations/{REGION}/repositories/haunted-halls"
STAGING = f"projects/{SOURCE_PROJECT}/locations/{REGION}/services/haunted-halls-engine-staging"
# Public Cloud Run hello sample, resolved read-only and fixed for review; no app/DB code.
CANARY_IMAGE = "gcr.io/cloudrun/hello@sha256:ea86b59c787261f424f9de114900e598f19e036c73aa95ff12b6ad5f022122fd"
TESTER_ROLE = "roles/iap.httpsResourceAccessor"
TESTER = f"serviceAccount:{DEPLOYER}"
CHECKS = [
    "Identity", "Preview project", "Canary creation permissions", "IAP policy read",
    "IAP tester add/remove", "IAP admin denial", "IAP mixed-role denial",
    "IAP non-WebService denial", "IAP outside-project denial",
    "Prefixed secret creation", "Non-prefixed secret creation",
    "Canary payload access denial", "Existing non-prefixed secret management denial",
    "Outside-project secret creation denial", "Preview quota request",
    "API/quota administration denial", "Staging service read", "Ready serving revision read",
    "Production engine read denial", "Source service listing denial",
    "Source revision listing denial", "Source runtime/invocation/IAM denial",
    "Source manifest read", "Source registry write denial", "Source runtime reader audit",
]


class CheckError(Exception):
    pass


class ApiError(CheckError):
    def __init__(self, status, code):
        super().__init__(f"HTTP {status}, {code}")
        self.status = status
        self.code = code


def request(url, token=None, method="GET", body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                raise CheckError("Unexpected response shape; contents withheld")
            return parsed
    except urllib.error.HTTPError as error:
        # Never print response bodies, request URLs, headers or credential-bearing exceptions.
        try:
            code = json.loads(error.read()).get("error", {}).get("status", "UNKNOWN")
        except (ValueError, AttributeError):
            code = "UNKNOWN"
        if code not in {"PERMISSION_DENIED", "NOT_FOUND", "ALREADY_EXISTS", "INVALID_ARGUMENT", "UNAUTHENTICATED"}:
            code = "UNKNOWN"
        raise ApiError(error.code, code) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise CheckError("Transport/JSON failure; outcome may be ambiguous") from None


def trusted_context(env):
    expected = {
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "jtesolin/haunted-halls", "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "GCP_PROJECT": PROJECT, "WIF_PROVIDER": PROVIDER, "DEPLOY_SERVICE_ACCOUNT": DEPLOYER,
        "GITHUB_ACTIONS": "true",
    }
    if any(env.get(key) != value for key, value in expected.items()):
        raise CheckError("Untrusted workflow context")
    if not re.fullmatch(r"[a-f0-9]{40}", env.get("GITHUB_SHA", "")):
        raise CheckError("Invalid trusted source SHA")
    run, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    if not all(re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in (run, attempt)):
        raise CheckError("Invalid run identity")
    identity = f"{run}-{attempt}"
    if len("hh-web-iam-accept-" + identity) > 49:
        raise CheckError("Run identity exceeds Cloud Run naming limit")
    return identity


def verified_token():
    result = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True,
                            text=True, check=False, timeout=60)
    token = result.stdout.strip()
    if result.returncode or not token or any(c.isspace() for c in token):
        raise CheckError("Preview access-token acquisition failed; diagnostics withheld")
    info = request("https://oauth2.googleapis.com/tokeninfo?" +
                   urllib.parse.urlencode({"access_token": token}))
    expiry = str(info.get("expires_in", ""))
    if (info.get("email") != DEPLOYER or not re.fullmatch(r"[0-9]{1,10}", expiry)
            or int(expiry) < 60):
        raise CheckError("Token does not prove the exact preview deployer")
    return token


def changed_policy(policy, role, member):
    updated = copy.deepcopy(policy)
    updated["version"] = 3
    bindings = updated.setdefault("bindings", [])
    for binding in bindings:
        if binding["role"] == role and not binding.get("condition"):
            if member not in binding["members"]:
                binding["members"].append(member)
            break
    else:
        bindings.append({"role": role, "members": [member]})
    return updated


def canonical_policy(policy):
    bindings = [{**b, "members": sorted(b.get("members", []))} for b in policy.get("bindings", [])]
    return sorted(bindings, key=lambda b: json.dumps(b, sort_keys=True))


class Harness:
    def __init__(self, identity, token, path):
        self.identity, self.token, self.path = identity, token, path
        self.service_name = f"hh-web-iam-accept-{identity}"
        self.service = f"projects/{PROJECT}/locations/{REGION}/services/{self.service_name}"
        self.prefixed = f"hh-web-pr-acceptance-{identity}"
        self.nonprefixed = f"iam-web-acceptance-{identity}"
        self.labels = {"hh-purpose": "iam-acceptance", "hh-repository": "web", "hh-run": identity.split("-")[0],
                       "hh-attempt": identity.split("-")[1]}
        self.report = {"principal": DEPLOYER, "project": PROJECT, "projectNumber": NUMBER,
                       "checks": {name: {"result": "NOT RUN"} for name in CHECKS},
                       "canaries": {}, "cleanup": {}}

    def save(self):
        self.path.write_text(json.dumps(self.report, indent=2) + "\n")
        self.path.chmod(0o600)

    def api(self, url, method="GET", body=None, headers=None):
        return request(url, self.token, method, body, headers)

    def check(self, name, operation):
        try:
            evidence = operation()
            self.require(isinstance(evidence, str) and bool(evidence), "Missing sanitized check evidence")
            self.report["checks"][name] = {"result": "PASS", "evidence": evidence}
        except CheckError as error:
            self.report["checks"][name] = {"result": "FAIL", "evidence": str(error)}
        self.save()

    def require(self, condition, message):
        if not condition:
            raise CheckError(message)

    def denied(self, operation):
        try:
            operation()
        except ApiError as error:
            if error.status == 403 and error.code == "PERMISSION_DENIED":
                return "Expected HTTP 403 PERMISSION_DENIED"
            raise
        raise CheckError("Unexpected authorization success")

    def permissions(self, url, allowed, denied):
        response = self.api(url + ":testIamPermissions", "POST",
                            {"permissions": allowed + denied})
        granted = set(response.get("permissions", []))
        self.require(set(allowed).issubset(granted), "Positive permission control missing")
        self.require(not granted.intersection(denied), "Forbidden permission granted")
        return "Positive control present; all requested negative permissions absent"

    def poll(self, operation):
        prefixes = tuple(f"projects/{project}/locations/{REGION}/operations/" for project in (PROJECT, NUMBER))
        self.require(operation.get("name", "").startswith(prefixes), "Unexpected operation boundary")
        for _ in range(120):
            if operation.get("done"):
                self.require("error" not in operation, "Cloud Run operation failed; details withheld")
                return
            time.sleep(5)
            operation = self.api("https://run.googleapis.com/v2/" + operation["name"])
        raise CheckError("Cloud Run operation incomplete; cleanup will reconcile")

    def absent(self, url):
        try:
            self.api(url)
        except ApiError as error:
            if error.status == 404 and error.code == "NOT_FOUND":
                return
            raise
        raise CheckError("Canary already exists; refusing adoption")

    def create_service(self):
        url = "https://run.googleapis.com/v2/" + self.service
        self.absent(url)
        self.report["canaries"]["service"] = {"name": self.service, "attempted": True}
        self.save()
        operation = self.api(
            f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/services?serviceId={self.service_name}",
            "POST", {
                "labels": self.labels, "iapEnabled": True, "ingress": "INGRESS_TRAFFIC_ALL",
                "template": {"serviceAccount": RUNTIME, "scaling": {"minInstanceCount": 0, "maxInstanceCount": 1},
                             "containers": [{"image": CANARY_IMAGE, "resources": {
                                 "limits": {"cpu": "1", "memory": "256Mi"}, "cpuIdle": True}}]},
            })
        self.report["canaries"]["service"]["operation"] = operation.get("name")
        self.save()
        self.poll(operation)
        self.report["canaries"]["service"]["creation_complete"] = True
        self.save()
        current = self.api(url + ":getIamPolicy")
        agent = f"serviceAccount:service-{NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
        self.api(url + ":setIamPolicy", "POST", {"policy": changed_policy(current, "roles/run.invoker", agent)})
        return "Disposable IAP hello service created; service-scoped IAP agent invocation only"

    def iap_policy(self):
        return self.api(self.iap_url + ":getIamPolicy?options.requestedPolicyVersion=3")

    def iap_positive(self):
        original = self.iap_policy()
        self.require(not any(TESTER in b.get("members", []) for b in original.get("bindings", [])
                             if b["role"] == TESTER_ROLE and not b.get("condition")),
                     "Tester already present on fresh canary")
        # An expired tester binding is an unrelated live preservation control,
        # without granting anyone access or requiring broader policy permissions.
        seeded = copy.deepcopy(original)
        seeded["version"] = 3
        control = {"role": TESTER_ROLE, "members": [TESTER], "condition": {
            "title": "acceptance-preservation-control",
            "expression": 'request.time < timestamp("2000-01-01T00:00:00Z")'}}
        seeded.setdefault("bindings", []).append(control)
        self.api(self.iap_url + ":setIamPolicy", "POST", {"policy": seeded})
        before = self.iap_policy()
        self.require(canonical_policy(before) == canonical_policy(seeded), "IAP control creation mismatch")
        self.api(self.iap_url + ":setIamPolicy", "POST",
                 {"policy": changed_policy(before, TESTER_ROLE, TESTER)})
        after = self.iap_policy()
        self.require(canonical_policy(after) == canonical_policy(changed_policy(before, TESTER_ROLE, TESTER)),
                     "IAP changed unrelated entries")
        restore = {**before, "etag": after["etag"], "version": 3}
        self.api(self.iap_url + ":setIamPolicy", "POST", {"policy": restore})
        restored = self.iap_policy()
        self.require(canonical_policy(restored) == canonical_policy(before), "IAP unrelated control changed")
        self.api(self.iap_url + ":setIamPolicy", "POST",
                 {"policy": {**original, "etag": restored["etag"], "version": 3}})
        self.require(canonical_policy(self.iap_policy()) == canonical_policy(original), "IAP restore mismatch")
        return "Tester added/removed; unrelated expired conditional binding preserved and removed"

    def iap_negative(self, mixed=False):
        before = self.iap_policy()
        proposed = changed_policy(before, "roles/iap.admin", TESTER)
        if mixed:
            proposed = changed_policy(proposed, TESTER_ROLE, TESTER)
        evidence = self.denied(lambda: self.api(self.iap_url + ":setIamPolicy", "POST", {"policy": proposed}))
        self.require(canonical_policy(self.iap_policy()) == canonical_policy(before), "Denied policy changed")
        return evidence

    def create_secret(self, prefixed):
        key, name = ("prefixed", self.prefixed) if prefixed else ("nonprefixed", self.nonprefixed)
        # CreateSecret is atomic and must return ALREADY_EXISTS rather than adopting a resource.
        self.report["canaries"][key] = {"name": f"projects/{NUMBER}/secrets/{name}", "attempted": True}
        self.save()
        try:
            response = self.api(f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets?secretId={name}",
                                "POST", {"replication": {"automatic": {}}, "labels": self.labels})
        except ApiError as error:
            if ((error.status, error.code) in {(409, "ALREADY_EXISTS"), (403, "PERMISSION_DENIED"),
                                              (400, "INVALID_ARGUMENT")}):
                self.report["canaries"][key]["attempted"] = False
                self.save()
            raise
        self.require(response.get("name") == f"projects/{NUMBER}/secrets/{name}", "Secret boundary mismatch")
        self.report["canaries"][key]["created"] = True
        self.save()
        return f"Created {response['name']}"

    def payload_denial(self):
        url = f"https://secretmanager.googleapis.com/v1/projects/{NUMBER}/secrets/{self.prefixed}"
        # A fixed, explicitly non-sensitive payload; never use durable credentials.
        version = self.api(url + ":addVersion", "POST", {"payload": {"data": "aWFtLWFjY2VwdGFuY2UtY2FuYXJ5"}})
        self.require(version.get("name", "").startswith(f"projects/{NUMBER}/secrets/{self.prefixed}/versions/"),
                     "Version boundary mismatch")
        return self.denied(lambda: self.api("https://secretmanager.googleapis.com/v1/" + version["name"] + ":access"))

    def serving_revision(self):
        service = self.api("https://run.googleapis.com/v2/" + STAGING)
        self.require(service.get("terminalCondition", {}).get("state") == "CONDITION_SUCCEEDED",
                     "Staging service not Ready")
        serving = [t for t in service.get("trafficStatuses", []) if t.get("percent", 0) > 0]
        self.require(len(serving) == 1 and serving[0]["percent"] == 100, "Ambiguous serving revision")
        revision = serving[0].get("revision", "")
        # API trafficStatuses may return a full name; never accept an arbitrary returned path.
        revision = revision.removeprefix(STAGING + "/revisions/")
        self.require(bool(re.fullmatch(r"haunted-halls-engine-staging-[a-z0-9-]+", revision)), "Revision boundary mismatch")
        full = STAGING + "/revisions/" + revision
        self.require(service.get("latestReadyRevision") == full, "Serving revision not latest Ready")
        self.revision = self.api("https://run.googleapis.com/v2/" + full)
        self.require(self.revision.get("name") == full, "Named revision response mismatch")
        return full

    def manifest(self):
        image = self.revision.get("containers", [{}])[0].get("image", "")
        prefix = f"{REGION}-docker.pkg.dev/{SOURCE_PROJECT}/haunted-halls/engine@"
        self.require(image.startswith(prefix) and bool(re.fullmatch(r"sha256:[a-f0-9]{64}", image[len(prefix):])),
                     "Serving engine image not an immutable accepted source reference")
        digest = image[len(prefix):]
        manifest = self.api(f"https://{REGION}-docker.pkg.dev/v2/{SOURCE_PROJECT}/haunted-halls/engine/manifests/{digest}",
                            headers={"Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"})
        self.require(manifest.get("schemaVersion") == 2, "Unsupported manifest")
        return f"Read manifest {digest}; no image capture/copy"

    def source_audit(self):
        try:
            policy = self.api("https://artifactregistry.googleapis.com/v1/" + SOURCE_REPOSITORY + ":getIamPolicy")
        except ApiError as error:
            if error.status == 403 and error.code == "PERMISSION_DENIED":
                raise CheckError("BLOCKED: source reader has no getIamPolicy; separate operator audit required") from None
            raise
        identities = {f"serviceAccount:hh-preview-{kind}@{PROJECT}.iam.gserviceaccount.com"
                      for kind in ("frontend", "engine", "migration")}
        identities.update({f"serviceAccount:service-{NUMBER}@serverless-robot-prod.iam.gserviceaccount.com",
                           f"serviceAccount:service-{NUMBER}@gcp-sa-iap.iam.gserviceaccount.com",
                           f"serviceAccount:{NUMBER}@cloudservices.gserviceaccount.com"})
        for binding in policy.get("bindings", []):
            self.require(not identities.intersection(binding.get("members", [])),
                         "Source repository grant to preview runtime/service agent found")
        return "No source repository policy grants to preview runtime/service-agent identities"

    def run(self):
        self.check("Identity", lambda: "Exact preview deployer token verified")
        self.check("Preview project", self.project)
        self.check("Canary creation permissions", self.canary_permissions)
        if any(self.report["checks"][name]["result"] != "PASS"
               for name in ("Identity", "Preview project", "Canary creation permissions")):
            return
        self.iap_url = f"https://iap.googleapis.com/v1/projects/{NUMBER}/iap_web/cloud_run-{REGION}/services/{self.service_name}"
        self.check("IAP policy read", self.setup_iap)
        if self.report["checks"]["IAP policy read"]["result"] == "PASS":
            self.check("IAP tester add/remove", self.iap_positive)
            if self.report["checks"]["IAP tester add/remove"]["result"] == "PASS":
                self.check("IAP admin denial", self.iap_negative)
                if self.report["checks"]["IAP admin denial"]["result"] == "PASS":
                    self.check("IAP mixed-role denial", lambda: self.iap_negative(True))
        # Non-mutating authorization queries only; no policy write outside the canary.
        self.check("IAP non-WebService denial", lambda: self.permissions(
            f"https://iap.googleapis.com/v1/projects/{NUMBER}/iap_web",
            [], ["iap.web.setIamPolicy"]))
        self.check("IAP outside-project denial", self.outside_iap)
        self.check("Prefixed secret creation", lambda: self.create_secret(True))
        self.check("Non-prefixed secret creation", lambda: self.create_secret(False))
        if self.report["checks"]["Prefixed secret creation"]["result"] == "PASS":
            self.check("Canary payload access denial", self.payload_denial)
        if self.report["checks"]["Non-prefixed secret creation"]["result"] == "PASS":
            self.check("Existing non-prefixed secret management denial", lambda: self.permissions(
                f"https://secretmanager.googleapis.com/v1/projects/{NUMBER}/secrets/{self.nonprefixed}",
                [], ["secretmanager.secrets.update", "secretmanager.secrets.delete",
                     "secretmanager.secrets.setIamPolicy", "secretmanager.versions.add", "secretmanager.versions.access"]))
        self.check("Outside-project secret creation denial", lambda: self.permissions(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{SOURCE_PROJECT}",
            [], ["secretmanager.secrets.create"]))
        self.check("Preview quota request", self.quota_request)
        self.check("API/quota administration denial", lambda: self.permissions(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}",
            ["serviceusage.services.use"],
            ["serviceusage.services.enable", "serviceusage.services.disable", "serviceusage.quotas.update"]))
        self.check("Staging service read", self.staging_read)
        self.check("Ready serving revision read", self.serving_revision)
        self.check("Production engine read denial", lambda: self.denied(
            lambda: self.api("https://run.googleapis.com/v2/" + STAGING.removesuffix("-staging"))))
        self.check("Source service listing denial", lambda: self.denied(lambda: self.api(
            f"https://run.googleapis.com/v2/projects/{SOURCE_PROJECT}/locations/{REGION}/services?pageSize=1")))
        self.check("Source revision listing denial", lambda: self.denied(lambda: self.api(
            "https://run.googleapis.com/v2/" + STAGING + "/revisions?pageSize=1")))
        self.check("Source runtime/invocation/IAM denial", lambda: self.permissions(
            "https://run.googleapis.com/v2/" + STAGING, ["run.services.get"],
            ["run.services.update", "run.services.delete", "run.services.setIamPolicy", "run.routes.invoke"]))
        if self.report["checks"]["Ready serving revision read"]["result"] == "PASS":
            self.check("Source manifest read", self.manifest)
        self.check("Source registry write denial", lambda: self.permissions(
            "https://artifactregistry.googleapis.com/v1/" + SOURCE_REPOSITORY,
            ["artifactregistry.repositories.downloadArtifacts"],
            ["artifactregistry.repositories.uploadArtifacts", "artifactregistry.repositories.deleteArtifacts",
             "artifactregistry.tags.create", "artifactregistry.tags.update", "artifactregistry.tags.delete"]))
        self.check("Source runtime reader audit", self.source_audit)

    def project(self):
        project = self.api(f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}")
        self.require(project.get("projectId") == PROJECT and str(project.get("projectNumber")) == NUMBER,
                     "Preview project identity mismatch")
        return f"{PROJECT} / {NUMBER}"

    def quota_request(self):
        self.api(f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/services?pageSize=1",
                 headers={"x-goog-user-project": PROJECT})
        return "Preview-project quota-billed read succeeded"

    def staging_read(self):
        service = self.api("https://run.googleapis.com/v2/" + STAGING)
        self.require(service.get("name") == STAGING, "Staging named service response mismatch")
        return STAGING

    def outside_iap(self):
        # A parent-policy denial does not prove a WebService denial; no accepted
        # outside-project disposable IAP WebService exists for a reliable probe.
        raise CheckError("BLOCKED: no approved outside-project IAP WebService canary; no production/staging IAP mutations")

    def canary_permissions(self):
        self.permissions(f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}",
                         ["run.services.create", "run.services.delete", "run.services.setIamPolicy"], [])
        self.permissions(f"https://iam.googleapis.com/v1/projects/-/serviceAccounts/{RUNTIME}",
                         ["iam.serviceAccounts.actAs"], [])
        return "Existing preview Run Admin + frontend actAs; no permission expansion"

    def setup_iap(self):
        self.create_service()
        self.iap_policy()
        return "Created private disposable IAP hello service and read service policy"

    def cleanup(self):
        for key in ("service", "prefixed"):
            canary = self.report["canaries"].get(key)
            if not canary or not canary.get("attempted"):
                continue
            url = ("https://run.googleapis.com/v2/" + self.service if key == "service" else
                   f"https://secretmanager.googleapis.com/v1/projects/{NUMBER}/secrets/{self.prefixed}")
            try:
                if key == "service" and not canary.get("creation_complete"):
                    if not canary.get("operation"):
                        raise CheckError("Creation response lost; cannot prove writer quiescence")
                    self.poll({"name": canary["operation"]})
                    canary["creation_complete"] = True
                    self.save()
                current = self.api(url)
                self.require(all(current.get("labels", {}).get(k) == v for k, v in self.labels.items()),
                             "Ownership labels mismatch; refusing cleanup")
                response = self.api(url, "DELETE")
                if key == "service":
                    self.poll(response)
                self.absent(url)
                self.report["cleanup"][key] = "PASS: deletion verified"
            except ApiError as error:
                confirmed = canary.get("created") if key == "prefixed" else canary.get("creation_complete")
                self.report["cleanup"][key] = ("PASS: already absent" if confirmed and error.status == 404 and error.code == "NOT_FOUND"
                                               else f"FAIL: {error}; operator reconciliation required")
            except CheckError as error:
                self.report["cleanup"][key] = f"FAIL: {error}; operator reconciliation required"
            self.save()
        canary = self.report["canaries"].get("nonprefixed")
        if canary and canary.get("attempted"):
            self.report["cleanup"]["nonprefixed"] = (
                "OPERATOR CLEANUP REQUIRED: " + canary["name"] +
                (" (creation confirmed)" if canary.get("created") else " (creation outcome unconfirmed)"))
        self.save()

    def summary(self):
        lines = ["## Preview prerequisite acceptance", "",
                 f"Principal: `{self.report.get('principal', 'UNVERIFIED')}`",
                 f"Preview project: `{PROJECT}` / `{NUMBER}`", "",
                 "| Check | Result | Evidence |", "|---|---|---|"]
        for name, check in self.report["checks"].items():
            lines.append(f"| {name} | {check['result']} | {check.get('evidence', '').replace('|', '/')} |")
        lines += ["", "### Canaries and cleanup"]
        for key, canary in self.report["canaries"].items():
            cleanup = ("NOT OWNED: creation definitively rejected; no cleanup attempted"
                       if not canary.get("attempted") else
                       self.report["cleanup"].get(key, "UNRESOLVED; operator reconciliation required"))
            lines.append(f"- `{canary['name']}`: {cleanup}")
        if not self.report["canaries"]:
            lines.append("- No canary creation attempted.")
        lines += ["", "No Terraform, real preview DB, migration, application-image rollout, or image copy.",
                  "Source-policy audit cannot be proven by reader-only credentials; a BLOCKED result fails acceptance."]
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
            output.write("\n".join(lines) + "\n")

    def passed(self):
        return (all(c["result"] == "PASS" for c in self.report["checks"].values()) and
                all(not c.startswith("FAIL") for c in self.report["cleanup"].values()))


def main():
    os.umask(0o077)
    if sys.argv[1:] not in (["run"], ["cleanup"]):
        raise CheckError("Only fixed run/cleanup modes are supported")
    identity = trusted_context(os.environ)
    path = Path(os.environ["RUNNER_TEMP"]) / "preview-prerequisite-acceptance.json"
    harness = Harness(identity, None, path)
    if sys.argv[1] == "cleanup" and path.exists():
        harness.report = json.loads(path.read_text())
    try:
        harness.token = verified_token()
        if sys.argv[1] == "run":
            harness.run()
        else:
            harness.cleanup()
    except (CheckError, subprocess.TimeoutExpired):
        harness.report["checks"]["Identity"] = {"result": "FAIL", "evidence": "Exact deployer credential verification failed"}
        harness.report["principal"] = "UNVERIFIED"
        harness.save()
    finally:
        if sys.argv[1] == "cleanup":
            harness.summary()
    return 0 if harness.passed() else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CheckError, KeyError, ValueError, OSError):
        print("Acceptance harness failed closed; sensitive diagnostics withheld.", file=sys.stderr)
        sys.exit(1)
