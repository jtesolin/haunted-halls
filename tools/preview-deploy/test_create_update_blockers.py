"""Offline regression tests for the remaining create/update trust gates."""

import argparse
import base64
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from test_lifecycle import lifecycle, github_pr, workflow_run, SHA, INCARNATION


REQUEST_ID = "d" * 32
JOB = "hh-web-pr-41-migrate"


def deployment():
    return lifecycle.PreviewDeployment(
        lifecycle.BuildContext("41", SHA, 123, 1, 456, "sha256:" + "a" * 64,
                               "image", "/tmp/image.tar"),
        Mock(),
    )


def execution(suffix, state="True", count=1):
    return {
        "metadata": {"name": f"{JOB}-{suffix}", "labels": {"run.googleapis.com/job": JOB}},
        "status": {"succeededCount": count,
                   "conditions": [{"type": "Completed", "status": state}]},
    }


def policy(role, members):
    return {"version": 3, "bindings": [
        {"role": role, "members": sorted(members)},
        {"role": "roles/viewer", "members": ["user:unrelated@example.com"]},
    ]}


class CiSourceTests(unittest.TestCase):
    def record(self, content):
        return {"type": "file", "encoding": "base64",
                "content": base64.b64encode(content).decode(),
                "sha": hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()}

    def test_unchanged_passes_but_changed_bytes_or_blob_fail(self):
        trusted = Path(".github/workflows/ci.yml").read_bytes()
        lifecycle.verify_ci_source(self.record(trusted), trusted)
        for record in (self.record(trusted + b"\n"),
                       {**self.record(trusted), "sha": "0" * 40},
                       {**self.record(trusted), "content": "***"}):
            with self.subTest(record=record["sha"]), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.verify_ci_source(record, trusted)

    def test_prepare_checks_exact_head_before_artifact_access(self):
        run = {**workflow_run(), "id": 123, "workflow_id": 10,
               "path": ".github/workflows/ci.yml", "event": "pull_request",
               "status": "completed", "conclusion": "success", "run_attempt": 1,
               "head_repository": {"full_name": lifecycle.REPOSITORY}}
        environment = {
            "GITHUB_REPOSITORY": lifecycle.REPOSITORY,
            "GITHUB_WORKFLOW_REF": (
                f"{lifecycle.REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main"
            ),
            "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_run",
            "GH_TOKEN": "offline",
        }
        for changed in (False, True):
            calls = []
            def api(endpoint):
                calls.append(endpoint)
                if endpoint.endswith("/actions/workflows/ci.yml"):
                    return {"id": 10, "path": ".github/workflows/ci.yml"}
                if endpoint.endswith("/actions/runs/123"):
                    return run
                if endpoint.endswith("/pulls/41"):
                    return github_pr()
                if "/contents/" in endpoint:
                    self.assertTrue(endpoint.endswith(f"?ref={SHA}"))
                    trusted = Path(".github/workflows/ci.yml").read_bytes()
                    return self.record(trusted + (b"\n" if changed else b""))
                raise RuntimeError("artifact gate reached")
            with tempfile.TemporaryDirectory() as directory:
                event = Path(directory) / "event.json"
                event.write_text(json.dumps({"workflow_run": run}))
                args = argparse.Namespace(event=str(event), output_directory=directory,
                                          github_output=str(Path(directory) / "output"))
                with patch.dict(os.environ, environment), patch.object(
                    lifecycle.Github, "api", side_effect=api
                ), patch.object(lifecycle.Github, "artifact_zip") as download, patch.object(
                    lifecycle.Commands, "run"
                ) as commands:
                    with self.assertRaises(lifecycle.LifecycleError if changed else RuntimeError):
                        lifecycle.prepare(args)
                    download.assert_not_called()
                    commands.assert_not_called()
                self.assertEqual(any("/artifacts?" in call for call in calls), not changed)


class MigrationTests(unittest.TestCase):
    def test_active_execution_finishes_before_async_launch_and_exact_poll(self):
        calls = []
        results = [
            [execution("old", "Unknown", 0), execution("historical", "False", 0)],
            execution("old", "Unknown", 0), execution("old"),
            execution("new", "Unknown", 0),
            execution("new", "Unknown", 0), execution("new"),
        ]
        def command(arguments, **kwargs):
            calls.append(arguments)
            return results.pop(0)
        with patch.object(lifecycle.Commands, "json", side_effect=command), patch.object(
            lifecycle.time, "sleep"
        ):
            deployment().run_migration()
        self.assertIn(f"--job={JOB}", calls[0])
        launch = next(index for index, call in enumerate(calls) if "execute" in call)
        self.assertEqual(launch, 3)
        self.assertIn("--async", calls[launch])
        self.assertNotIn("--wait", calls[launch])
        self.assertTrue(all(f"{JOB}-new" in call for call in calls[launch + 1:]))

    def test_failed_unresolved_foreign_or_malformed_active_execution_blocks_launch(self):
        cases = [
            ([execution("old", "Unknown", 0)], execution("old", "False", 0)),
            ([execution("old", "Unknown", 0)], execution("old", "Unknown", 0)),
            ([{"metadata": {"name": "hh-web-pr-42-migrate-old"}}], None),
            ([{"metadata": {"name": f"{JOB}-old"}, "status": {}}], None),
        ]
        for active, polled in cases:
            calls = []
            def command(arguments, **kwargs):
                calls.append(arguments)
                return active if "list" in arguments else polled
            with self.subTest(active=active), patch.object(
                lifecycle.Commands, "json", side_effect=command
            ), patch.object(lifecycle.time, "sleep"), patch.object(
                lifecycle.time, "monotonic", side_effect=[0, 1, 901]
            ), self.assertRaises(lifecycle.LifecycleError):
                deployment().run_migration()
            self.assertFalse(any("execute" in call for call in calls))

    def test_new_execution_failure_or_multiple_successes_stop(self):
        for state, count in (("False", 0), ("True", 2), ("Unknown", 0)):
            with self.subTest(state=state, count=count), patch.object(
                lifecycle.Commands, "json",
                side_effect=[[], execution("new", "Unknown", 0), execution("new", state, count)]
            ), patch.object(lifecycle.time, "sleep"), patch.object(
                lifecycle.time, "monotonic", side_effect=[0, 1, 901]
            ), self.assertRaises(lifecycle.LifecycleError):
                deployment().run_migration()


class LivePolicyTests(unittest.TestCase):
    def test_rollout_reads_live_invokers_before_http_probes_and_rejects_drift(self):
        frontend_url = "https://hh-web-pr-41-frontend-1001419903197.us-east1.run.app"
        engine_url = "https://hh-web-pr-41-engine-1001419903197.us-east1.run.app"
        frontend_member = (
            f"serviceAccount:hh-preview-frontend@{lifecycle.PREVIEW_PROJECT}.iam.gserviceaccount.com"
        )
        iap_member = (
            f"serviceAccount:service-{lifecycle.PREVIEW_PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
        )
        for drift in (None, "engine", "frontend"):
            current = deployment()
            current.frontend_image = "frontend-digest"
            current.preview_engine_image = "engine-digest"
            current.database_was_created = False
            current.verify_testers = Mock()
            results = [
                {"database_name": current.database, "repository_key": "web", "pr_number": "41",
                 "frontend_image": current.frontend_image, "engine_image": current.preview_engine_image,
                 "engine_url": engine_url},
                {"iapEnabled": True}, {}, {}, {},
                policy("roles/run.invoker", {frontend_member} | (
                    {"allUsers"} if drift == "engine" else set()
                )),
                policy("roles/run.invoker", {iap_member} | (
                    {"allAuthenticatedUsers"} if drift == "frontend" else set()
                )),
            ]
            with self.subTest(drift=drift), patch.object(
                lifecycle.Commands, "json", side_effect=results
            ) as commands, patch.object(
                lifecycle, "latest_ready_revision_name", return_value="revision"
            ), patch.object(
                lifecycle, "verify_serving_revision",
                side_effect=[("revision", frontend_url), ("revision", engine_url)]
            ), patch.object(lifecycle, "verify_unauthenticated_denied") as probe:
                if drift:
                    with self.assertRaises(lifecycle.LifecycleError):
                        current.verify_runtime(False)
                    probe.assert_not_called()
                    current.verify_testers.assert_not_called()
                else:
                    self.assertEqual(current.verify_runtime(False), frontend_url)
                    current.verify_testers.assert_called_once()
                    self.assertEqual(probe.call_args_list[0].args, (frontend_url + "/",))
                    self.assertEqual(probe.call_args_list[1].args, (engine_url + "/health",))
                    self.assertFalse(probe.call_args_list[1].kwargs["allow_google_redirect"])
                policies = [
                    call.args[0][4] for call in commands.call_args_list
                    if "get-iam-policy" in call.args[0]
                ]
                self.assertEqual(policies[0], "hh-web-pr-41-engine")
                if drift != "engine":
                    self.assertEqual(policies[1], "hh-web-pr-41-frontend")

    def test_exact_access_for_engine_frontend_and_iap_preserves_unrelated_roles(self):
        for role, expected in (
            ("roles/run.invoker", {
                f"serviceAccount:hh-preview-frontend@{lifecycle.PREVIEW_PROJECT}.iam.gserviceaccount.com"
            }),
            ("roles/run.invoker", {
                f"serviceAccount:service-{lifecycle.PREVIEW_PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
            }),
            ("roles/iap.httpsResourceAccessor", {"user:tester@example.com"}),
        ):
            original = policy(role, expected)
            before = copy.deepcopy(original)
            lifecycle.verify_policy_members(original, role, expected)
            self.assertEqual(original, before)
            for unexpected in ("allUsers", "allAuthenticatedUsers", "user:foreign@example.com"):
                with self.subTest(role=role, unexpected=unexpected), self.assertRaises(
                    lifecycle.LifecycleError
                ):
                    lifecycle.verify_policy_members(policy(role, expected | {unexpected}), role, expected)
            for bad in (policy(role, set()), {"bindings": []},
                        {"bindings": [{"role": role, "members": sorted(expected),
                                       "condition": {"expression": "true"}}]}):
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.verify_policy_members(bad, role, expected)

    def test_invoker_verification_reads_exact_live_service(self):
        expected = {"serviceAccount:frontend@example.com"}
        with patch.object(lifecycle.Commands, "json", return_value=policy(
            "roles/run.invoker", expected
        )) as command:
            deployment().verify_invokers("hh-web-pr-41-engine", expected)
        self.assertEqual(command.call_args.args[0][:5],
                         ["gcloud", "run", "services", "get-iam-policy", "hh-web-pr-41-engine"])

    def test_live_iap_post_resource_body_and_drift_detection(self):
        current = deployment()
        current.terraform_state = lambda: {"resources": [{
            "mode": "managed", "type": "google_iap_web_cloud_run_service_iam_member",
            "name": "tester", "instances": [{"attributes": {
                "role": "roles/iap.httpsResourceAccessor", "member": "user:tester@example.com",
                "cloud_run_service_name": "hh-web-pr-41-frontend",
                "project": lifecycle.PREVIEW_PROJECT, "location": lifecycle.PREVIEW_REGION,
            }}],
        }]}
        for drift in (False, True):
            live = policy("roles/iap.httpsResourceAccessor",
                          {"user:tester@example.com"} | ({"allUsers"} if drift else set()))
            with patch.dict(os.environ, {"PREVIEW_IAP_TESTERS": "user:tester@example.com"}), patch.object(
                lifecycle.Commands, "run", return_value=b"offline-token"
            ), patch.object(lifecycle.urllib.request, "urlopen") as open_request:
                open_request.return_value.__enter__.return_value = io.BytesIO(json.dumps(live).encode())
                if drift:
                    with self.assertRaises(lifecycle.LifecycleError):
                        current.verify_testers()
                else:
                    current.verify_testers()
                request = open_request.call_args.args[0]
                self.assertEqual(request.method, "POST")
                self.assertEqual(json.loads(request.data), {"options": {"requestedPolicyVersion": 3}})
                self.assertEqual(request.full_url, (
                    "https://iap.googleapis.com/v1/projects/1001419903197"
                    "/iap_web/cloud_run-us-east1/services/hh-web-pr-41-frontend:getIamPolicy"
                ))

    def test_frontend_redirect_only_exact_https_auth_host_and_engine_never_redirects(self):
        for location, permitted in (
            ("https://accounts.google.com/o/oauth2/auth", True),
            ("http://accounts.google.com/auth", False),
            ("https://evil.google.com/auth", False),
            ("https://accounts.google.com.evil.example/auth", False),
            ("https://user@accounts.google.com/auth", False),
            ("https://accounts.google.com:8443/auth", False),
        ):
            opener = Mock()
            error = urllib.error.HTTPError(
                "https://preview.run.app", 302, "redirect", {"Location": location}, None
            )
            opener.open.side_effect = error
            with patch.object(lifecycle.urllib.request, "build_opener", return_value=opener):
                if permitted:
                    lifecycle.verify_unauthenticated_denied("https://preview.run.app", True)
                else:
                    with self.assertRaises(lifecycle.LifecycleError):
                        lifecycle.verify_unauthenticated_denied("https://preview.run.app", True)
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.verify_unauthenticated_denied("https://engine.run.app/health", False)
            error.close()


class DispatchTests(unittest.TestCase):
    def metadata(self, request_id):
        return {"pull_request_number": "41", "pr_incarnation": INCARNATION,
                "generation": "8", "state": "complete", "request_id": request_id,
                "secret_versions": {"nextauth": "1", "internal_token": "2", "database_url": "3"}}

    def test_wrong_artifact_request_id_rejected(self):
        for request_id in ("e" * 32, "", None, REQUEST_ID.upper()):
            with self.subTest(request_id=request_id), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.validate_secret_metadata(self.metadata(request_id), "41", INCARNATION,
                                                   8, REQUEST_ID)

    def test_rapid_identical_dispatches_bind_distinct_title_and_metadata(self):
        current = deployment()
        current.revalidate_pr = Mock()
        titles = []
        def wait(title):
            titles.append(title)
            return {"id": len(titles)}
        current.wait_for_secret_workflow = wait
        ids = [REQUEST_ID, "e" * 32]
        archives = []
        for request_id in ids:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("secret-version-metadata.json", json.dumps(self.metadata(request_id)))
            archives.append(output.getvalue())
        current.github.api.side_effect = [
            b"", {"artifacts": [{"id": 1, "name": lifecycle.SECRET_ARTIFACT, "expired": False,
                                "digest": "sha256:" + hashlib.sha256(archives[0]).hexdigest()}]},
            b"", {"artifacts": [{"id": 2, "name": lifecycle.SECRET_ARTIFACT, "expired": False,
                                "digest": "sha256:" + hashlib.sha256(archives[1]).hexdigest()}]},
        ]
        current.github.artifact_zip.side_effect = archives
        with patch.dict(os.environ, {"PREVIEW_IAP_TESTERS": "user:tester@example.com"}), patch.object(
            lifecycle.secrets, "token_hex", side_effect=ids
        ) as random_id:
            current.run_secret_workflow("prepare", INCARNATION, 8)
            current.run_secret_workflow("prepare", INCARNATION, 8)
        self.assertNotEqual(titles[0], titles[1])
        for index, request_id in enumerate(ids):
            self.assertTrue(titles[index].endswith(f"-request-{request_id}"))
            dispatch = current.github.api.call_args_list[index * 2]
            self.assertEqual(dispatch.kwargs["data"]["inputs"]["request_id"], request_id)
        self.assertEqual(random_id.call_args_list[0].args, (16,))

    def test_run_selection_uses_exact_title_not_timestamp(self):
        current = deployment()
        title = f"Preview secret preparation prepare PR-41-{INCARNATION}-gen-8-request-{REQUEST_ID}"
        match = {"id": 9, "display_title": title, "event": "workflow_dispatch",
                 "head_branch": "main", "workflow_id": 7, "status": "completed",
                 "conclusion": "success", "path": f".github/workflows/{lifecycle.SECRET_WORKFLOW}"}
        current.github.api.side_effect = [
            {"id": 7, "path": match["path"]},
            {"workflow_runs": [
                {**match, "id": 8, "display_title": title.replace(REQUEST_ID, "e" * 32)},
                match,
            ]},
        ]
        self.assertEqual(current.wait_for_secret_workflow(title)["id"], 9)

    def test_malformed_request_id_rejected_by_pre_auth_workflow_validator(self):
        source = Path(".github/workflows/preview-secret-prepare.yml").read_text()
        validation = next(line.strip() for line in source.splitlines()
                          if "python3 -c" in line and '"$REQUEST_ID"' in line)
        self.assertLess(source.index(validation),
                        source.index("Authenticate only as the dedicated secret preparer"))
        self.assertIn("request_id:\n", source)
        for request_id in ("", "A" * 32, "a" * 31, "a" * 33, "$(exit 0)", REQUEST_ID):
            result = subprocess.run(["bash", "-c", validation],
                                    env={**os.environ, "REQUEST_ID": request_id}, capture_output=True)
            self.assertEqual(result.returncode == 0, request_id == REQUEST_ID)
        # Correlation is workflow metadata only, never a secret/ledger/Terraform identity.
        for filename in ("prepare.py", "terraform_targets.py"):
            self.assertNotIn("request_id", Path(f"tools/preview-secret-preparer/{filename}").read_text())
        self.assertNotIn("request_id", "\n".join(
            path.read_text() for path in Path("infra/terraform/preview-pr").glob("*.tf")
        ))


class ApplyPlanRevalidationTests(unittest.TestCase):
    """apply_plan centrally revalidates the exact PR around one saved plan."""

    def harness(self, temp, second_pr, unlink_error=False):
        current = deployment()
        context = current.context
        calls = []
        responses = [github_pr(), second_pr]

        def api(endpoint, method="GET", data=None):
            self.assertEqual((endpoint, method, data),
                             (f"repos/{lifecycle.REPOSITORY}/pulls/41", "GET", None))
            calls.append("revalidate")
            return responses.pop(0)

        def run(arguments, **kwargs):
            command = arguments[2]
            calls.append(command)
            if command == "plan":
                out = next(a for a in arguments if a.startswith("-out="))
                Path(out.removeprefix("-out=")).write_bytes(b"saved-plan")
            return b""

        def show(arguments, **kwargs):
            calls.append("show")
            return {"resource_changes": [
                {"address": address, "change": {"actions": ["create"]}}
                for address in sorted(lifecycle.TARGETS["containers"])
            ]}

        def check_backend():
            calls.append("check-backend")

        current.github.api.side_effect = api
        current.check_backend = check_backend
        stack = contextlib.ExitStack()
        stack.enter_context(patch.dict(os.environ, {"RUNNER_TEMP": temp}))
        run_mock = stack.enter_context(patch.object(lifecycle.Commands, "run", side_effect=run))
        stack.enter_context(patch.object(lifecycle.Commands, "json", side_effect=show))
        if unlink_error:
            stack.enter_context(patch.object(Path, "unlink", side_effect=OSError("busy")))
        return current, context, calls, stack, run_mock

    @staticmethod
    def apply(current, stack):
        targets = set(lifecycle.TARGETS["containers"])
        with stack:
            current.apply_plan("secret-containers", ["-var=x=1"], targets, allowed=targets)

    def test_exact_ordering_and_one_saved_plan_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            current, context, calls, stack, run = self.harness(temp, github_pr())
            self.apply(current, stack)
            plan_path = Path(temp) / "preview-41-secret-containers.tfplan"
            self.assertEqual(calls, ["revalidate", "check-backend", "plan", "show",
                                     "check-backend", "revalidate", "apply"])
            applies = [c.args[0] for c in run.call_args_list if c.args[0][2] == "apply"]
            self.assertEqual(len(applies), 1)
            self.assertEqual(applies[0][-1], str(plan_path))
            self.assertFalse(any(a.startswith("-var") or a.startswith("-target")
                                 for a in applies[0]))
            self.assertFalse(plan_path.exists())
            self.assertIs(current.context, context)

    def test_stale_closed_or_draft_pr_after_planning_blocks_apply(self):
        cases = {
            "stale-head": github_pr(sha="e" * 40),
            "closed": {**github_pr(), "state": "closed"},
            "draft": github_pr(draft=True),
            "base-not-main": {**github_pr(), "base": {"ref": "release",
                              "repo": {"full_name": lifecycle.REPOSITORY}}},
            "other-pr": github_pr(number=42),
        }
        for label, second in cases.items():
            for unlink_error in (False, True):
                with self.subTest(label=label, unlink_error=unlink_error), \
                        tempfile.TemporaryDirectory() as temp:
                    current, context, calls, stack, _ = self.harness(temp, second, unlink_error)
                    with self.assertRaises(lifecycle.LifecycleError):
                        self.apply(current, stack)
                    self.assertEqual(calls, ["revalidate", "check-backend", "plan", "show",
                                             "check-backend", "revalidate"])
                    self.assertNotIn("apply", calls)
                    self.assertEqual(calls.count("plan"), 1)
                    plan_path = Path(temp) / "preview-41-secret-containers.tfplan"
                    self.assertEqual(plan_path.exists(), unlink_error)
                    self.assertIs(current.context, context)
                    self.assertEqual((current.number, current.sha), ("41", SHA))


if __name__ == "__main__":
    unittest.main()
