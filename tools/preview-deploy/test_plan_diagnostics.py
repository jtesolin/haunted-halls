import subprocess
import unittest
from unittest.mock import patch

from test_lifecycle import lifecycle


LABEL = "secret-containers Terraform plan"
TARGETS = {
    "google_secret_manager_secret.pr",
    "google_secret_manager_secret_iam_member.runtime",
}


class PlanDiagnosticTests(unittest.TestCase):
    def plan_failure(self, stderr, stdout=b""):
        result = subprocess.CompletedProcess([], 1, stdout, stderr.encode())
        with patch.object(lifecycle.subprocess, "run", return_value=result):
            with self.assertRaises(lifecycle.LifecycleError) as error:
                lifecycle.run_terraform_plan(
                    ["terraform", "-chdir=infra/terraform/preview-pr", "plan"],
                    label=LABEL,
                    targets=TARGETS,
                )
        return str(error.exception)

    def test_missing_permission_status_http_and_target_resource_are_exposed(self):
        message = self.plan_failure("""
Error: Error creating Secret: googleapi: Error 403: PERMISSION_DENIED:
Permission 'secretmanager.secrets.create' denied on resource 'private-value'

  with google_secret_manager_secret.pr["nextauth"],
  on secrets.tf line 12, in resource "google_secret_manager_secret" "pr":
""")
        self.assertEqual(
            message,
            f"{LABEL} failed: PERMISSION_DENIED; HTTP 403; secret creation error; "
            "permission secretmanager.secrets.create; resource google_secret_manager_secret.pr",
        )

    def test_google_status_codes_are_preserved(self):
        for status in ("NOT_FOUND", "FAILED_PRECONDITION", "ALREADY_EXISTS"):
            with self.subTest(status=status):
                self.assertEqual(
                    self.plan_failure(f"Error: {status}: arbitrary provider text"),
                    f"{LABEL} failed: {status}",
                )
        for code in (400, 403, 404, 409, 500):
            with self.subTest(code=code):
                self.assertEqual(
                    self.plan_failure(f"Error: googleapi: Error {code}: private detail"),
                    f"{LABEL} failed: HTTP {code}",
                )

    def test_resource_instances_and_non_target_addresses_are_not_echoed(self):
        self.assertEqual(
            self.plan_failure("""
  with google_secret_manager_secret_iam_member.runtime["opaque-credential"],
  with google_secret_manager_secret.foreign,
"""),
            f"{LABEL} failed: resource google_secret_manager_secret_iam_member.runtime",
        )

    def test_secrets_paths_headers_url_userinfo_and_quoted_values_are_not_emitted(self):
        private = [
            "Authorization: Bearer super-private-access-token",
            "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzZWNyZXQifQ.signature",
            "/home/runner/work/gha-creds-private.json",
            "https://database-user:database-password@example.com/database",
            "postgresql://user:password@example.com/db",
            "a" * 120,
            '"unrecognized quoted value"',
            "'secretmanager.secrets.privateTokenValue'",
        ]
        message = self.plan_failure(
            "Error: PERMISSION_DENIED: " + " ".join(private)
            + "\nPermission 'secretmanager.secrets.getIamPolicy' denied\n"
            + "\n".join(private)
        )
        self.assertEqual(
            message,
            f"{LABEL} failed: PERMISSION_DENIED; permission secretmanager.secrets.getIamPolicy",
        )
        for value in private:
            self.assertNotIn(value, message)

    def test_arbitrary_provider_response_body_and_non_diagnostic_output_are_not_emitted(self):
        self.assertEqual(
            self.plan_failure("""
Error: unexpected provider response: {"payload":"private-response"}
{"code":403,"status":"PERMISSION_DENIED","message":"secretmanager.secrets.create"}
Authorization: Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
credentials: /tmp/private.json
"""),
            f"{LABEL} failed.",
        )

    def test_provider_configuration_headline_is_categorized_not_echoed(self):
        self.assertEqual(
            self.plan_failure('Error: Invalid provider configuration: "credential-file-path"'),
            f"{LABEL} failed: provider configuration error",
        )

    def test_unknown_or_invalid_utf8_failure_uses_generic_message(self):
        self.assertEqual(self.plan_failure("Unexpected failure: sensitive prose"), f"{LABEL} failed.")
        self.assertEqual(
            lifecycle.terraform_plan_diagnostic(b"\xffprivate-output", TARGETS), "",
        )

    def test_diagnostic_stdout_is_supported_and_duplicate_fields_are_compact(self):
        self.assertEqual(
            self.plan_failure("Error: PERMISSION_DENIED", b"Error: PERMISSION_DENIED\n"),
            f"{LABEL} failed: PERMISSION_DENIED",
        )

    def test_success_keeps_exact_command_capture_timeout_and_output(self):
        arguments = [
            "terraform", "-chdir=infra/terraform/preview-pr", "plan",
            "-input=false", "-no-color", "-out=/tmp/preview-41-secret-containers.tfplan",
            "-target=google_secret_manager_secret.pr", "-var=private-value",
        ]
        stdout = b"unchanged stdout"
        result = subprocess.CompletedProcess(arguments, 0, stdout, b"private stderr")
        with patch.object(lifecycle.subprocess, "run", return_value=result) as run:
            self.assertEqual(
                lifecycle.run_terraform_plan(arguments, label=LABEL, targets=TARGETS), stdout,
            )
        run.assert_called_once_with(
            arguments, input=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=900,
        )

    def test_timeout_and_spawn_errors_never_include_sensitive_details(self):
        for error in (
            OSError("private credential path"),
            subprocess.TimeoutExpired(["private-argument"], 900, b"private-output"),
        ):
            with self.subTest(error=type(error).__name__), patch.object(
                lifecycle.subprocess, "run", side_effect=error,
            ):
                with self.assertRaisesRegex(
                    lifecycle.LifecycleError, f"^{LABEL} could not be completed\\.$",
                ):
                    lifecycle.run_terraform_plan([], label=LABEL, targets=TARGETS)

    def test_other_cloud_commands_remain_opaque(self):
        result = subprocess.CompletedProcess([], 1, b"private", b"Error: PERMISSION_DENIED")
        with patch.object(lifecycle.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "^Cloud read failed\\.$"):
                lifecycle.Commands.run(["gcloud", "private-arguments"], label="Cloud read")


if __name__ == "__main__":
    unittest.main()
