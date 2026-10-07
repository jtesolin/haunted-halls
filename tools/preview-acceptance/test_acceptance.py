"""Offline workflow contracts and mocked transport tests; no cloud authorization proof."""

import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/preview-deploy.yml"
SPEC = importlib.util.spec_from_file_location("acceptance", Path(__file__).with_name("acceptance.py"))
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class WorkflowContracts(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text()

    def test_only_dispatch_no_inputs_or_automatic_lifecycle(self):
        self.assertEqual(self.workflow.split("on:\n")[1].split("\npermissions:")[0].strip(),
                         "workflow_dispatch:")
        for forbidden in ("pull_request_target", "pull_request:", "workflow_run:", "push:", "schedule:",
                          "inputs:", "inputs.", "github.event.inputs", "terraform", "migrate",
                          "docker build", "docker push", "preview-pr/", "engine-deployer", "production-promoter"):
            self.assertNotIn(forbidden, self.workflow)

    def test_exact_permission_set_and_hosted_runner(self):
        self.assertEqual(self.workflow.split("permissions:\n")[1].split("\nconcurrency:")[0].strip(),
                         "contents: read\n  id-token: write")
        self.assertIn("runs-on: ubuntu-latest", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_fixed_main_identity_and_checkout_before_auth(self):
        self.assertIn(acceptance.WORKFLOW_REF, self.workflow)
        self.assertIn("github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("github.repository == 'jtesolin/haunted-halls'", self.workflow)
        self.assertIn("ref: ${{ github.sha }}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertLess(self.workflow.index("Verify checked-out source"), self.workflow.index("id: auth"))
        self.assertEqual(WORKFLOW.relative_to(ROOT).as_posix(), ".github/workflows/preview-deploy.yml")

    def test_fixed_preview_provider_and_service_account(self):
        for value in (acceptance.PROJECT, acceptance.PROVIDER, acceptance.DEPLOYER):
            self.assertIn(value, self.workflow)
        source = (ROOT / "infra/terraform/preview-foundation/workload-identity.tf").read_text()
        self.assertIn(acceptance.WORKFLOW_REF, source)
        self.assertIn('workload_identity_pool_id = "hh-preview-github"', source)
        self.assertIn('workload_identity_pool_provider_id = "github-preview"', source)
        for forbidden in ("458395246135/locations/global", "haunted-halls-development.iam", "secrets.", "impersonate-service-account"):
            self.assertNotIn(forbidden, self.workflow)

    def test_existing_action_conventions_and_always_cleanup(self):
        for action in ("actions/checkout@v7", "google-github-actions/auth@v3", "google-github-actions/setup-gcloud@v3"):
            self.assertIn(action, self.workflow)
        self.assertIn("always() && steps.auth.outcome == 'success'", self.workflow)
        self.assertIn("python3 tools/preview-acceptance/acceptance.py cleanup", self.workflow)
        self.assertNotIn("continue-on-error", self.workflow)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.h = acceptance.Harness("37656163801-1", "fake-token",
                                    Path(self.directory.name) / "report.json")

    def test_context_rejects_pr_branch_arbitrary_project_and_invalid_run_ids(self):
        env = {
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "jtesolin/haunted-halls", "GITHUB_WORKFLOW_REF": acceptance.WORKFLOW_REF,
            "GITHUB_ACTIONS": "true", "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "37656163801",
            "GITHUB_RUN_ATTEMPT": "1", "GCP_PROJECT": acceptance.PROJECT,
            "WIF_PROVIDER": acceptance.PROVIDER, "DEPLOY_SERVICE_ACCOUNT": acceptance.DEPLOYER,
        }
        self.assertEqual(acceptance.trusted_context(env), "37656163801-1")
        for key, value in (("GITHUB_REF", "refs/heads/feature"), ("GITHUB_EVENT_NAME", "pull_request_target"),
                           ("GITHUB_WORKFLOW_REF", "different"), ("GCP_PROJECT", "other-project"),
                           ("DEPLOY_SERVICE_ACCOUNT", "owner@example.com"), ("GITHUB_RUN_ID", "../escape"),
                           ("GITHUB_RUN_ATTEMPT", "0"), ("GITHUB_RUN_ATTEMPT", "9" * 21)):
            with self.subTest(key=key), self.assertRaises(acceptance.CheckError):
                acceptance.trusted_context({**env, key: value})
        with self.assertRaisesRegex(acceptance.CheckError, "naming limit"):
            acceptance.trusted_context({**env, "GITHUB_RUN_ID": "9" * 20, "GITHUB_RUN_ATTEMPT": "9" * 20})

    def test_identity_requires_exact_token_principal(self):
        with patch.object(acceptance.subprocess, "run") as run, patch.object(acceptance, "request") as request:
            run.return_value.stdout = "fake-token\n"
            run.return_value.returncode = 0
            request.return_value = {"email": acceptance.DEPLOYER, "expires_in": 300}
            self.assertEqual(acceptance.verified_token(), "fake-token")
            request.return_value = {"email": "jack.tesolin@gmail.com", "expires_in": 300}
            with self.assertRaises(acceptance.CheckError):
                acceptance.verified_token()
            request.return_value = {"email": acceptance.DEPLOYER, "expires_in": None}
            with self.assertRaises(acceptance.CheckError):
                acceptance.verified_token()

    def test_http_errors_expose_only_status_not_credentials_or_response_bodies(self):
        body = io.BytesIO(b'{"error":{"status":"PERMISSION_DENIED","message":"payload fake-token"}}')
        error = acceptance.urllib.error.HTTPError(
            "https://oauth2.googleapis.com/tokeninfo?access_token=fake-token", 403, "secret response",
            {}, body)
        with patch.object(acceptance.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(acceptance.ApiError) as raised:
                acceptance.request("https://oauth2.googleapis.com/tokeninfo?access_token=fake-token")
        self.assertEqual(str(raised.exception), "HTTP 403, PERMISSION_DENIED")
        self.assertNotIn("fake-token", str(raised.exception))
        self.assertTrue(body.closed)

    def test_malformed_api_response_fails_without_echoing_content(self):
        with patch.object(acceptance.urllib.request, "urlopen") as response:
            response.return_value.__enter__.return_value.read.return_value = b'["fake-token"]'
            with self.assertRaisesRegex(acceptance.CheckError, "contents withheld"):
                acceptance.request("https://oauth2.googleapis.com/tokeninfo")

    def test_names_cannot_overlap_real_pr_resources(self):
        self.assertRegex(self.h.prefixed, r"^hh-web-pr-acceptance-[0-9]+-[0-9]+$")
        self.assertNotRegex(self.h.service_name, r"^hh-(web|engine)-pr-[0-9]+-")
        self.assertLessEqual(len(self.h.service_name), 49)

    def test_policy_edit_preserves_conditions_members_and_etag(self):
        original = {"etag": "etag", "version": 3, "bindings": [
            {"role": "roles/iap.admin", "members": ["user:operator@example.com"]},
            {"role": acceptance.TESTER_ROLE, "members": ["user:tester@example.com"],
             "condition": {"expression": "true", "title": "existing"}},
        ]}
        frozen = copy.deepcopy(original)
        updated = acceptance.changed_policy(original, acceptance.TESTER_ROLE, acceptance.TESTER)
        self.assertEqual(original, frozen)
        self.assertEqual(updated["bindings"][:2], frozen["bindings"])
        self.assertEqual(updated["etag"], "etag")
        self.assertEqual(updated["bindings"][2]["members"], [acceptance.TESTER])

    def test_positive_iap_write_and_restore_use_latest_etag(self):
        before = {"etag": "before", "bindings": [{"role": "roles/iap.admin", "members": ["user:op@example.com"]}]}
        self.h.iap_url = "https://iap.googleapis.com/v1/fixed-canary"
        current = copy.deepcopy(before)
        writes = []
        def write(url, method, body):
            nonlocal current
            self.assertEqual(body["policy"]["etag"], current["etag"])
            writes.append(copy.deepcopy(body["policy"]))
            current = copy.deepcopy(body["policy"])
            current["etag"] = str(len(writes))
        with patch.object(self.h, "iap_policy", side_effect=lambda: copy.deepcopy(current)), patch.object(self.h, "api", side_effect=write):
            self.h.iap_positive()
        self.assertEqual(len(writes), 4)
        self.assertEqual(writes[-1]["etag"], "3")
        self.assertEqual(writes[-1]["bindings"], before["bindings"])
        self.assertIn("condition", writes[1]["bindings"][1])
        self.assertEqual(writes[1]["bindings"][1], writes[2]["bindings"][1])

    def test_denial_requires_permission_denied_not_not_found_or_transport_error(self):
        def deny():
            raise acceptance.ApiError(403, "PERMISSION_DENIED")
        self.assertIn("Expected", self.h.denied(deny))
        for error in (acceptance.ApiError(404, "NOT_FOUND"), acceptance.ApiError(403, "UNKNOWN"),
                      acceptance.CheckError("transport")):
            with patch.object(self.h, "api", side_effect=error), self.assertRaises(acceptance.CheckError):
                self.h.denied(lambda: self.h.api("fixed-url"))
        with self.assertRaises(acceptance.CheckError):
            self.h.denied(lambda: {})

    def test_permission_negative_has_positive_control_when_available(self):
        with patch.object(self.h, "api", return_value={"permissions": ["run.services.get"]}):
            self.h.permissions("fixed-url", ["run.services.get"], ["run.services.delete"])
        for response in ({}, {"permissions": ["run.services.get", "run.services.delete"]}):
            with patch.object(self.h, "api", return_value=response), self.assertRaises(acceptance.CheckError):
                self.h.permissions("fixed-url", ["run.services.get"], ["run.services.delete"])

    def test_empty_successful_quota_read_has_sanitized_string_evidence(self):
        with patch.object(self.h, "api", return_value={}) as api:
            self.h.check("Preview quota request", self.h.quota_request)
        self.assertEqual(self.h.report["checks"]["Preview quota request"]["result"], "PASS")
        self.assertEqual(api.call_args.kwargs["headers"], {"x-goog-user-project": acceptance.PROJECT})
        self.h.check("Preview quota request", lambda: {"unsafe": "raw-response"})
        self.assertEqual(self.h.report["checks"]["Preview quota request"]["result"], "FAIL")
        self.assertNotIn("raw-response", self.h.path.read_text())

    def test_lro_polling_accepts_only_fixed_preview_operation_paths(self):
        for project in (acceptance.PROJECT, acceptance.NUMBER):
            with patch.object(self.h, "api", return_value={"done": True}), patch.object(acceptance.time, "sleep"):
                self.h.poll({"name": f"projects/{project}/locations/us-east1/operations/fixed"})
        with self.assertRaisesRegex(acceptance.CheckError, "boundary"):
            self.h.poll({"name": "projects/other/locations/us-east1/operations/fixed"})

    def test_ready_revision_and_manifest_only_read_exact_source(self):
        full = acceptance.STAGING + "/revisions/haunted-halls-engine-staging-00015-abc"
        service = {"terminalCondition": {"state": "CONDITION_SUCCEEDED"},
                   "trafficStatuses": [{"percent": 100, "revision": full}], "latestReadyRevision": full}
        image = f"us-east1-docker.pkg.dev/{acceptance.SOURCE_PROJECT}/haunted-halls/engine@sha256:" + "a" * 64
        with patch.object(self.h, "api", side_effect=[service, {"name": full, "containers": [{"image": image}]},
                                                    {"schemaVersion": 2}]) as api:
            self.h.serving_revision()
            self.h.manifest()
        self.assertTrue(all(len(call.args) == 1 for call in api.call_args_list))
        self.assertIn("/manifests/sha256:", api.call_args.args[0])
        self.h.revision = {"containers": [{"image": image.replace("engine@", "frontend@")}]}
        with self.assertRaises(acceptance.CheckError):
            self.h.manifest()

    def test_source_policy_audit_fails_closed_without_reader_permission(self):
        with patch.object(self.h, "api", side_effect=acceptance.ApiError(403, "PERMISSION_DENIED")):
            self.h.check("Source runtime reader audit", self.h.source_audit)
        self.assertEqual(self.h.report["checks"]["Source runtime reader audit"]["result"], "FAIL")
        self.assertIn("BLOCKED", self.h.report["checks"]["Source runtime reader audit"]["evidence"])
        self.assertFalse(self.h.passed())

    def test_outside_iap_cannot_claim_parent_denial_proves_service_denial(self):
        with self.assertRaisesRegex(acceptance.CheckError, "BLOCKED"), patch.object(self.h, "api") as api:
            self.h.outside_iap()
        api.assert_not_called()

    def test_no_runtime_policy_grants_allowed(self):
        policy = {"bindings": [{"role": "roles/artifactregistry.reader", "members": [acceptance.TESTER]}]}
        with patch.object(self.h, "api", return_value=policy):
            self.h.source_audit()
        policy["bindings"][0]["members"].append(f"serviceAccount:{acceptance.RUNTIME}")
        with patch.object(self.h, "api", return_value=policy), self.assertRaises(acceptance.CheckError):
            self.h.source_audit()

    def test_source_audit_version_three_and_conditional_membership(self):
        unrelated = {"role": "roles/artifactregistry.reader", "members": ["user:reviewer@example.com"],
                     "condition": {"title": "unrelated", "expression": "true"}}
        for member in (f"serviceAccount:{acceptance.RUNTIME}",
                       f"serviceAccount:service-{acceptance.NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"):
            for conditional in (False, True):
                binding = {"role": "roles/artifactregistry.reader", "members": [member]}
                if conditional:
                    binding["condition"] = {"title": "conditional", "expression": "true"}
                with patch.object(self.h, "api", return_value={"version": 3, "bindings": [unrelated, binding]}) as api:
                    with self.assertRaises(acceptance.CheckError):
                        self.h.source_audit()
                self.assertTrue(api.call_args.args[0].endswith(":getIamPolicy?options.requestedPolicyVersion=3"))
        policy = {"version": 3, "bindings": [unrelated]}
        frozen = copy.deepcopy(policy)
        with patch.object(self.h, "api", return_value=policy):
            self.h.source_audit()
        self.assertEqual(policy, frozen)

    def test_canary_spec_has_no_secret_db_public_grant_or_app_image(self):
        self.h.absent = lambda url: None
        self.h.poll = lambda operation: None
        with patch.object(self.h, "api", side_effect=[{"name": "fixed"}, {}, {}]) as api:
            self.h.create_service()
        spec = api.call_args_list[0].args[2]
        self.assertTrue(spec["iapEnabled"])
        template = spec["template"]
        self.assertEqual(template["serviceAccount"], acceptance.RUNTIME)
        self.assertEqual(template["scaling"], {"minInstanceCount": 0, "maxInstanceCount": 1})
        self.assertEqual(template["containers"][0]["image"], acceptance.CANARY_IMAGE)
        self.assertNotIn("env", template["containers"][0])
        self.assertNotIn("volumes", template)
        self.assertNotIn("allUsers", json.dumps(api.call_args_list[-1].args[2]))

    def test_cleanup_checks_ownership_and_never_deletes_nonprefixed_secret(self):
        self.h.report["canaries"] = {
            "prefixed": {"name": self.h.prefixed, "attempted": True, "created": True},
            "nonprefixed": {"name": self.h.nonprefixed, "attempted": True, "created": True}}
        with patch.object(self.h, "api", side_effect=[{"labels": self.h.labels}, {},
                                                    acceptance.ApiError(404, "NOT_FOUND")]) as api:
            self.h.cleanup()
        self.assertEqual([c.args[1] for c in api.call_args_list if len(c.args) > 1], ["DELETE"])
        self.assertIn("deletion verified", self.h.report["cleanup"]["prefixed"])
        self.assertIn("OPERATOR CLEANUP REQUIRED", self.h.report["cleanup"]["nonprefixed"])
        self.h.report["cleanup"] = {}
        with patch.object(self.h, "api", return_value={"labels": {}}) as api:
            self.h.cleanup()
        self.assertEqual(api.call_count, 1)
        self.assertIn("Ownership labels mismatch", self.h.report["cleanup"]["prefixed"])

    def test_lost_create_response_is_not_treated_as_successful_cleanup(self):
        self.h.report["canaries"]["service"] = {"name": self.h.service, "attempted": True}
        with patch.object(self.h, "api") as api:
            self.h.cleanup()
        api.assert_not_called()
        self.assertIn("quiescence", self.h.report["cleanup"]["service"])
        self.h.report["canaries"] = {"prefixed": {"name": self.h.prefixed, "attempted": True}}
        with patch.object(self.h, "api", side_effect=acceptance.ApiError(404, "NOT_FOUND")):
            self.h.cleanup()
        self.assertTrue(self.h.report["cleanup"]["prefixed"].startswith("FAIL"))

    def test_cleanup_failure_does_not_overwrite_original_acceptance_failure(self):
        self.h.report["checks"]["IAP admin denial"] = {"result": "FAIL", "evidence": "original failure"}
        self.h.report["canaries"]["prefixed"] = {"name": self.h.prefixed, "attempted": True}
        with patch.object(self.h, "api", side_effect=acceptance.ApiError(403, "PERMISSION_DENIED")):
            self.h.cleanup()
        self.assertEqual(self.h.report["checks"]["IAP admin denial"]["evidence"], "original failure")
        self.assertFalse(self.h.passed())

    def test_script_has_only_fixed_token_command_and_no_deployment_interfaces(self):
        import ast
        source = Path(acceptance.__file__).read_text()
        tree = ast.parse(source)
        commands = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"]
        self.assertEqual(len(commands), 1)
        self.assertEqual(ast.literal_eval(commands[0].args[0]), ["gcloud", "auth", "print-access-token"])
        for forbidden in ("terraform apply", "-chdir=", "hh-preview-db-app-password", "hh-preview-db-provisioner-password",
                          "hh-preview-openai-api-key", "preview-pr/", "DATABASE_URL", "local-exec"):
            self.assertNotIn(forbidden, source)

    def test_sanitized_summary_never_contains_credentials_or_payloads(self):
        self.h.report["checks"]["Identity"] = {"result": "PASS", "evidence": "Exact deployer verified"}
        summary = Path(self.directory.name) / "summary"
        with patch.dict(acceptance.os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            self.h.summary()
        text = summary.read_text()
        for forbidden in ("fake-token", "Bearer", "aWFtLWFjY2VwdGFuY2UtY2FuYXJ5", "credential.json"):
            self.assertNotIn(forbidden, text)


class IapReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "report.json"
        self.h = acceptance.Harness("37656163801-1", "fake-token", self.path)
        self.h.iap_url = f"https://iap.googleapis.com/v1/projects/{acceptance.NUMBER}/iap_web/cloud_run-us-east1/services/{self.h.service_name}"
        self.original = {"version": 3, "etag": "0", "bindings": [
            {"role": acceptance.TESTER_ROLE, "members": ["user:original@example.com"],
             "condition": {"title": "private-original-marker", "description": "keep-condition",
                           "expression": 'request.time < timestamp("2000-01-01T00:00:00Z")'}}]}
        self.current = copy.deepcopy(self.original)
        self.h.report["canaries"]["service"] = {
            "name": self.h.service, "attempted": True, "creation_complete": True}
        self.writes = 0
        self.calls = []
        self.deleted = False
        self.get_fail_after = None
        self.write_fail_at = None
        self.conflict_once = False
        self.delete_fail = False

    def api(self, url, method="GET", body=None, headers=None):
        self.calls.append((url, method, copy.deepcopy(body)))
        if "iap.googleapis.com" in url:
            if method == "GET":
                self.assertIn("options.requestedPolicyVersion=3", url)
                if self.get_fail_after == self.writes:
                    self.get_fail_after = None
                    raise acceptance.CheckError("Injected post-write read failure")
                return copy.deepcopy(self.current)
            journal = json.loads(self.path.read_text())["iap_reconciliation"]
            self.assertEqual(journal["state"], "ambiguous")
            self.assertEqual(journal["original"]["bindings"], self.original["bindings"])
            if self.conflict_once:
                self.conflict_once = False
                self.current["etag"] = "fresh-conflict-etag"
                raise acceptance.ApiError(409, "UNKNOWN")
            self.assertEqual(body["policy"]["etag"], self.current["etag"])
            self.writes += 1
            if self.write_fail_at == self.writes:
                raise acceptance.CheckError("Injected lost final-write response")
            self.current = copy.deepcopy(body["policy"])
            self.current["etag"] = str(self.writes)
            return copy.deepcopy(self.current)
        self.assertEqual(url, "https://run.googleapis.com/v2/" + self.h.service)
        if method == "DELETE":
            self.assertEqual(acceptance.canonical_policy(self.current), acceptance.canonical_policy(self.original))
            self.assertEqual(json.loads(self.path.read_text())["iap_reconciliation"]["state"], "restored")
            if self.delete_fail:
                raise acceptance.ApiError(403, "PERMISSION_DENIED")
            self.deleted = True
            return {"done": True}
        if self.deleted:
            raise acceptance.ApiError(404, "NOT_FOUND")
        return {"labels": self.h.labels}

    def restart(self):
        h = acceptance.Harness(self.h.identity, "fresh-fake-token", self.path)
        h.report = json.loads(self.path.read_text())
        self.h = h

    def cleanup(self):
        with patch.object(self.h, "api", side_effect=self.api), patch.object(self.h, "poll"):
            self.h.cleanup()

    def failed_positive(self, reads=None, write=None):
        self.get_fail_after = reads
        self.write_fail_at = write
        with patch.object(self.h, "api", side_effect=self.api):
            self.h.check("IAP tester add/remove", self.h.iap_positive)
        self.assertEqual(self.h.report["checks"]["IAP tester add/remove"]["result"], "FAIL")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.restart()

    def test_failure_after_each_successful_write_reconciles_from_disk_before_delete(self):
        for writes in (1, 2, 3):
            with self.subTest(writes=writes):
                self.current = copy.deepcopy(self.original)
                self.writes = 0
                self.deleted = False
                self.h.report.pop("iap_reconciliation", None)
                self.failed_positive(reads=writes)
                self.assertEqual(self.h.report["iap_reconciliation"]["state"], "succeeded")
                self.cleanup()
                self.assertTrue(self.deleted)
                self.assertEqual(self.h.report["iap_reconciliation"]["state"], "restored")
                self.assertEqual(self.h.report["checks"]["IAP tester add/remove"]["result"], "FAIL")

    def test_final_restore_failure_remains_ambiguous_until_cleanup_proves_restore(self):
        self.failed_positive(write=4)
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "ambiguous")
        self.cleanup()
        self.assertTrue(self.deleted)
        self.assertEqual(self.h.report["cleanup"]["iap"], "PASS: original IAP policy restored")

    def test_successful_final_restore_without_verification_remains_unproven(self):
        self.failed_positive(reads=4)
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "succeeded")
        self.cleanup()
        self.assertTrue(self.deleted)
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "restored")

    def test_lost_success_response_and_crash_keep_write_intent_durable(self):
        self.h.capture_iap(self.original)
        proposed = acceptance.changed_policy(self.original, acceptance.TESTER_ROLE, acceptance.TESTER)
        def crash(url, method, body):
            self.current = copy.deepcopy(body["policy"])
            self.current["etag"] = "crash-etag"
            raise SystemExit("Simulated runner process crash")
        with patch.object(self.h, "api", side_effect=crash), self.assertRaises(SystemExit):
            self.h.write_iap(proposed, "tester_add")
        self.restart()
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "ambiguous")
        self.cleanup()
        self.assertTrue(self.deleted)

    def test_stale_etag_is_rejected_then_restore_reads_fresh_policy(self):
        self.failed_positive(reads=2)
        self.conflict_once = True
        self.calls = []
        self.cleanup()
        self.assertTrue(self.deleted)
        iap_calls = [call for call in self.calls if "iap.googleapis.com" in call[0]]
        self.assertEqual([call[1] for call in iap_calls], ["GET", "POST", "GET", "POST", "GET"])
        self.assertEqual(iap_calls[3][2]["policy"]["etag"], "fresh-conflict-etag")

    def test_cleanup_cannot_prove_restore_retains_service_and_original_failure(self):
        self.failed_positive(reads=2)
        self.get_fail_after = 3
        self.cleanup()
        self.assertFalse(self.deleted)
        self.assertIn("reconciliation required", self.h.report["cleanup"]["iap"])
        self.assertIn("retained", self.h.report["cleanup"]["service"])
        self.assertEqual(self.h.report["checks"]["IAP tester add/remove"]["result"], "FAIL")
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "succeeded")

    def test_cleanup_does_not_overwrite_unrelated_conditional_change(self):
        self.failed_positive(reads=1)
        self.current["bindings"].append({"role": acceptance.TESTER_ROLE, "members": ["user:other@example.com"],
                                        "condition": {"title": "external", "expression": "true"}})
        writes = self.writes
        self.cleanup()
        self.assertEqual(self.writes, writes)
        self.assertFalse(self.deleted)
        self.assertIn("reconciliation required", self.h.report["cleanup"]["iap"])

    def test_ownership_failure_prevents_iap_write_and_service_deletion(self):
        self.failed_positive(reads=1)
        writes = self.writes
        with patch.object(self.h, "api", return_value={"labels": {}}) as api:
            self.h.cleanup()
        self.assertEqual(api.call_count, 1)
        self.assertEqual(self.writes, writes)
        self.assertFalse(self.deleted)
        self.assertIn("reconciliation required", self.h.report["cleanup"]["iap"])

    def test_rejected_restore_requires_operator_reconciliation(self):
        self.failed_positive(reads=1)
        with patch.object(self.h, "iap_policy", return_value=self.current), patch.object(
                self.h, "api", side_effect=[{"labels": self.h.labels},
                                          acceptance.ApiError(403, "PERMISSION_DENIED")]):
            self.h.cleanup()
        self.assertFalse(self.deleted)
        self.assertIn("reconciliation required", self.h.report["cleanup"]["iap"])
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "ambiguous")

    def test_rollback_success_and_service_deletion_failure_preserve_original_failure(self):
        self.failed_positive(reads=1)
        self.delete_fail = True
        self.cleanup()
        self.assertEqual(self.h.report["iap_reconciliation"]["state"], "restored")
        self.assertTrue(self.h.report["cleanup"]["service"].startswith("FAIL"))
        self.assertEqual(self.h.report["checks"]["IAP tester add/remove"]["result"], "FAIL")

    def test_raw_original_policy_never_in_summary(self):
        self.failed_positive(reads=1)
        self.cleanup()
        summary = Path(self.directory.name) / "summary"
        with patch.dict(acceptance.os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            self.h.summary()
        text = summary.read_text()
        for private in ("original@example.com", "private-original-marker", "keep-condition", "bindings", "etag"):
            self.assertNotIn(private, text)
        self.assertIn("original IAP policy restored", text)

    def test_no_mutation_snapshot_needs_no_iap_write(self):
        self.h.capture_iap(self.original)
        # No submitted write: deletion is safe without policy restoration.
        with patch.object(self.h, "api", side_effect=[
                {"labels": self.h.labels}, {"done": True}, acceptance.ApiError(404, "NOT_FOUND")]) as api, patch.object(self.h, "poll"):
            self.h.cleanup()
        self.assertEqual(api.call_count, 3)
        self.assertEqual(self.h.report["cleanup"]["iap"], "PASS: no IAP mutation occurred")


if __name__ == "__main__":
    unittest.main()
