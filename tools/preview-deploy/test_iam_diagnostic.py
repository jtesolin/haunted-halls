"""Offline isolation and evidence contracts for the temporary PR 76 diagnostic."""

import ast
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import iam_diagnostic as diagnostic


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/preview-deploy.yml").read_text()
JOB = WORKFLOW.split("\n  iam-diagnostic:\n", 1)[1].split("\n  deploy:\n", 1)[0]
ENV = {
    "GITHUB_WORKFLOW_REF": diagnostic.WORKFLOW,
    "GITHUB_REPOSITORY": "jtesolin/haunted-halls", "GITHUB_REF": "refs/heads/main",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
}
EVENT = {
    "repository": {"full_name": "jtesolin/haunted-halls"},
    "inputs": {"operation": "iam-diagnostic", "pull_request_number": "76"},
}


def selected(job, event="workflow_dispatch", operation="iam-diagnostic", number="76",
             ref="refs/heads/main", repository="jtesolin/haunted-halls"):
    condition = re.split(
        r"\n    [a-z-]+:", job.split("    if: >-\n", 1)[1], maxsplit=1,
    )[0]
    for symbol, value in {
        "github.event_name": event, "inputs.operation": operation,
        "inputs.pull_request_number": number, "github.ref": ref,
        "github.repository": repository,
    }.items():
        condition = condition.replace(symbol, repr(value))
    condition = " ".join(condition.split()).replace("&&", " and ").replace("||", " or ")
    # Evaluate only a fixed repository boolean expression, not user/source commands.
    tree = ast.parse(condition, mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq, ast.Constant)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError("Unexpected workflow condition syntax")
    return eval(compile(tree, "<workflow-condition>", "eval"), {"__builtins__": {}})


class ContextTests(unittest.TestCase):
    def check(self, event=EVENT, env=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(json.dumps(event))
            with patch.dict(os.environ, {**ENV, "GITHUB_EVENT_PATH": str(path), **(env or {})}):
                diagnostic.check_context()

    def test_exact_context_and_request(self):
        self.check()
        for key, value in (
            ("GITHUB_WORKFLOW_REF", diagnostic.WORKFLOW.replace("preview-deploy", "other")),
            ("GITHUB_WORKFLOW_REF", diagnostic.WORKFLOW.replace("main", "topic")),
            ("GITHUB_REPOSITORY", "other/haunted-halls"),
            ("GITHUB_REF", "refs/heads/topic"),
            ("GITHUB_EVENT_NAME", "pull_request_target"),
            ("GITHUB_EVENT_NAME", "workflow_run"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(diagnostic.LifecycleError):
                self.check(env={key: value})

    def test_only_explicit_operation_and_exact_pr76(self):
        for operation, number in (
            ("acceptance", "76"), ("teardown", "76"), ("", "76"),
            ("iam-diagnostic", "66"), ("iam-diagnostic", "77"),
            ("iam-diagnostic", "0"), ("iam-diagnostic", "076"),
            ("iam-diagnostic", 76), ("iam-diagnostic", ""),
        ):
            event = copy.deepcopy(EVENT)
            event["inputs"] = {"operation": operation, "pull_request_number": number}
            with self.subTest(inputs=event["inputs"]), self.assertRaises(diagnostic.LifecycleError):
                self.check(event)
        for event in (None, [], {}, {"inputs": None}, {**EVENT, "repository": None}):
            with self.subTest(event=event), self.assertRaises(diagnostic.LifecycleError):
                self.check(event)

    def test_invalid_or_missing_event_cannot_authenticate(self):
        with patch.dict(os.environ, {**ENV, "GITHUB_EVENT_PATH": "/missing/event"}), \
             patch.object(sys, "argv", ["iam_diagnostic.py"]), \
             patch.object(diagnostic.subprocess, "run") as process, redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostic.main(), 1)
        process.assert_not_called()

    def test_check_context_mode_has_no_external_calls(self):
        with patch.object(diagnostic, "check_context", return_value="76"), \
             patch.object(diagnostic, "validate_closed_pr"), \
             patch.object(sys, "argv", ["iam_diagnostic.py", "--check-context"]), \
             patch.object(diagnostic.subprocess, "run") as process:
            self.assertEqual(diagnostic.main(), 0)
        process.assert_not_called()


class ReadTests(unittest.TestCase):
    def test_network_allowlist_blocks_mutations_arbitrary_targets_and_redirects(self):
        for url, method in (
            (diagnostic.RUN_ROOT + diagnostic.SERVICES[0], "DELETE"),
            (diagnostic.RUN_ROOT + diagnostic.SERVICES[0] + ":setIamPolicy", "POST"),
            (diagnostic.IAP_URL, "GET"), ("https://attacker.invalid/", "GET"),
            (diagnostic.RUN_ROOT + "hh-web-pr-77-engine:getIamPolicy", "GET"),
        ):
            with self.subTest(url=url, method=method), \
                 patch.object(diagnostic.urllib.request, "build_opener") as opener, \
                 self.assertRaises(diagnostic.LifecycleError):
                diagnostic.read_policy(url, method, "private-token")
            opener.assert_not_called()
        self.assertIsNone(diagnostic.NoRedirect().redirect_request(None, None, 302, "", {}, ""))

    def test_read_only_request_shapes(self):
        for url, method in (
            (diagnostic.RUN_ROOT + diagnostic.SERVICES[0], "GET"),
            (diagnostic.RUN_ROOT + diagnostic.SERVICES[1] + diagnostic.RUN_POLICY_SUFFIX, "GET"),
            (diagnostic.IAP_URL, "POST"),
        ):
            response = Mock(status=200, read=Mock(return_value=b'{"etag":"private-etag"}'))
            opener = Mock()
            opener.open.return_value.__enter__ = Mock(return_value=response)
            opener.open.return_value.__exit__ = Mock(return_value=False)
            with patch.object(diagnostic.urllib.request, "build_opener", return_value=opener):
                status, policy, error = diagnostic.read_policy(url, method, "private-token")
            self.assertEqual((status, policy, error), (200, {"etag": "private-etag"}, None))
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, url)
            self.assertEqual(request.get_method(), method)
            self.assertEqual(request.data, b'{"options":{"requestedPolicyVersion":3}}'
                             if method == "POST" else None)

    def test_http_and_transport_failures_are_explicit_and_sanitized(self):
        for error in (
            HTTPError(diagnostic.IAP_URL, 403, "private-token", {}, io.BytesIO(b'{"error":"private-data"}')),
            URLError("private-token"),
            TimeoutError("private-token"),
        ):
            opener = Mock()
            opener.open.side_effect = error
            with patch.object(diagnostic.urllib.request, "build_opener", return_value=opener):
                status, policy, failure = diagnostic.read_policy(diagnostic.IAP_URL, "POST", "token")
            if isinstance(error, HTTPError):
                self.assertEqual(status, 403)
            else:
                self.assertIsNone(status)
                self.assertIn("unavailable", failure)
            self.assertNotIn("private", json.dumps(diagnostic.shape(policy)))

    def test_cli_is_exact_teardown_read_and_diagnostics_are_not_logged(self):
        with patch.object(diagnostic.subprocess, "run") as process, \
             self.assertRaises(diagnostic.LifecycleError):
            diagnostic.cli_policy("hh-web-pr-77-engine")
        process.assert_not_called()
        for code, output, error, missing in (
            (0, b'{"etag":"private-etag"}', b"", False),
            (1, b"", b"NOT_FOUND hh-web-pr-76-engine", True),
            (1, b"", b"NOT_FOUND hh-web-pr-77-engine", False),
            (1, b"", b"NOT_FOUND hh-web-pr-76-engine PERMISSION_DENIED private-token", False),
            (0, b"private-token", b"", False),
        ):
            with patch.object(diagnostic.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], code, output, error,
            )) as process:
                result = diagnostic.cli_policy("hh-web-pr-76-engine")
            self.assertEqual(result[2], missing)
            self.assertEqual(process.call_args.args[0], [
                "gcloud", "run", "services", "get-iam-policy", "hh-web-pr-76-engine",
                "--project=hh-preview-458395246135", "--region=us-east1", "--format=json",
            ])
            self.assertNotIn("private-token", str(result))
        with patch.object(diagnostic.subprocess, "run", side_effect=subprocess.TimeoutExpired(
            "private-command", 60, output=b"private-token",
        )):
            self.assertEqual(diagnostic.cli_policy("hh-web-pr-76-engine"),
                             (-1, None, False, "Cloud Run CLI policy read unavailable."))

    def test_verifier_cases_and_exact_failure_conditions(self):
        for policy in ({"bindings": []}, {"etag": "private-etag"}):
            self.assertEqual(diagnostic.validate(200, policy, None, True, "roles/run.invoker")[0], "PASS")
        for policy, condition in (
            (None, "policy must be an object"),
            ({}, "bindings must be a list"),
            ({"etag": "etag", "version": 1}, "bindings must be a list"),
            ({"bindings": [{"role": "roles/run.invoker", "members": "bad"}]}, "binding/member structure"),
        ):
            result, reason = diagnostic.validate(200, policy, None, True, "roles/run.invoker")
            self.assertEqual(result, "FAIL")
            self.assertIn(condition, reason)
        for status in (None, 201, 202, 204, 206, 401, 403, 429, 500, 503):
            self.assertEqual(diagnostic.validate(status, {}, None, True, "roles/run.invoker")[0],
                             "INCONCLUSIVE")
        self.assertEqual(diagnostic.validate(404, {}, None, False, "roles/run.invoker")[0],
                         "INCONCLUSIVE")
        self.assertEqual(diagnostic.validate(404, {}, None, True, "roles/run.invoker")[0], "PASS")
        self.assertEqual(diagnostic.validate(200, None, "invalid JSON", True, "roles/run.invoker"),
                         ("FAIL", "invalid JSON"))
        self.assertEqual(diagnostic.validate(200, {"bindings": [
            {"role": "roles/run.invoker", "members": ["private-member"]},
        ]}, None, True, "roles/run.invoker")[0], "FAIL")

    def test_missing_bindings_wording_matches_role_and_verified_parent_context(self):
        generic = "bindings must be a list or policy must contain only a nonempty string etag"
        iap = "bindings must be a list, an etag-only policy, or valid metadata for verified-absent IAP"
        for role, parent_absent, expected in (
            ("roles/run.invoker", True, generic),
            ("roles/run.invoker", False, generic),
            ("roles/run.invoker", None, generic),
            ("roles/iap.httpsResourceAccessor", True, iap),
            ("roles/iap.httpsResourceAccessor", False, generic),
            ("roles/iap.httpsResourceAccessor", None, generic),
            ("roles/iap.httpsResourceAccessor", 1, generic),
        ):
            for policy in ({}, {"etag": "private-etag", "version": "private-version"},
                           {"bindings": None}, {"bindings": "private-bindings"}):
                with self.subTest(role=role, parent=parent_absent, policy=policy):
                    result, reason = diagnostic.validate(200, policy, None, parent_absent, role)
                    self.assertEqual(result, "FAIL")
                    self.assertEqual(reason,
                                     "Resource IAM policy is malformed or unavailable. "
                                     f"Condition: {expected}.")
                    self.assertNotIn("private", reason)

    def test_shape_never_contains_policy_values_or_unexpected_field_names(self):
        policy = {"bindings": [{"members": ["private-member"], "role": "private-role",
                                "condition": {"expression": "private-expression"}}],
                  "etag": "private-etag", "version": "private-version",
                  "private-field": "private-value"}
        text = json.dumps(diagnostic.shape(policy))
        self.assertNotIn("private", text)
        self.assertEqual(diagnostic.shape(policy)["fields"]["bindings"],
                         {"present": True, "type": "list", "count": 1})
        self.assertEqual(diagnostic.shape(policy)["fields"]["other_field_count"], 1)

    def run_diagnostic(self, cli_policy=None, api_policy=None, parent=404, iap_status=404):
        calls = []

        def read(url, method, token):
            calls.append((url, method))
            if url == diagnostic.IAP_URL:
                return iap_status, {"error": "private-error"}, None
            if url.endswith(diagnostic.RUN_POLICY_SUFFIX):
                return 200, api_policy if api_policy is not None else {"etag": "private-etag"}, None
            return parent, {}, None

        with patch.object(diagnostic, "read_policy", side_effect=read), \
             patch.object(diagnostic, "cli_policy",
                          return_value=(0, cli_policy if cli_policy is not None else
                                        {"etag": "private-etag"}, False, None)):
            records = diagnostic.diagnose("private-token")
        self.assertEqual(len(calls), 5)
        self.assertEqual({method for _, method in calls}, {"GET", "POST"})
        return records

    def test_observed_empty_policies_and_iap_absence_pass(self):
        records = self.run_diagnostic()
        self.assertEqual([r["result"] for r in records], ["PASS"] * 3)
        self.assertNotIn("private", json.dumps(records))

    def test_cli_api_disagreement_and_present_parent_cannot_pass(self):
        self.assertEqual(self.run_diagnostic(cli_policy={})[0]["result"], "FAIL")
        self.assertEqual(self.run_diagnostic(api_policy={})[0]["result"], "FAIL")
        self.assertEqual(self.run_diagnostic(parent=200)[0]["result"], "INCONCLUSIVE")
        self.assertEqual(self.run_diagnostic(iap_status=503)[2]["result"], "INCONCLUSIVE")

    def test_main_outputs_only_sanitized_report_and_no_cleanup(self):
        for failed in (False, True):
            records = self.run_diagnostic(cli_policy={} if failed else None)
            with tempfile.TemporaryDirectory() as directory:
                summary = Path(directory) / "summary"
                output = io.StringIO()
                with patch.object(diagnostic, "check_context", return_value="76"), \
                     patch.object(diagnostic, "validate_closed_pr"), \
                     patch.object(sys, "argv", ["iam_diagnostic.py"]), \
                     patch.object(diagnostic.subprocess, "run", return_value=subprocess.CompletedProcess(
                         [], 0, b"private-token", b"private-stderr",
                     )) as process, \
                     patch.object(diagnostic, "diagnose", return_value=records), \
                     patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}), \
                     redirect_stdout(output):
                    self.assertEqual(diagnostic.main(), 1 if failed else 0)
                process.assert_called_once_with(["gcloud", "auth", "print-access-token"],
                                                capture_output=True, timeout=60, check=False)
                self.assertNotIn("private", output.getvalue() + summary.read_text())
                report = json.loads(output.getvalue())
                self.assertEqual(report["iam_checks_allow_continuation"], not failed)
                self.assertEqual(report["existing_teardown_policy_checks_pass"], not failed)

    def test_token_and_timeout_failure_never_emit_stderr_or_token(self):
        for outcome in (
            subprocess.CompletedProcess([], 1, b"private-token", b"private-error"),
            subprocess.TimeoutExpired("private-command", 60, output=b"private-token"),
        ):
            output = io.StringIO()
            with patch.object(diagnostic, "check_context"), \
                 patch.object(sys, "argv", ["iam_diagnostic.py"]), \
                 patch.object(diagnostic.subprocess, "run",
                              **({"side_effect": outcome} if isinstance(outcome, Exception)
                                 else {"return_value": outcome})), \
                 patch.object(diagnostic, "diagnose") as diagnose, redirect_stdout(output):
                self.assertEqual(diagnostic.main(), 1)
            diagnose.assert_not_called()
            self.assertNotIn("private", output.getvalue())
            self.assertIn("INCONCLUSIVE", output.getvalue())


class WorkflowIsolationTests(unittest.TestCase):
    def test_diagnostic_selects_only_manual_exact_request(self):
        self.assertTrue(selected(JOB))
        for changes in (
            {"event": "pull_request_target"}, {"event": "workflow_run"},
            {"operation": "teardown"}, {"operation": "acceptance"}, {"operation": ""},
            {"number": "77"}, {"number": ""}, {"number": "076"},
            {"ref": "refs/heads/topic"}, {"repository": "fork/haunted-halls"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(selected(JOB, **changes))

    def test_acceptance_cannot_run_canaries_during_diagnostic(self):
        job = WORKFLOW.split("\n  acceptance:\n", 1)[1].split("\n  iam-diagnostic:\n", 1)[0]
        self.assertFalse(selected(job))
        self.assertFalse(selected(job, operation="teardown"))
        self.assertFalse(selected(job, operation=""))
        self.assertTrue(selected(job, operation="acceptance"))

    def test_diagnostic_does_not_select_deploy_or_teardown(self):
        deploy = WORKFLOW.split("\n  deploy:\n", 1)[1].split("\n  teardown:\n", 1)[0]
        teardown = WORKFLOW.split("\n  teardown:\n", 1)[1]
        self.assertFalse(selected(deploy))
        self.assertFalse(selected(teardown))
        self.assertTrue(selected(deploy, operation="deploy"))
        self.assertTrue(selected(teardown, operation="teardown"))
        for event in ("workflow_run", "pull_request"):
            self.assertFalse(selected(deploy, event=event, operation="deploy"))
        self.assertTrue(selected(teardown, event="pull_request_target", operation=""))

    def test_job_has_only_read_only_helper_and_existing_auth(self):
        self.assertIn("group: frontend-preview-pr-76", JOB)
        self.assertIn("contents: read\n      id-token: write", JOB)
        self.assertNotIn("actions: write", JOB)
        self.assertNotIn("issues:", JOB)
        self.assertNotIn("pull-requests:", JOB)
        self.assertIn("service_account: ${{ env.DEPLOY_SERVICE_ACCOUNT }}", JOB)
        self.assertIn("workload_identity_provider: ${{ env.WIF_PROVIDER }}", JOB)
        self.assertIn("ref: ${{ github.sha }}", JOB)
        self.assertIn("persist-credentials: false", JOB)
        self.assertIn(f'test "$GITHUB_WORKFLOW_REF" = "{diagnostic.WORKFLOW}"', JOB)
        self.assertLess(JOB.index("iam_diagnostic.py --check-context"),
                        JOB.index("uses: google-github-actions/auth"))
        commands = re.findall(r"^        run: (.+)$", JOB, re.M)
        self.assertEqual(commands, [
            '|', 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
            "python tools/preview-deploy/iam_diagnostic.py --check-context",
            "python tools/preview-deploy/iam_diagnostic.py",
        ])
        self.assertEqual(re.findall(r"uses: ([^\n]+)", JOB), [
            "actions/checkout@v7", "actions/setup-python@v6",
            "google-github-actions/setup-gcloud@v3", "google-github-actions/auth@v3",
        ])

    def test_helper_has_no_cleanup_call_graph_or_arbitrary_subprocess(self):
        source = Path(diagnostic.__file__).read_text()
        tree = ast.parse(source)
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual([(n.module, [a.name for a in n.names]) for n in imports], [
            ("pathlib", ["Path"]), ("teardown", ["LifecycleError", "PreviewTeardown"]),
            ("iam_evidence", ["cli_error_kind", "condition", "record", "shape"]),
        ])
        references = [n.attr for n in ast.walk(tree)
                      if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                      and n.value.id == "PreviewTeardown"]
        self.assertEqual(references, ["policy_members"])
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                             and n.func.id == "PreviewTeardown" for n in ast.walk(tree)))
        process_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                         and ast.unparse(n.func) == "subprocess.run"]
        self.assertEqual(len(process_calls), 2)
        for call in process_calls:
            self.assertIsInstance(call.args[0], ast.List)
            self.assertFalse(any(k.arg == "shell" for k in call.keywords))
        self.assertEqual([
            [ast.literal_eval(n) for n in call.args[0].elts if isinstance(n, ast.Constant)][:4]
            for call in process_calls
        ], [
            ["gcloud", "run", "services", "get-iam-policy"],
            ["gcloud", "auth", "print-access-token"],
        ])
        self.assertNotIn("os.system", source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("exec(", source)

    def test_existing_wif_claim_mapping_authorizes_same_caller_not_a_new_workflow(self):
        source = (ROOT / "infra/terraform/preview-foundation/workload-identity.tf").read_text()
        self.assertIn('"attribute.workflow_ref"     = "assertion.workflow_ref"', source)
        self.assertIn('attribute.workflow_ref in [', source)
        self.assertIn('attribute.workflow_ref/${local.frontend_workflow_ref}', source)
        self.assertIn(diagnostic.WORKFLOW, source)
        self.assertIn('role               = "roles/iam.workloadIdentityUser"', source)
        self.assertNotIn("job_workflow_ref", source)


if __name__ == "__main__":
    unittest.main()
