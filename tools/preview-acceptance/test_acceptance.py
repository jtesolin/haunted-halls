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


if __name__ == "__main__":
    unittest.main()
