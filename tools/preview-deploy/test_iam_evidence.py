"""Offline evidence contracts: preserve IAM decisions and never expose policy values."""

from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import iam_diagnostic as diagnostic
import iam_evidence
import teardown
from test_teardown import state


class EvidenceTests(unittest.TestCase):
    def make(self):
        instance = object.__new__(teardown.PreviewTeardown)
        instance.number = "66"
        return instance

    def cli(self, policy=None, code=0, stderr=b"", parent=True, raw=None):
        output = io.StringIO()
        raw = json.dumps(policy).encode() if raw is None else raw
        with patch.object(teardown.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], code, raw, stderr)), \
                redirect_stdout(output):
            try:
                self.make().verify_cloud_run_iam_absent("hh-web-pr-66-engine", parent)
                accepted = True
            except teardown.LifecycleError:
                accepted = False
        record = json.loads(output.getvalue().removeprefix("IAM verification: "))
        self.assertNotIn("private", output.getvalue())
        self.assertEqual(record["resource_type"], "cloud_run_service")
        self.assertTrue(record["resource"].endswith("/hh-web-pr-66-engine"))
        self.assertEqual(record["cli_exit_code"], code)
        self.assertIsNone(record["http_status"])
        self.assertIn(":getIamPolicy", record["endpoint"])
        return accepted, record

    def test_exact_conditions_and_acceptance_matrix(self):
        for policy, expected, accepted in (
            (None, "policy_not_object", False),
            ([], "policy_not_object", False),
            ({}, "bindings_missing", False),
            ({"etag": ""}, "etag_not_nonempty_string", False),
            ({"etag": 123}, "etag_not_nonempty_string", False),
            ({"etag": "private-etag"}, "empty_owned_role", True),
            ({"etag": "private-etag", "version": 1}, "bindings_missing", False),
            ({"version": 3, "bindings": []}, "empty_owned_role", True),
            ({"error": {"message": "private-error"}}, "bindings_missing", False),
            ({"bindings": None}, "bindings_not_list", False),
            ({"bindings": [None]}, "binding_structure_invalid", False),
            ({"bindings": [{"role": "roles/run.invoker", "members": [123]}]},
             "owned_member_not_string", False),
            ({"bindings": [{"role": "roles/run.invoker", "members": ["private-member"],
                            "condition": {"expression": "private-expression"}}]},
             "owned_binding_conditional", False),
            ({"bindings": [{"role": "roles/run.invoker", "members": ["private-member"]}]},
             "owned_members_remain", False),
        ):
            with self.subTest(condition=expected, policy=policy):
                result, evidence = self.cli(policy)
                self.assertEqual(result, accepted)
                self.assertEqual(evidence["validation_condition"], expected)

    def test_cli_errors_and_unknown_parent_are_not_absence(self):
        for code, output, error, parent, expected, accepted in (
            (0, b"private-invalid-json", b"", True, "invalid_json", False),
            (1, b"", b"PERMISSION_DENIED private-token", True, "permission_denied", False),
            (1, b"", b"NOT_FOUND hh-web-pr-66-engine", True, "not_found_with_absent_parent", True),
            (1, b"", b"NOT_FOUND hh-web-pr-66-engine", False, "cli_read_failed", False),
            (1, b"", b"NOT_FOUND hh-web-pr-66-engine 403 private", True, "permission_denied", False),
            (1, b"", b"NOT_FOUND hh-web-pr-66-engine 401 private", True, "permission_denied", False),
            (1, b"", b"NOT_FOUND hh-web-pr-67-engine", True, "cli_read_failed", False),
        ):
            with self.subTest(expected=expected, parent=parent):
                result, evidence = self.cli(code=code, stderr=error, parent=parent, raw=output)
                self.assertEqual(result, accepted)
                self.assertEqual(evidence["validation_condition"], expected)
                self.assertEqual(evidence["parent_state"], "absent" if parent else "unknown")

    def test_iap_status_shape_and_failures_are_distinct(self):
        for status, body, expected, accepted in (
            (200, b'{}', "bindings_missing", False),
            (200, b'{"bindings":[]}', "empty_owned_role", True),
            (200, b'{"etag":"private","version":1}', "bindings_missing", False),
            (200, b"private-invalid-json", "invalid_json", False),
            (201, b'{"bindings":[]}', "http_read_failed", False),
            (204, b"", "http_read_failed", False),
            (401, b"private-error", "permission_denied", False),
            (403, b"private-error", "permission_denied", False),
            (404, b"private-error", "not_found_with_absent_parent", True),
            (503, b"private-error", "http_read_failed", False),
        ):
            stream = io.BytesIO(body)
            stream.status = status
            response = {"return_value": stream} if 200 <= status < 300 else {
                "side_effect": HTTPError("private-url", status, "private-error", {}, stream)
            }
            output = io.StringIO()
            with self.subTest(status=status, expected=expected), \
                    patch.object(teardown.Commands, "run", return_value=b"private-token"), \
                    patch.object(teardown.urllib.request, "urlopen", **response), redirect_stdout(output):
                try:
                    self.make().verify_iap_iam_absent(True)
                    result = True
                except teardown.LifecycleError:
                    result = False
                self.assertEqual(result, accepted)
            evidence = json.loads(output.getvalue().removeprefix("IAM verification: "))
            self.assertEqual(evidence["http_status"], status)
            self.assertEqual(evidence["validation_condition"], expected)
            self.assertTrue(evidence["resource"].endswith("/hh-web-pr-66-frontend"))
            self.assertNotIn("private", output.getvalue())

    def test_cli_transport_and_token_errors_emit_before_failure(self):
        for site, error in (
            ("cli", OSError("private")),
            ("cli", subprocess.TimeoutExpired("private", 120, output=b"private-token")),
            ("token", OSError("private")), ("iap", OSError("private")),
        ):
            output = io.StringIO()
            with self.subTest(site=site), redirect_stdout(output), \
                    patch.object(teardown.subprocess, "run", side_effect=error), \
                    patch.object(teardown.Commands, "run", **(
                        {"side_effect": teardown.LifecycleError("private")} if site == "token" else
                        {"return_value": b"private-token"})), \
                    patch.object(teardown.urllib.request, "urlopen", side_effect=URLError("private")):
                with self.assertRaises(teardown.LifecycleError):
                    if site == "cli":
                        self.make().verify_cloud_run_iam_absent("hh-web-pr-66-engine", True)
                    else:
                        self.make().verify_iap_iam_absent(True)
            self.assertNotIn("private", output.getvalue())
            self.assertIn({"cli": "cli_transport_unavailable", "token": "token_unavailable",
                           "iap": "transport_unavailable"}[site], output.getvalue())

    def test_unknown_policy_keys_and_binding_values_never_escape(self):
        policy = {"bindings": [{"role": "private-role", "members": ["private-member"]}],
                  "etag": "private-etag", "version": "private-version", "private-key": "private"}
        text = json.dumps(iam_evidence.record(
            "cloud_run_service", "fixed-resource", "GET", "fixed-endpoint", "unknown", policy))
        self.assertNotIn("private", text)
        self.assertEqual(iam_evidence.shape(policy)["fields"]["other_field_count"], 1)

    def test_api_classification_separates_missing_permission_and_transport(self):
        for status, parent, expected in (
            (404, True, "not_found_with_absent_parent"),
            (404, False, "parent_absence_unverified"),
            (403, True, "permission_denied"), (401, True, "permission_denied"),
            (503, True, "http_read_failed"), (302, True, "http_read_failed"),
            (None, True, "transport_unavailable"),
        ):
            with self.subTest(status=status, parent=parent):
                self.assertEqual(diagnostic.api_condition(
                    status, None, None, parent, "roles/run.invoker"), expected)

    def test_each_policy_rejection_blocks_database_and_later_cleanup(self):
        cases = [(failed, 200, None, "bindings_missing")
                 for failed in ("engine", "frontend", "iap")]
        cases += [("iap", status, None, "http_read_failed") for status in (201, 202, 204, 206)]
        cases += [(failed, 200, marker, "permission_denied")
                  for failed in ("engine", "frontend")
                  for marker in (b"401", b"403", b"PERMISSION_DENIED", b"permission denied",
                                 b"UNAUTHENTICATED")]
        for failed, status, marker, expected in cases:
            instance = teardown.PreviewTeardown({"number": "56"}, Mock())
            output = io.StringIO()

            def cli(args, **kwargs):
                bad = args[4].endswith("-" + failed)
                if bad and marker:
                    return subprocess.CompletedProcess(
                        args, 1, b"NOT_FOUND " + args[4].encode(),
                        marker + b" private-token")
                return subprocess.CompletedProcess(
                    args, 0, json.dumps({} if bad and status == 200 else
                                        {"etag": "private-etag"}).encode(), b"")

            response = io.BytesIO(b"" if status == 204 else b'{"bindings":[]}' if status != 200 else b"{}")
            response.status = status
            with self.subTest(failed=failed, status=status, marker=marker), redirect_stdout(output), \
                    patch.object(instance, "revalidate"), patch.object(instance, "check_secret_workflow"), \
                    patch.object(instance, "initialize"), patch.object(instance, "read_state", return_value=state()), \
                    patch.object(instance, "destroy") as destroy, \
                    patch.object(instance, "verify_runtime_absent", return_value={
                        "hh-web-pr-56-engine", "hh-web-pr-56-frontend"}), \
                    patch.object(teardown.subprocess, "run", side_effect=cli), \
                    patch.object(teardown.Commands, "run", return_value=b"private-token"), \
                    patch.object(teardown.urllib.request, "urlopen", return_value=response), \
                    patch.object(teardown, "request_database") as database, \
                    patch.object(instance, "cleanup_tags") as tags:
                with self.assertRaises(teardown.LifecycleError):
                    instance.run()
                database.assert_not_called()
                tags.assert_not_called()
                destroy.assert_called_once_with(runtime_only=True)
            records = [json.loads(line.removeprefix("IAM verification: "))
                       for line in output.getvalue().splitlines()]
            self.assertEqual(records[-1]["validation_condition"], expected)
            suffix = "frontend" if failed == "iap" else failed
            self.assertTrue(records[-1]["resource"].endswith("-" + suffix))
            self.assertEqual(records[-1]["resource_type"],
                             "iap_web_service" if failed == "iap" else "cloud_run_service")
            self.assertNotIn("private", output.getvalue())


class LocalDiagnosticTests(unittest.TestCase):
    def tearDown(self):
        diagnostic.configure_targets("76")
        diagnostic.IMPERSONATE = False

    def test_cli_mixed_denials_and_transport_failures_are_distinct(self):
        diagnostic.configure_targets("66")

        def read(url, method, token):
            return (200, {"etag": "private-etag"}, None) if url.endswith(
                diagnostic.RUN_POLICY_SUFFIX) else (404, None, None)

        cases = [(marker, "permission_denied") for marker in (
            b"401", b"403", b"PERMISSION_DENIED", b"permission denied", b"UNAUTHENTICATED")]
        cases += [(subprocess.TimeoutExpired("private-command", 60, output=b"private-token",
                                            stderr=b"private-error"), "cli_transport_unavailable"),
                  (OSError("private-token"), "cli_transport_unavailable"),
                  (b"NOT_FOUND_OTHER", "cli_read_failed")]
        for failure, expected in cases:
            with self.subTest(failure=type(failure).__name__, expected=expected):
                def cli(args, **kwargs):
                    if isinstance(failure, Exception):
                        raise failure
                    return subprocess.CompletedProcess(
                        args, 1, b"NOT_FOUND hh-web-pr-67-engine" if failure == b"NOT_FOUND_OTHER"
                        else b"NOT_FOUND " + args[4].encode(), failure + b" private-token")

                with patch.object(diagnostic, "read_policy", side_effect=read), \
                        patch.object(diagnostic.subprocess, "run", side_effect=cli):
                    records = diagnostic.diagnose("private-token")
                for entry in records[:2]:
                    self.assertEqual(entry["cli_validation_condition"], expected)
                    self.assertEqual(entry["cli_verifier"], "INCONCLUSIVE")
                    self.assertEqual(entry["result"], "INCONCLUSIVE")
                    self.assertEqual(entry["cli_exit_code"],
                                     -1 if isinstance(failure, Exception) else 1)
                self.assertNotIn("private", json.dumps(records))

    def pr(self, **changes):
        return {"number": 66, "state": "closed", "closed_at": "2026-10-16T00:00:00Z",
                "base": {"ref": "main", "repo": {"full_name": "jtesolin/haunted-halls"}}, **changes}

    def test_canonical_bounded_numbers(self):
        for value in ("0", "066", "66/../76", "66;echo", " 66", "1000000000", "", None, 66):
            with self.subTest(value=value), self.assertRaises(teardown.LifecycleError):
                diagnostic.configure_targets(value)
        diagnostic.configure_targets("66")
        self.assertEqual(diagnostic.SERVICES, ("hh-web-pr-66-engine", "hh-web-pr-66-frontend"))
        self.assertIn("hh-web-pr-66-frontend:", diagnostic.IAP_URL)

    def test_closed_pr_metadata_required_and_read_only(self):
        for pr, accepted in ((self.pr(), True), (self.pr(state="open"), False),
                             (self.pr(number=76), False), (self.pr(closed_at=None), False),
                             (self.pr(base={"ref": "other"}), False), ([], False)):
            response = io.BytesIO(json.dumps(pr).encode())
            response.status = 200
            opener = Mock()
            opener.open.return_value = response
            with self.subTest(pr=pr), patch.object(diagnostic.urllib.request, "build_opener",
                                                 return_value=opener):
                if accepted:
                    diagnostic.validate_closed_pr("66")
                else:
                    with self.assertRaises(teardown.LifecycleError):
                        diagnostic.validate_closed_pr("66")
                request = opener.open.call_args.args[0]
                self.assertEqual(request.full_url,
                                 "https://api.github.com/repos/jtesolin/haunted-halls/pulls/66")
                self.assertEqual(request.get_method(), "GET")
                self.assertFalse(request.has_header("Authorization"))

    def test_local_closed_pr_gate_precedes_auth_and_queries(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["iam_diagnostic.py", "--local", "--pull-request-number", "66"]), \
                patch.dict(os.environ, {"GITHUB_ACTIONS": ""}), \
                patch.object(diagnostic, "validate_closed_pr", side_effect=teardown.LifecycleError("Closed PR required")), \
                patch.object(diagnostic.subprocess, "run") as command, \
                patch.object(diagnostic, "diagnose") as diagnose, redirect_stdout(output):
            self.assertEqual(diagnostic.main(), 1)
        command.assert_not_called()
        diagnose.assert_not_called()

    def test_closed_pr_metadata_errors_fail_without_leaking(self):
        for error in (HTTPError("private-url", 403, "private-error", {}, io.BytesIO()),
                      URLError("private-error"), TimeoutError("private-error")):
            opener = Mock()
            opener.open.side_effect = error
            with self.subTest(error=type(error).__name__), \
                    patch.object(diagnostic.urllib.request, "build_opener", return_value=opener), \
                    self.assertRaises(teardown.LifecycleError) as failure:
                diagnostic.validate_closed_pr("66")
            self.assertNotIn("private", str(failure.exception))

    def test_impersonation_cli_uses_only_fixed_deployer_and_target(self):
        diagnostic.configure_targets("66")
        diagnostic.IMPERSONATE = True
        with patch.object(diagnostic.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, b'{"etag":"private-etag"}', b"")) as command:
            self.assertEqual(diagnostic.cli_policy("hh-web-pr-66-engine")[0], 0)
        self.assertIn("--impersonate-service-account=" + diagnostic.DEPLOYER, command.call_args.args[0])
        self.assertEqual(command.call_args.args[0][4], "hh-web-pr-66-engine")

    def test_impersonation_denied_stops_without_policy_queries_or_leaks(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["iam_diagnostic.py", "--local", "--pull-request-number", "66",
                                       "--impersonate-deployer"]), \
                patch.dict(os.environ, {"GITHUB_ACTIONS": ""}), \
                patch.object(diagnostic, "validate_closed_pr"), \
                patch.object(diagnostic.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 1, b"private-token", b"PERMISSION_DENIED private-error")) as command, \
                patch.object(diagnostic, "diagnose") as diagnose, redirect_stdout(output):
            self.assertEqual(diagnostic.main(), 1)
        diagnose.assert_not_called()
        self.assertIn("--impersonate-service-account=" + diagnostic.DEPLOYER, command.call_args.args[0])
        report = json.loads(output.getvalue())
        self.assertEqual(report["condition"], "permission_denied")
        self.assertEqual(report["policies_queried"], 0)
        self.assertNotIn("private", output.getvalue())

    def test_local_mode_cannot_bypass_actions_or_accept_arbitrary_endpoints(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["iam_diagnostic.py", "--local", "--pull-request-number", "66"]), \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                patch.object(diagnostic.subprocess, "run") as command, redirect_stdout(output):
            self.assertEqual(diagnostic.main(), 1)
        command.assert_not_called()
        diagnostic.configure_targets("66")
        for method, url in (("DELETE", diagnostic.RUN_ROOT + diagnostic.SERVICES[0]),
                            ("GET", diagnostic.RUN_ROOT + "hh-web-pr-76-engine"),
                            ("GET", "https://private.invalid")):
            with self.assertRaises(teardown.LifecycleError):
                diagnostic.read_policy(url, method, "private-token")


if __name__ == "__main__":
    unittest.main()
