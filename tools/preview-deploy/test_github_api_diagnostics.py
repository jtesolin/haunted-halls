import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from test_lifecycle import (
    PREVIEW_ENGINE,
    PREVIEW_FRONTEND,
    SHA,
    SOURCE_ENGINE,
    lifecycle,
)


TOKEN = "ghs_" + "S" * 36
REPO = lifecycle.REPOSITORY
SENSITIVE_STDOUT = json.dumps({
    "message": "Resource not accessible by integration",
    "private": "sensitive-response-body",
}).encode()


def completed(returncode, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def failure(status, message="Resource not accessible by integration"):
    return completed(1, SENSITIVE_STDOUT, f"gh: {message} (HTTP {status})\n".encode())


class GithubApiDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.github = lifecycle.Github(TOKEN)

    def call(self, result, endpoint, method="GET", data=None):
        kwargs = {"side_effect": result} if isinstance(result, BaseException) else {
            "return_value": result
        }
        with patch.object(lifecycle.subprocess, "run", **kwargs) as run:
            with self.assertRaises(lifecycle.LifecycleError) as error:
                self.github.api(endpoint, method=method, data=data)
        return str(error.exception), run

    def assert_sanitized(self, message):
        for secret in (
            TOKEN,
            "sensitive-response-body",
            "Resource not accessible",
            "private comment body",
            "per_page",
            "page=",
            "?",
            "https://",
        ):
            self.assertNotIn(secret, message)
        self.assertLess(len(message), 400)
        self.assertNotIn("\n", message)

    def test_successful_get_and_write_requests_are_unchanged(self):
        with patch.object(
            lifecycle.subprocess, "run", return_value=completed(0, b'{"number": 56}')
        ) as run:
            self.assertEqual(self.github.api(f"repos/{REPO}/pulls/56"), {"number": 56})
        self.assertEqual(
            run.call_args.args[0], ["gh", "api", "--method", "GET", f"repos/{REPO}/pulls/56"]
        )
        self.assertIsNone(run.call_args.kwargs["input"])

        with patch.object(
            lifecycle.subprocess, "run", return_value=completed(0, b'{"id": 1}')
        ) as run:
            self.github.api(
                f"repos/{REPO}/issues/56/comments", method="POST", data={"body": "x"}
            )
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[-2:], ["--input", "-"])
        self.assertNotIn("x", " ".join(arguments[:-2]).split())
        self.assertEqual(run.call_args.kwargs["input"], b'{"body":"x"}')
        self.assertTrue(all(TOKEN not in argument for argument in arguments))

    def test_create_comment_permission_failure_is_actionable_and_sanitized(self):
        message, _ = self.call(
            failure(403),
            f"repos/{REPO}/issues/56/comments",
            method="POST",
            data={"body": "private comment body"},
        )
        self.assertEqual(
            message,
            "GitHub API request failed: operation=create-pr-comment method=POST "
            "endpoint=repos/{repo}/issues/{id}/comments status=403 "
            "category=permission-denied hint=the workflow GITHUB_TOKEN lacks a "
            "permission this operation requires.",
        )
        self.assert_sanitized(message)

    def test_operations_and_endpoint_categories_drop_queries_and_ids(self):
        cases = [
            ("GET", f"repos/{REPO}/pulls/56", "read-pull-request",
             "repos/{repo}/pulls/{id}"),
            ("GET", f"repos/{REPO}/issues/56/comments?per_page=100&page=2",
             "list-pr-comments", "repos/{repo}/issues/{id}/comments"),
            ("PATCH", f"repos/{REPO}/issues/comments/6502748064", "update-pr-comment",
             "repos/{repo}/issues/comments/{id}"),
            ("GET", f"repos/{REPO}/actions/workflows/ci.yml", "read-workflow",
             "repos/{repo}/actions/workflows/ci.yml"),
            ("POST", f"repos/{REPO}/actions/workflows/x.yml/dispatches", "dispatch-workflow",
             "repos/{repo}/actions/workflows/x.yml/dispatches"),
            ("GET", f"repos/{REPO}/actions/workflows/x.yml/runs?event=workflow_dispatch",
             "list-workflow-runs", "repos/{repo}/actions/workflows/x.yml/runs"),
            ("GET", f"repos/{REPO}/contents/.github/workflows/ci.yml?ref={SHA}",
             "read-file-contents", "repos/{repo}/contents/{value}/workflows/ci.yml"),
            ("GET", f"repos/{REPO}/actions/runs/9/artifacts?per_page=100",
             "list-run-artifacts", "repos/{repo}/actions/runs/{id}/artifacts"),
            ("DELETE", f"repos/{REPO}/unexpected/{TOKEN}", "github-api-request",
             "repos/{repo}/unexpected/{value}"),
        ]
        for method, endpoint, operation, category in cases:
            with self.subTest(endpoint=endpoint):
                message, _ = self.call(failure(404, "Not Found"), endpoint, method=method)
                self.assertIn(f"operation={operation} method={method} ", message)
                self.assertIn(f" endpoint={category} ", message)
                self.assert_sanitized(message)
                self.assertNotIn(SHA, message)

    def test_failure_categories(self):
        cases = [
            (failure(401, "Bad credentials"), "401", "authentication-failed"),
            (failure(403, "API rate limit exceeded for installation"), "403", "rate-limited"),
            (failure(403, "You have exceeded a secondary rate limit"), "403", "rate-limited"),
            (failure(429, "Too Many Requests"), "429", "rate-limited"),
            (failure(403, "Must have admin rights"), "403", "authorization-denied"),
            (failure(403), "403", "permission-denied"),
            (failure(404, "Not Found"), "404", "not-found"),
            (failure(422, "Validation Failed"), "422", "request-rejected"),
            (failure(409, "Conflict"), "409", "request-rejected"),
            (failure(500, "Server Error"), "500", "server-error"),
            (failure(502, "Bad Gateway"), "502", "server-error"),
            (failure(418, "Teapot"), "418", "unexpected-http-status"),
            (completed(1, b"", b"error connecting to api.github.com\n"),
             "unavailable", "transport-failure"),
            (completed(1, SENSITIVE_STDOUT, f"token {TOKEN} leaked".encode()),
             "unavailable", "transport-failure"),
            (OSError(f"gh missing {TOKEN}"), "unavailable", "transport-failure"),
            (subprocess.TimeoutExpired(["gh", TOKEN], 120, SENSITIVE_STDOUT),
             "unavailable", "transport-failure"),
        ]
        for result, status, category in cases:
            with self.subTest(category=category, status=status, result=repr(result)[:60]):
                message, _ = self.call(result, f"repos/{REPO}/pulls/56")
                self.assertIn(f" status={status} category={category} hint=", message)
                self.assert_sanitized(message)
                self.assertNotIn("connecting", message)

    def test_artifact_download_failures_are_classified(self):
        with patch.object(lifecycle.subprocess, "run", return_value=failure(410, "Gone")):
            with self.assertRaises(lifecycle.LifecycleError) as error:
                self.github.artifact_zip(7, "sha256:" + "a" * 64)
        self.assertIn(
            "operation=download-artifact method=GET "
            "endpoint=repos/{repo}/actions/artifacts/{id}/zip status=410",
            str(error.exception),
        )

    def test_invalid_get_metadata_still_fails_closed(self):
        with patch.object(lifecycle.subprocess, "run", return_value=completed(0, b"not-json")):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "invalid metadata"):
                self.github.api(f"repos/{REPO}/pulls/56")


class PreviewCommentLifecycleTests(unittest.TestCase):
    def deployment(self):
        context = lifecycle.BuildContext(
            "41", SHA, 1234, 1, 5678, "sha256:" + "d" * 64, "image", "/tmp/image.tar"
        )
        deployment = lifecycle.PreviewDeployment(context, lifecycle.Github(TOKEN))
        deployment.source_engine_image = SOURCE_ENGINE
        deployment.preview_engine_image = PREVIEW_ENGINE
        deployment.frontend_image = PREVIEW_FRONTEND
        deployment.database_was_created = False
        return deployment

    def run_update(self, existing, write_result):
        calls = []

        def run(arguments, **kwargs):
            calls.append((arguments, kwargs.get("input")))
            if arguments[3] == "GET":
                return completed(0, json.dumps(existing).encode())
            return write_result

        with patch.object(lifecycle.subprocess, "run", side_effect=run):
            self.deployment().update_comment("https://preview.run.app")
        return calls

    def test_comment_is_created_when_none_exists(self):
        human = [{"id": 5, "body": lifecycle.COMMENT_MARKER, "user": {"login": "jtesolin"}}]
        calls = self.run_update(human, completed(0, b"{}"))
        writes = [call for call in calls if call[0][3] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0][3:5], ["POST", f"repos/{REPO}/issues/41/comments"])
        self.assertIn(b"## Preview Environment", writes[0][1])

    def test_existing_bot_comment_is_updated_not_duplicated(self):
        bot = [{
            "id": 17,
            "body": lifecycle.COMMENT_MARKER,
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        }]
        calls = self.run_update(bot, completed(0, b"{}"))
        writes = [call for call in calls if call[0][3] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0][3:5], ["PATCH", f"repos/{REPO}/issues/comments/17"])

    def test_comment_write_failure_fails_closed_without_leaking_body(self):
        with self.assertRaises(lifecycle.LifecycleError) as error:
            self.run_update([], failure(403))
        message = str(error.exception)
        self.assertIn("operation=create-pr-comment", message)
        self.assertIn("category=permission-denied", message)
        self.assertNotIn("Preview Environment", message)
        self.assertNotIn("preview.run.app", message)

    def test_main_reports_sanitized_failure_and_nonzero_exit(self):
        stderr = io.StringIO()
        error = lifecycle.LifecycleError(
            lifecycle.github_failure_message(
                "POST", f"repos/{REPO}/issues/56/comments", 403,
                b"gh: Resource not accessible by integration (HTTP 403)",
            )
        )
        with patch.object(lifecycle, "deploy", side_effect=error), patch(
            "sys.argv", ["lifecycle.py", "deploy", "--context", "unused"]
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(lifecycle.main(), 1)
        output = stderr.getvalue()
        self.assertTrue(output.startswith("ERROR: GitHub API request failed: "))
        self.assertIn("status=403 category=permission-denied", output)
        self.assertNotIn("Resource not accessible", output)


class DeployWorkflowPermissionTests(unittest.TestCase):
    def test_deploy_job_can_write_pr_comments_without_other_broadening(self):
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/preview-deploy.yml"
        ).read_text(encoding="utf-8")
        deploy = workflow.split("\n  deploy:\n", 1)[1]
        block = deploy.split("    permissions:\n", 1)[1].split("    env:\n", 1)[0]
        permissions = {
            line.strip().split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        self.assertEqual(
            permissions,
            {
                "contents": "read",
                "actions": "write",
                "id-token": "write",
                "pull-requests": "write",
                "issues": "write",
            },
        )


if __name__ == "__main__":
    unittest.main()
