import hashlib
import importlib.util
import io
import json
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("preview_lifecycle", ROOT / "lifecycle.py")
lifecycle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lifecycle
SPEC.loader.exec_module(lifecycle)


SHA = "a" * 40
INCARNATION = "b" * 32
DIGEST = "sha256:" + "c" * 64
PREVIEW_FRONTEND = (
    "us-east1-docker.pkg.dev/hh-preview-458395246135/"
    "haunted-halls-preview/frontend@" + DIGEST
)
PREVIEW_ENGINE = (
    "us-east1-docker.pkg.dev/hh-preview-458395246135/"
    "haunted-halls-preview/engine@" + DIGEST
)
SOURCE_ENGINE = (
    "us-east1-docker.pkg.dev/haunted-halls-development/"
    "haunted-halls/engine@" + DIGEST
)


def github_pr(*, draft=False, sha=SHA, number=41):
    return {
        "number": number,
        "state": "open",
        "draft": draft,
        "base": {"ref": "main", "repo": {"full_name": lifecycle.REPOSITORY}},
        "head": {
            "sha": sha,
            "ref": "preview-test",
            "repo": {"full_name": lifecycle.REPOSITORY},
        },
    }


def workflow_run(*, sha=SHA, number=41):
    return {
        "head_sha": sha,
        "pull_requests": [{"number": number, "head": {"sha": sha}}],
    }


def ready_conditions(kind="Ready"):
    return [{"type": kind, "state": "CONDITION_SUCCEEDED"}]


def terraform_state(number="41", generation="7", incarnation=INCARNATION):
    resources = []
    for role, suffix in (
        ("nextauth", "nextauth"),
        ("internal_token", "internal-token"),
        ("database_url", "database-url"),
    ):
        resources.append(
            {
                "mode": "managed",
                "type": "google_secret_manager_secret",
                "name": "pr",
                "instances": [
                    {
                        "index_key": role,
                        "attributes": {
                            "secret_id": (
                                f"hh-web-pr-{number}-i-{incarnation}-{suffix}"
                            ),
                            "labels": {
                                "app": "haunted-halls",
                                "environment": "preview",
                                "repository": "web",
                                "pull_request": number,
                                "incarnation": incarnation,
                                "managed_by": "terraform",
                                "secret_generation": generation,
                            },
                        },
                    }
                ],
            }
        )
    return {"resources": resources}


class EligibilityTests(unittest.TestCase):
    def test_draft_pr_is_a_noop_but_ready_matching_sha_is_eligible(self):
        self.assertIsNone(lifecycle.eligibility(workflow_run(), github_pr(draft=True)))
        self.assertEqual(
            lifecycle.eligibility(workflow_run(), github_pr()),
            ("41", SHA),
        )

    def test_closed_stale_fork_or_mismatched_pr_is_not_deployed(self):
        closed = github_pr()
        closed["state"] = "closed"
        fork = github_pr()
        fork["head"]["repo"]["full_name"] = "someone/fork"
        self.assertIsNone(lifecycle.eligibility(workflow_run(), closed))
        self.assertIsNone(lifecycle.eligibility(workflow_run(sha="d" * 40), github_pr()))
        self.assertIsNone(lifecycle.eligibility(workflow_run(), fork))
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.eligibility(
                {"pull_requests": [{"number": 41}, {"number": 42}]},
                github_pr(),
            )

    def test_artifact_name_binds_pr_sha_attempt_and_run_metadata(self):
        name = lifecycle.artifact_name("41", SHA, 3)
        artifact = lifecycle.validate_artifact_record(
            123,
            name,
            [
                {
                    "id": 8,
                    "name": name,
                    "expired": False,
                    "digest": "sha256:" + "d" * 64,
                }
            ],
        )
        self.assertEqual(artifact["id"], 8)
        for invalid in (
            [],
            [{"id": 8, "name": name, "expired": True, "digest": "sha256:" + "d" * 64}],
            [{"id": 8, "name": name, "expired": False, "digest": None}],
            [
                {"id": 8, "name": name, "expired": False, "digest": "sha256:" + "d" * 64},
                {"id": 9, "name": name, "expired": False, "digest": "sha256:" + "e" * 64},
            ],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.validate_artifact_record(123, name, invalid)

    def test_artifact_archive_digest_and_contents_are_verified(self):
        files = {
            "frontend-image.tar": b"image bytes",
            "frontend-image.tar.sha256": (
                hashlib.sha256(b"image bytes").hexdigest() + "  frontend-image.tar\n"
            ).encode(),
        }
        archive_io = io.BytesIO()
        with zipfile.ZipFile(archive_io, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        raw = archive_io.getvalue()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        extracted = lifecycle.extract_artifact_zip(
            raw, digest, set(files)
        )
        self.assertEqual(
            lifecycle.validate_image_archive(extracted, "41", SHA),
            f"hh-web-pr-41-frontend:{SHA}",
        )
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.extract_artifact_zip(raw, "sha256:" + "f" * 64, set(files))

    def test_database_name_is_deterministic_and_bounded(self):
        self.assertEqual(
            lifecycle.derive_database_name("41"),
            "haunted_halls_web_pr_41",
        )
        self.assertEqual(
            lifecycle.derive_database_name("999999999"),
            "haunted_halls_web_pr_999999999",
        )
        for number in ("0", "01", "1000000000", "../41"):
            with self.subTest(number=number), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.derive_database_name(number)

    def test_existing_database_is_reused_without_reset(self):
        database = "haunted_halls_web_pr_41"
        self.assertTrue(
            lifecycle.validate_database_result(
                {"database": database, "operation": "create", "created": True},
                database,
            )
        )
        self.assertFalse(
            lifecycle.validate_database_result(
                {"database": database, "operation": "create", "created": False},
                database,
            )
        )
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.validate_database_result(
                {"database": database, "operation": "drop", "created": False},
                database,
            )


class StagingAndTerraformTests(unittest.TestCase):
    def staging_metadata(self, image=SOURCE_ENGINE):
        service = {
            "name": "projects/haunted-halls-development/locations/us-east1/services/haunted-halls-engine-staging",
            "status": {
                "conditions": ready_conditions(),
                "latestReadyRevisionName": "haunted-halls-engine-staging-00042-abc",
                "latestCreatedRevisionName": "haunted-halls-engine-staging-00042-abc",
                "trafficStatuses": [
                    {
                        "revision": "haunted-halls-engine-staging-00042-abc",
                        "percent": 100,
                    }
                ],
            },
        }
        revision = {
            "name": "projects/haunted-halls-development/locations/us-east1/revisions/haunted-halls-engine-staging-00042-abc",
            "status": {
                "conditions": ready_conditions(),
                "containerStatuses": [{"imageDigest": image}],
            },
        }
        return service, revision

    def test_exact_ready_serving_staging_digest_is_frozen(self):
        service, revision = self.staging_metadata()
        self.assertEqual(lifecycle.staging_engine_digest(service, revision), SOURCE_ENGINE)

    def test_missing_invalid_or_not_serving_staging_digest_fails_closed(self):
        for image in (
            "us-east1-docker.pkg.dev/other/repo/engine@" + DIGEST,
            SOURCE_ENGINE.rsplit("@", 1)[0] + ":latest",
            SOURCE_ENGINE.rsplit("@", 1)[0] + "@sha256:" + "A" * 64,
        ):
            service, revision = self.staging_metadata(image)
            with self.subTest(image=image), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.staging_engine_digest(service, revision)
        service, revision = self.staging_metadata()
        service["status"]["trafficStatuses"][0]["percent"] = 50
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.staging_engine_digest(service, revision)
        revision["status"]["conditions"] = [{"type": "Ready", "state": "CONDITION_FAILED"}]
        service, revision = self.staging_metadata()
        revision["status"]["conditions"] = [{"type": "Ready", "state": "CONDITION_FAILED"}]
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.staging_engine_digest(service, revision)

    def test_pr_secret_incarnation_and_generation_survive_updates(self):
        self.assertIsNone(lifecycle.state_secret_identity({"resources": []}, "41"))
        self.assertEqual(
            lifecycle.state_secret_identity(terraform_state(), "41"),
            (INCARNATION, 7),
        )
        self.assertEqual(
            lifecycle.state_secret_identity(
                terraform_state(generation="8", incarnation=INCARNATION),
                "41",
            ),
            (INCARNATION, 8),
        )
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.state_secret_identity(terraform_state(number="42"), "41")
        partial = terraform_state()
        partial["resources"].pop()
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.state_secret_identity(partial, "41")

    def test_only_explicit_numeric_versions_are_returned_and_passed_to_terraform(self):
        metadata = {
            "pull_request_number": "41",
            "pr_incarnation": INCARNATION,
            "generation": "8",
            "state": "complete",
            "secret_versions": {
                "nextauth": "12",
                "internal_token": "14",
                "database_url": "16",
            },
        }
        versions = lifecycle.validate_secret_metadata(metadata, "41", INCARNATION, 8)
        self.assertEqual(set(versions), lifecycle.SECRET_ROLES)
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.validate_secret_metadata(
                {
                    **metadata,
                    "secret_versions": {**versions, "nextauth": "latest"},
                },
                "41",
                INCARNATION,
                8,
            )
        deployment = lifecycle.PreviewDeployment(
            lifecycle.BuildContext(
                "41", SHA, 1, 1, 1, "sha256:" + "e" * 64, "artifact", "/tmp/image.tar"
            ),
            object(),
        )
        deployment.frontend_image = PREVIEW_FRONTEND
        deployment.preview_engine_image = PREVIEW_ENGINE
        environment = {
            "PREVIEW_IAP_TESTERS": "user:tester@example.com",
            "PREVIEW_DB_PROVISIONER_URL": "https://preview-provisioner-abc-ue.a.run.app",
        }
        with patch.dict("os.environ", environment, clear=False):
            arguments = deployment.tf_arguments(INCARNATION, 8, versions)
        self.assertIn("-var=nextauth_secret_version=\"12\"", arguments)
        self.assertIn("-var=internal_engine_service_token_version=\"14\"", arguments)
        self.assertIn("-var=database_url_secret_version=\"16\"", arguments)
        self.assertFalse(any("latest" in item for item in arguments))

    def test_generation_reservation_retries_only_absent_attempts_and_advances_complete(self):
        self.assertEqual(lifecycle.select_secret_generation(0, "absent"), 1)
        self.assertEqual(lifecycle.select_secret_generation(1, "absent"), 1)
        self.assertEqual(lifecycle.select_secret_generation(1, "complete"), 2)
        for state in ("reserved", "writing", "reconciliation-required"):
            with self.subTest(state=state), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.select_secret_generation(1, state)

    def test_terraform_plan_rejects_deletes_and_unexpected_resource_addresses(self):
        allowed = {"google_cloud_run_v2_service.frontend"}
        lifecycle.validate_plan(
            {
                "resource_changes": [
                    {
                        "address": 'google_cloud_run_v2_service.frontend["x"]',
                        "change": {"actions": ["update"]},
                    }
                ]
            },
            allowed,
        )
        for action in (["delete"], ["delete", "create"]):
            with self.subTest(action=action), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.validate_plan(
                    {
                        "resource_changes": [
                            {
                                "address": "google_cloud_run_v2_service.frontend",
                                "change": {"actions": action},
                            }
                        ]
                    },
                    allowed,
                )
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.validate_plan(
                {
                    "resource_changes": [
                        {
                            "address": "google_project_iam_member.unrelated",
                            "change": {"actions": ["update"]},
                        }
                    ]
                },
                allowed,
            )

    def test_migration_status_requires_one_successful_task(self):
        self.assertTrue(
            lifecycle.execution_succeeded(
                {
                    "status": {
                        "succeededCount": 1,
                        "conditions": [
                            {"type": "Completed", "state": "CONDITION_SUCCEEDED"}
                        ],
                    }
                }
            )
        )
        self.assertFalse(
            lifecycle.execution_succeeded(
                {
                    "status": {
                        "succeededCount": 0,
                        "conditions": [
                            {"type": "Completed", "state": "CONDITION_FAILED"}
                        ],
                    }
                }
            )
        )


class OrchestrationTests(unittest.TestCase):
    def deployment(self):
        context = lifecycle.BuildContext(
            "41", SHA, 1234, 1, 5678, "sha256:" + "d" * 64, "image", "/tmp/image.tar"
        )
        return lifecycle.PreviewDeployment(context, object())

    def test_migration_precedes_rollout_and_existing_database_is_reused(self):
        deployment = self.deployment()
        calls = []
        deployment.revalidate_pr = lambda: calls.append("revalidate") or {}
        deployment.freeze_and_copy_engine = (
            lambda: calls.append("freeze-engine") or (SOURCE_ENGINE, PREVIEW_ENGINE)
        )
        deployment.publish_frontend_image = lambda: calls.append("publish-frontend") or PREVIEW_FRONTEND
        deployment.initialize_backend = lambda: calls.append("init-state")
        deployment.bootstrap_secrets = lambda: calls.append("bootstrap-secrets") or (INCARNATION, 2)
        deployment.ensure_database = lambda: calls.append("reuse-database") or False
        deployment.prepare_secret_generation = (
            lambda *args: calls.append("prepare-secrets")
            or (
                {"nextauth": "1", "internal_token": "2", "database_url": "3"},
                3,
            )
        )
        deployment.prepare_migration_job = lambda *args: calls.append("prepare-migration-job")
        deployment.run_migration = lambda: calls.append("migrate-to-head")
        deployment.apply_runtime = lambda *args: calls.append("rollout")
        deployment.verify_runtime = lambda created: calls.append(
            "verify-runtime-reused-db" if created is False else "verify-runtime-created-db"
        ) or "https://preview.run.app"
        deployment.update_comment = lambda url: calls.append("comment")
        environment = {
            "GITHUB_REPOSITORY": lifecycle.REPOSITORY,
            "GITHUB_WORKFLOW_REF": (
                f"{lifecycle.REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main"
            ),
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_run",
            "PREVIEW_IAP_TESTERS": "user:tester@example.com",
            "PREVIEW_DB_PROVISIONER_URL": (
                "https://preview-provisioner-abc-ue.a.run.app"
            ),
        }
        with patch.dict("os.environ", environment, clear=False):
            deployment.run()
        self.assertLess(calls.index("migrate-to-head"), calls.index("rollout"))
        self.assertIn("reuse-database", calls)
        self.assertIn("verify-runtime-reused-db", calls)
        self.assertLess(calls.index("rollout"), calls.index("comment"))

    def test_failed_migration_stops_before_rollout_and_comment(self):
        deployment = self.deployment()
        calls = []
        deployment.revalidate_pr = lambda: {}
        deployment.freeze_and_copy_engine = lambda: (SOURCE_ENGINE, PREVIEW_ENGINE)
        deployment.publish_frontend_image = lambda: PREVIEW_FRONTEND
        deployment.initialize_backend = lambda: None
        deployment.bootstrap_secrets = lambda: (INCARNATION, 2)
        deployment.ensure_database = lambda: False
        deployment.prepare_secret_generation = lambda *args: (
            {"nextauth": "1", "internal_token": "2", "database_url": "3"},
            3,
        )
        deployment.prepare_migration_job = lambda *args: None
        deployment.run_migration = lambda: (_ for _ in ()).throw(
            lifecycle.LifecycleError("migration failed")
        )
        deployment.apply_runtime = lambda *args: calls.append("rollout")
        deployment.update_comment = lambda *args: calls.append("comment")
        environment = {
            "GITHUB_REPOSITORY": lifecycle.REPOSITORY,
            "GITHUB_WORKFLOW_REF": (
                f"{lifecycle.REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main"
            ),
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_run",
            "PREVIEW_IAP_TESTERS": "user:tester@example.com",
            "PREVIEW_DB_PROVISIONER_URL": (
                "https://preview-provisioner-abc-ue.a.run.app"
            ),
        }
        with patch.dict("os.environ", environment, clear=False):
            with self.assertRaises(lifecycle.LifecycleError):
                deployment.run()
        self.assertEqual(calls, [])

    def test_exactly_one_preview_comment_is_updated_without_duplicate_creation(self):
        deployment = self.deployment()
        deployment.source_engine_image = SOURCE_ENGINE
        deployment.preview_engine_image = PREVIEW_ENGINE
        deployment.frontend_image = PREVIEW_FRONTEND

        class FakeGithub:
            def __init__(self):
                self.calls = []

            def api(self, endpoint, method="GET", data=None):
                self.calls.append((endpoint, method, data))
                if method == "GET":
                    return [{"id": 17, "body": f"{lifecycle.COMMENT_MARKER}\nold"}]
                return {}

        fake = FakeGithub()
        deployment.github = fake
        deployment.update_comment("https://preview.run.app")
        writes = [call for call in fake.calls if call[1] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], "PATCH")
        self.assertIn("## Preview Environment", writes[0][2]["body"])
        self.assertIn(f"**PR head SHA:** `{SHA}`", writes[0][2]["body"])
        self.assertIn("**PR database:** `haunted_halls_web_pr_41`", writes[0][2]["body"])

        fake.api = lambda *args, **kwargs: [
            {"id": 17, "body": lifecycle.COMMENT_MARKER},
            {"id": 18, "body": lifecycle.COMMENT_MARKER},
        ]
        with self.assertRaises(lifecycle.LifecycleError):
            deployment.update_comment("https://preview.run.app")


class WorkflowBoundaryTests(unittest.TestCase):
    def test_privileged_workflow_checks_out_only_its_default_branch(self):
        workflow = (ROOT.parents[1] / ".github/workflows/preview-deploy.yml").read_text()
        deployment_workflow = workflow.split("\n  deploy:\n", 1)[1]
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertNotIn("ref: ${{ github.event.workflow_run.head_sha }}", workflow)
        self.assertNotIn("ref: ${{ github.event.pull_request.head.sha }}", workflow)
        self.assertLess(
            deployment_workflow.index("Validate workflow/artifact provenance"),
            deployment_workflow.index("Authenticate only as the preview deployer"),
        )
        self.assertIn("actions: write", workflow)

    def test_cloud_workflow_has_no_pr_checkout_or_staging_mutation_path(self):
        workflow = (ROOT.parents[1] / ".github/workflows/ci.yml").read_text()
        lifecycle_source = (ROOT / "lifecycle.py").read_text()
        self.assertNotIn("id-token: write", workflow)
        self.assertIn("pull_request.head.sha", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("gcloud run services update", lifecycle_source)
        self.assertNotIn("gcloud run deploy", lifecycle_source)
        self.assertNotIn("gcloud sql", lifecycle_source)
        self.assertNotIn("terraform destroy", lifecycle_source)
        self.assertIn('"copy"', lifecycle_source)


if __name__ == "__main__":
    unittest.main()
