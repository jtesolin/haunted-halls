"""Offline teardown contracts: all destructive/cloud boundaries are mocked."""

import copy
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import lifecycle
from test_lifecycle import INCARNATION, SHA, github_pr


SPEC = importlib.util.spec_from_file_location("preview_teardown", Path(__file__).with_name("teardown.py"))
teardown = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(teardown)

ENV = {
    "GITHUB_REPOSITORY": teardown.REPOSITORY,
    "GITHUB_WORKFLOW_REF": f"{teardown.REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main",
    "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
}
CLOSED_AT = "2026-10-30T19:05:12Z"
CONTEXT = {"number": "56", "head_sha": SHA, "closed_at": CLOSED_AT}


def closed():
    pr = github_pr(number=56)
    pr.update(state="closed", closed_at=CLOSED_AT)
    return pr


def state(iam_separator="/"):
    number, project, region = "56", teardown.PREVIEW_PROJECT, teardown.PREVIEW_REGION
    labels = {
        "app": "haunted-halls", "environment": "preview", "repository": "web",
        "pull_request": number, "incarnation": INCARNATION, "managed_by": "terraform",
    }
    resources = []

    def add(kind, name, values, index=None):
        instance = {"attributes": values}
        if index is not None:
            instance["index_key"] = index
        resources.append({
            "type": kind, "name": name, "mode": "managed", "provider": teardown.PROVIDER,
            "instances": [instance],
        })

    for role, suffix in teardown.ROLES.items():
        secret = f"hh-web-pr-{number}-i-{INCARNATION}-{suffix}"
        add("google_secret_manager_secret", "pr", {
            "project": project, "secret_id": secret,
            "id": f"projects/{project}/secrets/{secret}",
            "labels": {**labels, "secret_generation": "7"},
        }, role)
    for key, (role, runtime) in teardown.GRANTS.items():
        secret = f"projects/{project}/secrets/hh-web-pr-{number}-i-{INCARNATION}-{teardown.ROLES[role]}"
        member = f"serviceAccount:hh-preview-{runtime}@{project}.iam.gserviceaccount.com"
        role_name = "roles/secretmanager.secretAccessor"
        add("google_secret_manager_secret_iam_member", "runtime", {
            "project": project, "secret_id": secret, "member": member, "role": role_name,
            "id": f"{secret}{iam_separator}{role_name}{iam_separator}{member}",
        }, key)
    for kind, name, suffix in (
        ("google_cloud_run_v2_service", "frontend", "frontend"),
        ("google_cloud_run_v2_service", "engine", "engine"),
        ("google_cloud_run_v2_job", "migration", "migrate"),
    ):
        resource_name = f"hh-web-pr-{number}-{suffix}"
        plural = "jobs" if suffix == "migrate" else "services"
        add(kind, name, {
            "project": project, "location": region, "name": resource_name,
            "id": f"projects/{project}/locations/{region}/{plural}/{resource_name}",
            "labels": labels.copy(),
        })
    for key, suffix, member in (
        ("engine_frontend", "engine", f"serviceAccount:hh-preview-frontend@{project}.iam.gserviceaccount.com"),
        ("frontend_iap", "frontend", f"serviceAccount:service-{teardown.PREVIEW_PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"),
    ):
        full_name = f"projects/{project}/locations/{region}/services/hh-web-pr-{number}-{suffix}"
        add("google_cloud_run_v2_service_iam_member", key, {
            "project": project, "location": region, "name": full_name,
            "role": "roles/run.invoker", "member": member,
            "id": f"{full_name}{iam_separator}roles/run.invoker{iam_separator}{member}",
        })
    iap = f"projects/{project}/iap_web/cloud_run-{region}/services/hh-web-pr-{number}-frontend"
    member = "user:tester@example.com"
    add("google_iap_web_cloud_run_service_iam_member", "tester", {
        "project": project, "location": region, "cloud_run_service_name": iap,
        "member": member, "role": "roles/iap.httpsResourceAccessor",
        "id": f"{iap}{iam_separator}roles/iap.httpsResourceAccessor{iam_separator}{member}",
    }, member)
    return {
        "lineage": "test-lineage", "serial": 42, "resources": resources,
        "outputs": {"preview_identity": {"value": {
            "project_id": project, "repository_key": "web", "pr_number": number,
            "pr_incarnation": INCARNATION, "state_bucket": teardown.STATE_BUCKET,
            "state_prefix": f"previews/web-pr-{number}",
            "database_name": f"haunted_halls_web_pr_{number}",
            "frontend_name": f"hh-web-pr-{number}-frontend",
            "engine_name": f"hh-web-pr-{number}-engine",
            "migration_name": f"hh-web-pr-{number}-migrate",
        }}},
    }


def inventory():
    return teardown.validate_state(state(), "56")[1]


def empty_state():
    return {
        "version": 4, "terraform_version": "1.11.4",
        "lineage": "e11b7f1a-a835-f476-a526-d4a43ee9d6a9", "serial": 46,
        "resources": [], "outputs": {},
    }


def plan(items=None):
    items = inventory() if items is None else items
    return {"resource_changes": [{
        "address": address, "mode": "managed",
        "provider_name": "registry.terraform.io/hashicorp/google",
        "change": {"actions": ["delete"], "before": values, "after": None},
    } for address, values in items.items()]}


class EventTests(unittest.TestCase):
    def test_closed_and_merged_pr_are_eligible_but_open_foreign_or_invalid_are_not(self):
        github = Mock()
        for merged in (False, True):
            github.api.return_value = {**closed(), "merged": merged}
            self.assertEqual(teardown.closed_pr(github, "56"), CONTEXT)
        for mutate in (
            lambda pr: pr.update(state="open"),
            lambda pr: pr.update(number=57),
            lambda pr: pr["base"]["repo"].update(full_name="someone/other"),
            lambda pr: pr["base"].update(ref="staging"),
            lambda pr: pr.update(closed_at=None),
        ):
            pr = closed()
            mutate(pr)
            github.api.return_value = pr
            with self.assertRaises(lifecycle.LifecycleError):
                teardown.closed_pr(github, "56")
        for number in ("056", "0", "56;echo unsafe", None, 56):
            with self.subTest(number=number), self.assertRaises(lifecycle.LifecycleError):
                teardown.closed_pr(github, number)

    def test_manual_legacy_pr56_and_automatic_close_share_the_same_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(event=f"{directory}/event", context=f"{directory}/context",
                             github_output=f"{directory}/output")
            github = Mock()
            github.api.return_value = closed()
            for event_name in ("workflow_dispatch", "pull_request_target"):
                event = {
                    "repository": {"full_name": teardown.REPOSITORY},
                    "inputs": {"operation": "teardown", "pull_request_number": "56"},
                    "action": "closed", "pull_request": closed(),
                }
                Path(args.event).write_text(json.dumps(event))
                with patch.dict(os.environ, {**ENV, "GITHUB_EVENT_NAME": event_name}):
                    teardown.prepare(args, github)
                self.assertEqual(json.loads(Path(args.context).read_text()), CONTEXT)
                self.assertIn("pull_request_number=56", Path(args.github_output).read_text())

    def test_stale_closure_or_wrong_workflow_cannot_prepare(self):
        github = Mock()
        github.api.return_value = closed()
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(event=f"{directory}/event", context=f"{directory}/context",
                             github_output=f"{directory}/output")
            event = {"repository": {"full_name": teardown.REPOSITORY},
                     "action": "closed", "pull_request": {**closed(), "closed_at": "old"}}
            Path(args.event).write_text(json.dumps(event))
            with patch.dict(os.environ, {**ENV, "GITHUB_EVENT_NAME": "pull_request_target"}):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "stale"):
                    teardown.prepare(args, github)
            for key, value in (("GITHUB_REF", "refs/heads/feature"),
                               ("GITHUB_REPOSITORY", "someone/fork"),
                               ("GITHUB_EVENT_NAME", "pull_request"),
                               ("GITHUB_WORKFLOW_REF", "untrusted")):
                with patch.dict(os.environ, {**ENV, key: value}):
                    with self.assertRaises(lifecycle.LifecycleError):
                        teardown.trusted_context()

    def test_github_failure_never_enables_teardown(self):
        github = Mock()
        github.api.side_effect = lifecycle.LifecycleError("GitHub API unavailable")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "GitHub API"):
            teardown.closed_pr(github, "56")


class OwnershipTests(unittest.TestCase):
    def test_full_state_and_partial_state_with_identity_are_valid(self):
        incarnation, values = teardown.validate_state(state(), "56")
        self.assertEqual(incarnation, INCARNATION)
        self.assertEqual(len(values), 14)
        partial = state()
        partial["resources"] = partial["resources"][:1]
        self.assertEqual(teardown.validate_state(partial, "56")[0], INCARNATION)
        partial.pop("outputs")
        self.assertEqual(teardown.validate_state(partial, "56")[0], INCARNATION)
        self.assertEqual(teardown.validate_state(empty_state(), "56"), (None, {}))

    def test_empty_state_does_not_require_identity_output_or_positive_serial(self):
        for outputs in ({}, None):
            value = empty_state()
            value["serial"] = 0
            if outputs is None:
                value.pop("outputs")
            with self.subTest(outputs=outputs):
                self.assertEqual(teardown.validate_state(value, "56"), (None, {}))

    def test_malformed_state_structure_is_rejected(self):
        for value in (None, [], {}, {"resources": None}, {"resources": {}}):
            with self.subTest(value=value), self.assertRaises(lifecycle.LifecycleError):
                teardown.validate_state(value, "56")

    def test_allowed_zero_instance_resource_envelopes_are_valid(self):
        value = empty_state()
        value["resources"] = [
            {"type": kind, "name": name, "mode": "managed", "provider": teardown.PROVIDER,
             "instances": []}
            for kind, name in (address.split(".") for address in sorted(teardown.ALLOWED))
        ]
        self.assertEqual(teardown.validate_state(value, "56"), (None, {}))
        partial = state()
        partial["serial"] = 44
        partial["resources"] = [
            resource for resource in partial["resources"]
            if resource["type"].startswith("google_secret")
        ] + copy.deepcopy(value["resources"])
        incarnation, owned = teardown.validate_state(partial, "56")
        self.assertEqual(incarnation, INCARNATION)
        self.assertEqual(len(owned), 8)

    def test_zero_instance_resource_envelopes_cannot_hide_malformed_or_foreign_blocks(self):
        original = {
            "type": "google_secret_manager_secret", "name": "pr", "mode": "managed",
            "provider": teardown.PROVIDER, "instances": [],
        }
        malformed = [None, [], {}]
        for key in original:
            missing = copy.deepcopy(original)
            missing.pop(key)
            malformed.append(missing)
        for key, invalid in (
            ("type", None), ("type", []), ("type", ""), ("type", "google_storage_bucket"),
            ("type", "google_secret_manager_secret.pr"),
            ("name", None), ("name", []), ("name", ""), ("name", "shared"),
            ("name", 'pr["database_url"]'), ("name", "pr.extra"),
            ("mode", "data"), ("mode", None),
            ("provider", 'provider["registry.terraform.io/hashicorp/google"].shared'),
            ("provider", None), ("module", "module.shared"), ("module", ""),
            ("module", None), ("module", []), ("instances", None), ("instances", {}),
        ):
            malformed.append({**original, key: invalid})
        for resource in malformed:
            for nonempty in (False, True):
                value = state() if nonempty else empty_state()
                value["resources"].append(resource)
                with self.subTest(resource=resource, nonempty=nonempty):
                    with self.assertRaises(lifecycle.LifecycleError):
                        teardown.validate_state(value, "56")

    def test_empty_and_nonempty_states_require_lineage_and_integer_serial(self):
        for initial in (empty_state(), state()):
            for key, invalid in (
                ("lineage", None), ("lineage", ""), ("lineage", " \t"),
                ("lineage", 46), ("lineage", []),
                ("serial", None), ("serial", "46"), ("serial", -1),
                ("serial", 46.0), ("serial", True), ("serial", False),
            ):
                value = copy.deepcopy(initial)
                value[key] = invalid
                with self.subTest(empty=not value["resources"], key=key, invalid=invalid):
                    with self.assertRaisesRegex(lifecycle.LifecycleError, "lineage or serial"):
                        teardown.validate_state(value, "56")
            for key in ("lineage", "serial"):
                value = copy.deepcopy(initial)
                value.pop(key)
                with self.subTest(empty=not value["resources"], missing=key):
                    with self.assertRaisesRegex(lifecycle.LifecycleError, "lineage or serial"):
                        teardown.validate_state(value, "56")

    def test_empty_inventory_preserves_identity_output_validation(self):
        value = state()
        value["resources"] = []
        self.assertEqual(teardown.validate_state(value, "56"), (INCARNATION, {}))
        value["outputs"]["preview_identity"]["value"]["database_name"] = "haunted_halls_staging"
        with self.assertRaises(lifecycle.LifecycleError):
            teardown.validate_state(value, "56")

    def test_sanitized_pr56_slash_ids_and_provider_space_ids_validate_for_all_iam_types(self):
        slash_state = state(iam_separator="/")
        space_state = state(iam_separator=" ")
        for value in (slash_state, space_state):
            incarnation, resources = teardown.validate_state(value, "56")
            self.assertEqual(incarnation, INCARNATION)
            self.assertEqual(
                sum("_iam_member." in address for address in resources),
                8,
            )
        slash_ids = {
            resource["type"]: resource["instances"][0]["attributes"]["id"]
            for resource in slash_state["resources"] if "_iam_member" in resource["type"]
        }
        self.assertIn("/roles/secretmanager.secretAccessor/", slash_ids["google_secret_manager_secret_iam_member"])
        self.assertIn("/roles/run.invoker/", slash_ids["google_cloud_run_v2_service_iam_member"])
        self.assertIn("/roles/iap.httpsResourceAccessor/", slash_ids["google_iap_web_cloud_run_service_iam_member"])

    def test_foreign_pr_shared_projects_or_unexpected_resources_are_rejected(self):
        for mutate in (
            lambda value: value["outputs"]["preview_identity"]["value"].update(database_name="haunted_halls_staging"),
            lambda value: value["outputs"]["preview_identity"]["value"].update(database_name="haunted_halls_web_pr_57"),
            lambda value: value["outputs"]["preview_identity"]["value"].update(state_prefix="preview-foundation"),
            lambda value: value["resources"][0]["instances"][0]["attributes"].update(project="haunted-halls-development"),
            lambda value: value["resources"][0]["instances"][0]["attributes"].update(secret_id="hh-preview-openai-api-key"),
            lambda value: value["resources"][0].update(type="google_sql_database_instance"),
            lambda value: value["resources"][0].update(module="module.other"),
            lambda value: value["resources"][0].update(provider='provider["registry.terraform.io/hashicorp/google"].existing'),
            lambda value: value["resources"][0]["instances"][0].update(deposed="old"),
            lambda value: value["resources"][0]["instances"][0]["attributes"]["labels"].update(incarnation="a" * 32),
            lambda value: value["resources"][0]["instances"][0]["attributes"]["labels"].update(pull_request="57"),
            lambda value: value["resources"][0]["instances"][0]["attributes"]["labels"].update(secret_generation="8"),
            lambda value: value["resources"][0]["instances"][0]["attributes"].update(id="projects/other/secrets/foreign"),
            lambda value: value.update(lineage=None),
        ):
            value = state()
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(lifecycle.LifecycleError):
                teardown.validate_state(value, "56")

    def test_each_iam_resource_id_is_checked_not_only_its_display_attributes(self):
        value = state()
        for resource in value["resources"]:
            if "_iam_member" not in resource["type"]:
                continue
            altered = copy.deepcopy(value)
            index = value["resources"].index(resource)
            altered["resources"][index]["instances"][0]["attributes"]["id"] = "projects/shared/foreign"
            with self.subTest(resource=resource["name"]), self.assertRaises(lifecycle.LifecycleError):
                teardown.validate_state(altered, "56")

    def test_destroy_plan_rejects_replacements_updates_foreign_ids_and_shared_resources(self):
        teardown.validate_destroy_plan(plan(), "56", INCARNATION, inventory(), teardown.ALLOWED)
        for mutate in (
            lambda value: value["resource_changes"][0]["change"].update(actions=["delete", "create"]),
            lambda value: value["resource_changes"][0]["change"].update(actions=["update"]),
            lambda value: value["resource_changes"][0].update(address="google_storage_bucket.shared"),
            lambda value: value["resource_changes"][0]["change"]["before"].update(project="production"),
            lambda value: value["resource_changes"][0]["change"]["before"]["labels"].update(incarnation="a" * 32),
            lambda value: value["resource_changes"][0]["change"]["before"]["labels"].update(secret_generation="8"),
            lambda value: value["resource_changes"][0].update(provider_name="untrusted"),
        ):
            value = plan()
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(lifecycle.LifecycleError):
                teardown.validate_destroy_plan(value, "56", INCARNATION, inventory(), teardown.ALLOWED)
        with self.assertRaises(lifecycle.LifecycleError):
            teardown.validate_destroy_plan(plan(), "56", INCARNATION, inventory(), teardown.RUNTIME)

    def test_runtime_plan_can_leave_owned_secrets_unchanged(self):
        value = plan()
        for change in value["resource_changes"]:
            if change["address"].split("[", 1)[0] not in teardown.RUNTIME:
                change["change"].update(actions=["no-op"], after=copy.deepcopy(change["change"]["before"]))
        teardown.validate_destroy_plan(value, "56", INCARNATION, inventory(), teardown.RUNTIME)

    def test_runtime_destroy_plan_accepts_only_owned_dependency_closure(self):
        teardown.validate_destroy_plan(plan(), "56", INCARNATION, inventory(), teardown.ALLOWED)
        with self.assertRaises(lifecycle.LifecycleError):
            teardown.validate_destroy_plan(plan(), "56", INCARNATION, inventory(), teardown.RUNTIME)


class StateDigestTests(unittest.TestCase):
    def snapshot(self):
        value = state()
        value["check_results"] = [
            {"object_kind": "var", "config_addr": "var.pull_request_number", "status": "pass",
             "objects": [{"object_addr": "var.pull_request_number", "status": "pass"}]},
            {"object_kind": "resource", "config_addr": "google_secret_manager_secret.pr",
             "status": "pass", "objects": [
                 {"object_addr": 'google_secret_manager_secret.pr["nextauth"]', "status": "pass"},
                 {"object_addr": 'google_secret_manager_secret.pr["database_url"]', "status": "pass"},
             ]},
        ]
        return value

    def test_check_result_and_object_order_does_not_change_digest_or_mutate_snapshot(self):
        original = self.snapshot()
        reordered = copy.deepcopy(original)
        reordered["check_results"][1]["objects"].reverse()
        reordered["check_results"].reverse()
        before = copy.deepcopy(reordered)
        self.assertNotEqual(original, reordered)
        self.assertEqual(teardown.state_digest(original), teardown.state_digest(reordered))
        self.assertEqual(reordered, before)

    def test_guard_accepts_only_order_changes_and_rejects_all_semantic_changes(self):
        original = self.snapshot()
        instance = teardown.PreviewTeardown(CONTEXT, Mock())
        instance.state = original
        reordered = copy.deepcopy(original)
        reordered["check_results"].reverse()
        with patch.object(instance, "revalidate"), patch.object(instance, "read_state", return_value=reordered):
            instance.guard()
        for mutate in (
            lambda s: s.update(serial=43),
            lambda s: s.update(lineage="other-lineage"),
            lambda s: s["outputs"]["preview_identity"]["value"].update(pr_incarnation="e" * 32),
            lambda s: s["resources"][0]["instances"][0]["attributes"].update(id="foreign"),
            lambda s: s["resources"][0]["instances"][0]["attributes"]["labels"].update(secret_generation="8"),
            lambda s: s["resources"].pop(),
            lambda s: s["resources"].reverse(),
            lambda s: s["check_results"][0].update(status="fail"),
            lambda s: s["check_results"][0]["objects"][0].update(status="fail"),
            lambda s: s["check_results"][0]["objects"][0].update(object_addr="var.other"),
            lambda s: s["check_results"][0]["objects"][0].update(failure_messages=["failed"]),
            lambda s: s["check_results"].pop(),
            lambda s: s["check_results"].append(copy.deepcopy(s["check_results"][0])),
            lambda s: s["check_results"][1]["objects"].pop(),
            lambda s: s.pop("check_results"),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            with (
                self.subTest(mutate=mutate),
                patch.object(instance, "revalidate"),
                patch.object(instance, "read_state", return_value=changed),
                self.assertRaisesRegex(lifecycle.LifecycleError, "Terraform state changed"),
            ):
                instance.guard()

    def test_real_terraform_local_state_pulls_have_stable_digest(self):
        terraform = shutil.which("terraform")
        if terraform is None:
            self.skipTest("Terraform is required for the local state serialization regression.")
        value = {
            "version": 4, "terraform_version": "1.11.4",
            "serial": 42, "lineage": "test-lineage", "outputs": {}, "resources": [],
            "check_results": [
                {"object_kind": "var", "config_addr": f"var.input_{n}", "status": "pass",
                 "objects": [{"object_addr": f"var.input_{n}", "status": "pass"}]}
                for n in range(13)
            ],
        }
        with tempfile.TemporaryDirectory(prefix="teardown-state-pull-") as directory:
            path = Path(directory) / "terraform.tfstate"
            original = json.dumps(value).encode()
            path.write_bytes(original)
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith(("TF_", "GOOGLE_", "CLOUDSDK_"))
            }
            environment["CHECKPOINT_DISABLE"] = "1"
            snapshots = []
            for _ in range(5):
                result = subprocess.run(
                    [terraform, f"-chdir={directory}", "state", "pull"],
                    env=environment, capture_output=True, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                snapshots.append(json.loads(result.stdout))
            self.assertEqual(len({teardown.state_digest(s) for s in snapshots}), 1)
            self.assertTrue(all(s["serial"] == 42 and s["lineage"] == "test-lineage" for s in snapshots))
            self.assertEqual(path.read_bytes(), original)


class TerraformDependencyGraphTests(unittest.TestCase):
    def dependency_graph(self, terraform, source):
        provider_cache = source / ".terraform" / "providers"
        if not any(path.is_file() for path in provider_cache.glob(
            "registry.terraform.io/hashicorp/google/*/*/terraform-provider-google*"
        )):
            self.skipTest(
                "Offline graph test requires cached Google provider binaries; "
                "run terraform -chdir=infra/terraform/preview-pr init -backend=false "
                "explicitly before running this test."
            )
        with tempfile.TemporaryDirectory(prefix="preview-destroy-graph-") as directory:
            root = Path(directory)
            for path in source.glob("*.tf"):
                contents = path.read_text(encoding="utf-8")
                if path.name == "versions.tf":
                    contents, replacements = re.subn(
                        r'\n  backend "gcs" \{.*?\n  \}\n', "\n", contents, count=1, flags=re.S,
                    )
                    self.assertEqual(replacements, 1, "Expected only the configured GCS backend.")
                (root / path.name).write_text(contents, encoding="utf-8")
            shutil.copyfile(source / ".terraform.lock.hcl", root / ".terraform.lock.hcl")

            environment = os.environ.copy()
            environment["TF_DATA_DIR"] = str(root / ".terraform-data")
            environment["TF_IN_AUTOMATION"] = "1"
            configuration = root / "offline.tfrc"
            configuration.write_text(
                "provider_installation {\n  filesystem_mirror {\n"
                f"    path = {json.dumps(str(provider_cache))}\n"
                "  }\n}\n",
                encoding="utf-8",
            )
            environment["TF_CLI_CONFIG_FILE"] = str(configuration)
            environment["CHECKPOINT_DISABLE"] = "1"
            environment.pop("TF_PLUGIN_CACHE_DIR", None)
            for credential in (
                "GOOGLE_APPLICATION_CREDENTIALS",
                "GOOGLE_BACKEND_CREDENTIALS",
                "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
            ):
                environment.pop(credential, None)

            initialized = subprocess.run(
                [terraform, "init", "-input=false", "-lockfile=readonly"],
                cwd=root, env=environment, capture_output=True, text=True, timeout=300,
                check=False,
            )
            self.assertEqual(
                initialized.returncode, 0,
                "Offline provider initialization failed. Populate the locked provider for this "
                "platform with terraform -chdir=infra/terraform/preview-pr init -backend=false "
                "before retrying; registry fallback is disabled.\n"
                + initialized.stdout + initialized.stderr,
            )
            result = subprocess.run(
                [terraform, "graph", "-type=plan"],
                cwd=root, env=environment, capture_output=True, text=True, timeout=120,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_missing_or_empty_provider_cache_skips_without_starting_terraform(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(subprocess, "run") as run:
            source = Path(directory)
            for empty_cache in (False, True):
                if empty_cache:
                    (source / ".terraform/providers").mkdir(parents=True)
                with self.subTest(empty_cache=empty_cache), self.assertRaisesRegex(
                    unittest.SkipTest, "init -backend=false",
                ):
                    self.dependency_graph("terraform", source)
            run.assert_not_called()

    def test_incomplete_cache_fails_offline_with_actionable_prerequisite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            provider = source / ".terraform/providers/registry.terraform.io/hashicorp/google/0.0.0/other_platform"
            provider.mkdir(parents=True)
            (provider / "terraform-provider-google").touch()
            (source / ".terraform.lock.hcl").touch()

            def initialize(command, **kwargs):
                configuration = Path(kwargs["env"]["TF_CLI_CONFIG_FILE"]).read_text()
                self.assertIn("filesystem_mirror", configuration)
                self.assertIn(json.dumps(str(source / ".terraform/providers")), configuration)
                self.assertNotIn("direct", configuration)
                self.assertNotIn("TF_PLUGIN_CACHE_DIR", kwargs["env"])
                self.assertEqual(kwargs["env"]["CHECKPOINT_DISABLE"], "1")
                self.assertIn("-lockfile=readonly", command)
                return subprocess.CompletedProcess(command, 1, "", "Provider unavailable in local mirror")

            with patch.object(subprocess, "run", side_effect=initialize) as run:
                with self.assertRaisesRegex(AssertionError, "registry fallback is disabled"):
                    self.dependency_graph("terraform", source)
            self.assertEqual(run.call_count, 1)

    def test_runtime_target_closure_includes_secret_iam_and_containers(self):
        terraform = shutil.which("terraform")
        if terraform is None:
            self.skipTest("Terraform is required to inspect the configured dependency graph.")
        source = Path(__file__).resolve().parents[2] / "infra/terraform/preview-pr"
        graph = self.dependency_graph(terraform, source)

        edges: dict[str, set[str]] = {}
        for line in graph.splitlines():
            match = re.fullmatch(r'\s*"(\[root\] [^"]+)" -> "(\[root\] [^"]+)"', line)
            if match is None:
                continue
            source_node, dependency_node = (
                node.removeprefix("[root] ").split(" (", 1)[0]
                for node in match.groups()
            )
            edges.setdefault(source_node, set()).add(dependency_node)

        closure = set(teardown.RUNTIME)
        pending = list(closure)
        while pending:
            for dependency in edges.get(pending.pop(), set()) & teardown.ALLOWED:
                if dependency not in closure:
                    closure.add(dependency)
                    pending.append(dependency)
        self.assertEqual(closure, teardown.ALLOWED)


class ExecutionTests(unittest.TestCase):
    def make(self):
        github = Mock()
        github.api.return_value = closed()
        return teardown.PreviewTeardown(CONTEXT, github)

    def test_reopened_or_changed_state_fails_before_deletion(self):
        instance = self.make()
        instance.state = state()
        with patch.dict(os.environ, ENV), patch.object(instance, "read_state", return_value=state()):
            instance.guard()
            instance.github.api.return_value = {**closed(), "state": "open"}
            with self.assertRaisesRegex(lifecycle.LifecycleError, "reopened"):
                instance.guard()
            instance.github.api.return_value = closed()
            with patch.object(instance, "read_state", return_value={**state(), "serial": 43}):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "state changed"):
                    instance.guard()

    def test_saved_plan_is_validated_and_state_rechecked_immediately_before_apply(self):
        instance = self.make()
        instance.state = state()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            instance.directory = Path(directory)
            with (
                patch.object(instance, "guard", side_effect=lambda: calls.append("guard")),
                patch.object(instance, "read_state", return_value={
                    "resources": [], "lineage": "test-lineage", "serial": 43,
                }),
                patch.object(
                    teardown, "run_terraform_plan",
                    side_effect=lambda *a, **k: calls.append("plan"),
                ) as run_plan,
                patch.object(teardown.Commands, "json", return_value=plan()),
                patch.object(teardown.Commands, "run", side_effect=lambda *a, **k: calls.append(a[0])),
            ):
                instance.destroy(runtime_only=True)
            self.assertEqual(calls[:3], ["guard", "plan", "guard"])
            self.assertEqual(calls[3][2], "apply")
            self.assertEqual(calls[3][-1], f"{directory}/destroy.tfplan")
            arguments = run_plan.call_args.args[0]
            self.assertEqual(
                [argument for argument in arguments if argument.startswith("-target=")],
                [f"-target={target}" for target in sorted(teardown.RUNTIME)],
            )
            self.assertEqual(run_plan.call_args.kwargs["targets"], teardown.ALLOWED)

    def test_runtime_destroy_accepts_partial_state_with_only_secret_resources_remaining(self):
        instance = self.make()
        original = state()
        instance.state = original
        runtime_inventory = {
            address: attributes for address, attributes in inventory().items()
            if address.split("[", 1)[0] in teardown.RUNTIME
        }
        runtime_plan = plan(runtime_inventory)
        remaining_state = copy.deepcopy(original)
        remaining_state["serial"] = original["serial"] + 1
        remaining_state["resources"] = [
            resource for resource in remaining_state["resources"]
            if resource["type"] in {
                "google_secret_manager_secret",
                "google_secret_manager_secret_iam_member",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            instance.directory = Path(directory)
            with (
                patch.object(instance, "guard"),
                patch.object(instance, "read_state", return_value=remaining_state),
                patch.object(teardown, "run_terraform_plan"),
                patch.object(teardown.Commands, "json", return_value=runtime_plan),
                patch.object(teardown.Commands, "run"),
            ):
                instance.destroy(runtime_only=True)
        _, remaining = teardown.validate_state(instance.state, "56")
        self.assertTrue(remaining)
        self.assertTrue(all(
            address.split("[", 1)[0] not in teardown.RUNTIME
            for address in remaining
        ))

    def test_final_destroy_rejects_expected_secrets_that_remain_after_apply(self):
        instance = self.make()
        original = state()
        remaining_state = copy.deepcopy(original)
        remaining_state["serial"] = original["serial"] + 1
        remaining_state["resources"] = [
            resource for resource in remaining_state["resources"]
            if resource["type"] in {
                "google_secret_manager_secret",
                "google_secret_manager_secret_iam_member",
            }
        ]
        secret_inventory = {
            address: attributes for address, attributes in inventory().items()
            if address.split("[", 1)[0] in {
                "google_secret_manager_secret.pr",
                "google_secret_manager_secret_iam_member.runtime",
            }
        }
        instance.state = remaining_state
        with tempfile.TemporaryDirectory() as directory:
            instance.directory = Path(directory)
            with (
                patch.object(instance, "guard"),
                patch.object(instance, "read_state", return_value=remaining_state),
                patch.object(teardown, "run_terraform_plan"),
                patch.object(teardown.Commands, "json", return_value=plan(secret_inventory)),
                patch.object(teardown.Commands, "run"),
            ):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "cleanup phase"):
                    instance.destroy(runtime_only=False)

    def test_new_incarnation_after_apply_cannot_be_used_for_database_deletion(self):
        instance = self.make()
        instance.state = state()
        newer = json.loads(json.dumps(state()).replace(INCARNATION, "e" * 32))
        newer["serial"] = 44
        with tempfile.TemporaryDirectory() as directory:
            instance.directory = Path(directory)
            with (
                patch.object(instance, "guard"),
                patch.object(instance, "read_state", return_value=newer),
                patch.object(teardown, "run_terraform_plan"),
                patch.object(teardown.Commands, "json", return_value=plan()),
                patch.object(teardown.Commands, "run"),
            ):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "incarnation changed"):
                    instance.destroy(runtime_only=False)

    def test_bad_plan_or_late_reopen_never_applies(self):
        for bad_plan, guard_error in ((True, False), (False, True)):
            instance = self.make()
            instance.state = state()
            with tempfile.TemporaryDirectory() as directory:
                instance.directory = Path(directory)
                value = plan()
                if bad_plan:
                    value["resource_changes"][0]["change"]["actions"] = ["update"]
                with (
                    patch.object(instance, "guard", side_effect=[None, lifecycle.LifecycleError("reopened")] if guard_error else None),
                    patch.object(teardown, "run_terraform_plan"),
                    patch.object(teardown.Commands, "json", return_value=value),
                    patch.object(teardown.Commands, "run") as run,
                ):
                    with self.assertRaises(lifecycle.LifecycleError):
                        instance.destroy(runtime_only=False)
                    run.assert_not_called()

    def run_mocked(self, value=None, database_error=None, database_result=None):
        instance = self.make()
        calls = []
        value = state() if value is None else value
        def destroy(*, runtime_only):
            calls.append("runtime" if runtime_only else "secrets")
        def database(*args):
            calls.append("database")
            if database_error:
                raise lifecycle.LifecycleError(database_error)
            return database_result or {
                "operation": "drop", "database": "haunted_halls_web_pr_56", "dropped": False,
            }
        with (
            patch.object(instance, "revalidate"), patch.object(instance, "check_secret_workflow"),
            patch.object(instance, "initialize"), patch.object(instance, "read_state", return_value=value),
            patch.object(instance, "guard"),
            patch.object(instance, "destroy", side_effect=destroy),
            patch.object(instance, "verify_runtime_absent", side_effect=lambda: calls.append("verify-runtime")),
            patch.object(instance, "verify_runtime_iam_absent", side_effect=lambda *a: calls.append("verify-runtime-iam")),
            patch.object(instance, "verify_untracked_secrets_absent",
                         side_effect=lambda: calls.append("verify-untracked")),
            patch.object(instance, "verify_secrets_absent", side_effect=lambda x: calls.append("verify-secrets")),
            patch.object(instance, "cleanup_tags", side_effect=lambda: calls.append("tags")),
            patch.object(teardown, "request_database", side_effect=database),
        ):
            try:
                instance.run()
            except lifecycle.LifecycleError as error:
                return instance, calls, str(error)
        return instance, calls, None

    def test_runtime_database_secrets_and_tags_are_removed_in_order(self):
        instance, calls, error = self.run_mocked()
        self.assertIsNone(error)
        self.assertEqual(calls, [
            "runtime", "verify-runtime", "verify-runtime-iam", "database",
            "secrets", "verify-secrets", "tags",
        ])
        self.assertEqual(instance.status, "Removed")

    def test_runtime_iam_check_accepts_real_indexed_pr_state(self):
        instance = self.make()
        owned = inventory()
        self.assertTrue(any(
            address.startswith("google_secret_manager_secret_iam_member.runtime[")
            for address in owned
        ))
        self.assertTrue(any(
            address.startswith("google_iap_web_cloud_run_service_iam_member.tester[")
            for address in owned
        ))
        absent = {
            "hh-web-pr-56-frontend",
            "hh-web-pr-56-engine",
        }
        with (
            patch.object(instance, "verify_cloud_run_iam_absent") as cloud_run,
            patch.object(instance, "verify_iap_iam_absent") as iap,
        ):
            instance.verify_runtime_iam_absent(owned, absent)
        self.assertEqual(cloud_run.call_count, 2)
        iap.assert_called_once_with(True)

    def test_already_removed_is_noop_without_database_adoption(self):
        value = empty_state()
        original = copy.deepcopy(value)
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                instance, calls, error = self.run_mocked(value)
                self.assertIsNone(error)
                self.assertEqual(calls, ["verify-runtime", "verify-runtime-iam", "verify-untracked", "tags"])
                self.assertEqual(instance.status, "No-op: no tracked preview resources")
                self.assertEqual(value, original)

    def test_incomplete_empty_state_never_reaches_success_or_cleanup(self):
        for value in (
            {"resources": []},
            {**empty_state(), "lineage": ""},
            {**empty_state(), "serial": True},
            {**empty_state(), "serial": -1},
            {"resources": None},
        ):
            with self.subTest(value=value):
                instance, calls, error = self.run_mocked(value)
                self.assertIsNotNone(error)
                self.assertEqual(calls, [])
                self.assertEqual(instance.status, "Cleanup incomplete")

    def test_zero_instance_envelopes_only_allow_owned_resource_noops(self):
        valid = empty_state()
        valid["resources"] = [{
            "type": "google_secret_manager_secret", "name": "pr", "mode": "managed",
            "provider": teardown.PROVIDER, "instances": [],
        }]
        instance, calls, error = self.run_mocked(valid)
        self.assertIsNone(error)
        self.assertEqual(instance.status, "No-op: no tracked preview resources")
        self.assertEqual(calls, ["verify-runtime", "verify-runtime-iam", "verify-untracked", "tags"])
        for fields in (
            {"type": "google_storage_bucket", "name": "shared"},
            {"name": 'pr["foreign"]'},
            {"module": None},
        ):
            value = copy.deepcopy(valid)
            value["resources"][0].update(fields)
            with self.subTest(fields=fields):
                instance, calls, error = self.run_mocked(value)
                self.assertIsNotNone(error)
                self.assertEqual(instance.status, "Cleanup incomplete")
                self.assertEqual(calls, [])

    def test_database_owner_failure_reports_dependency_cleanup_partial_state(self):
        instance, calls, error = self.run_mocked(database_error="Database owner mismatch")
        self.assertEqual(calls, ["runtime", "verify-runtime", "verify-runtime-iam", "database"])
        self.assertIn("owner mismatch", error)
        self.assertEqual(instance.status, "Cleanup incomplete")
        self.assertIn("database cleanup pending", instance.progress)

    def test_foreign_database_response_does_not_allow_secret_cleanup(self):
        instance, calls, error = self.run_mocked(database_result={
            "operation": "drop", "database": "haunted_halls_web_pr_57", "dropped": True,
        })
        self.assertEqual(calls, ["runtime", "verify-runtime", "verify-runtime-iam", "database"])
        self.assertIn("not verified", error)
        self.assertEqual(instance.status, "Cleanup incomplete")

    def test_partial_retry_uses_remaining_database_secret_and_grant_as_evidence(self):
        value = state()
        value.pop("outputs")
        value["resources"] = [item for item in value["resources"] if item["type"].startswith("google_secret")]
        instance, calls, error = self.run_mocked(value)
        self.assertIsNone(error)
        self.assertIn("database", calls)
        self.assertEqual(instance.status, "Removed")

    def test_serial44_retry_validates_reduced_plans_and_preserves_cleanup_order(self):
        for dependency_cleanup in (False, True):
            with self.subTest(dependency_cleanup=dependency_cleanup):
                instance = self.make()
                partial = state()
                partial["serial"] = 44
                partial["resources"] = [
                    item for item in partial["resources"]
                    if item["type"].startswith("google_secret")
                ]
                incarnation, remaining = teardown.validate_state(partial, "56")
                self.assertEqual(len(remaining), 8)
                self.assertEqual(incarnation, INCARNATION)
                current = copy.deepcopy(partial)
                calls = []
                saved_plans = []

                def saved_plan(*args, **kwargs):
                    runtime = any(arg.startswith("-target=") for arg in args[0])
                    calls.append("runtime-plan" if runtime else "secret-plan")
                    expected = teardown.validate_state(current, "56")[1]
                    result = plan(expected)
                    if runtime and not dependency_cleanup:
                        for item in result["resource_changes"]:
                            item["change"].update(
                                actions=["no-op"], after=item["change"]["before"],
                            )
                    saved_plans.append(result)

                def apply(command, **kwargs):
                    self.assertEqual(command[2], "apply")
                    calls.append("apply")
                    if dependency_cleanup or calls.count("apply") == 2:
                        current["resources"] = []
                        current["serial"] += 1
                    return b""

                def database(number, operation, guard):
                    calls.append("database")
                    self.assertEqual((number, operation), ("56", "drop"))
                    self.assertIn("verify-iam", calls)
                    guard()
                    return {"operation": "drop", "database": "haunted_halls_web_pr_56",
                            "dropped": True}

                with tempfile.TemporaryDirectory() as directory:
                    instance.directory = Path(directory)
                    with (
                        patch.dict(os.environ, ENV),
                        patch.object(instance, "initialize"),
                        patch.object(instance, "check_secret_workflow"),
                        patch.object(instance, "read_state",
                                     side_effect=lambda: copy.deepcopy(current)),
                        patch.object(teardown, "run_terraform_plan", side_effect=saved_plan) as planning,
                        patch.object(teardown.Commands, "json",
                                     side_effect=lambda *a, **k: saved_plans.pop(0)),
                        patch.object(teardown.Commands, "run", side_effect=apply),
                        patch.object(instance, "verify_runtime_absent", return_value={
                            "hh-web-pr-56-engine", "hh-web-pr-56-frontend",
                        }),
                        patch.object(instance, "verify_cloud_run_iam_absent",
                                     side_effect=lambda *a: calls.append("verify-iam")),
                        patch.object(instance, "verify_iap_iam_absent"),
                        patch.object(teardown, "request_database", side_effect=database),
                        patch.object(instance, "verify_secrets_absent",
                                     side_effect=lambda *a: calls.append("verify-secrets")),
                        patch.object(instance, "cleanup_tags",
                                     side_effect=lambda: calls.append("tags")),
                    ):
                        instance.run()
                self.assertEqual(instance.status, "Removed")
                self.assertEqual(teardown.validate_state(instance.state, "56")[1], {})
                self.assertLess(calls.index("apply"), calls.index("database"))
                self.assertLess(calls.index("database"), calls.index("verify-secrets"))
                self.assertEqual(calls[-1], "tags")
                self.assertEqual(planning.call_count, 1 if dependency_cleanup else 2)

    def test_partial_retry_rejects_foreign_inventory_and_genuine_state_changes(self):
        partial = state()
        partial["serial"] = 44
        partial["resources"] = [
            item for item in partial["resources"]
            if item["type"].startswith("google_secret")
        ]
        foreign = copy.deepcopy(partial)
        foreign["resources"][0]["instances"][0]["attributes"]["project"] = "production"
        _, calls, error = self.run_mocked(foreign)
        self.assertIn("Unexpected Terraform address or project", error)
        self.assertEqual(calls, [])
        instance = self.make()
        instance.state = partial
        for mutate in (
            lambda value: value.update(serial=45),
            lambda value: value.update(lineage="foreign-lineage"),
            lambda value: value["resources"][0]["instances"][0]["attributes"].update(id="foreign"),
        ):
            changed = copy.deepcopy(partial)
            mutate(changed)
            with (
                self.subTest(mutate=mutate),
                patch.dict(os.environ, ENV),
                patch.object(instance, "read_state", return_value=changed),
                self.assertRaisesRegex(lifecycle.LifecycleError, "Terraform state changed"),
            ):
                instance.guard()

    def test_missing_database_evidence_removes_only_runtime_and_requires_manual_cleanup(self):
        value = state()
        value.pop("outputs")
        value["resources"] = [item for item in value["resources"] if item["type"].startswith("google_cloud_run")]
        instance, calls, error = self.run_mocked(value)
        self.assertEqual(calls, ["runtime", "verify-runtime", "verify-runtime-iam"])
        self.assertIn("manual cleanup required", error)

    def test_permission_error_is_not_treated_as_missing_secret(self):
        instance = self.make()
        for code, error, success in ((1, b"NOT_FOUND: missing", True),
                                     (1, b"PERMISSION_DENIED NOT_FOUND 403", False),
                                     (1, b"connection unavailable", False),
                                     (0, b"", False)):
            with patch.object(teardown.subprocess, "run", return_value=subprocess.CompletedProcess([], code, b"", error)):
                if success:
                    instance.verify_secrets_absent(["owned"])
                else:
                    with self.assertRaises(lifecycle.LifecycleError):
                        instance.verify_secrets_absent(["owned"])

    def test_secret_preparation_for_this_pr_blocks_cleanup_but_other_pr_does_not(self):
        instance = self.make()
        instance.github.api.return_value = {"workflow_runs": [{"display_title": "Preview prepare PR-56-abc"}]}
        with self.assertRaisesRegex(lifecycle.LifecycleError, "still active"):
            instance.check_secret_workflow()
        instance.github.api.return_value = {"workflow_runs": [{"display_title": "Preview prepare PR-57-abc"}]}
        instance.check_secret_workflow()

    def test_tag_cleanup_never_removes_other_pr_tags_or_shared_image_digests(self):
        instance = self.make()
        prefix = f"projects/{teardown.PREVIEW_PROJECT}/locations/us-east1/repositories/haunted-halls-preview/packages/frontend/tags/"
        own = f"pr-56-{SHA}-run-123-attempt-1"
        with (
            patch.object(instance, "guard"),
            patch.object(teardown.Commands, "json", side_effect=[
                [{"tag": prefix + own}, {"tag": prefix + f"pr-57-{SHA}-run-123-attempt-1"},
                 {"tag": prefix + "shared"}],
                [{"tag": prefix + "shared"}],
            ]),
            patch.object(teardown.Commands, "run") as run,
        ):
            instance.cleanup_tags()
        self.assertEqual(run.call_count, 1)
        self.assertIn(f"{teardown.PREVIEW_FRONTEND_REPOSITORY}:{own}", run.call_args.args[0])

    def test_incorrect_backend_or_state_read_failure_never_appears_absent(self):
        instance = self.make()
        with tempfile.TemporaryDirectory() as directory:
            instance.directory = Path(directory)
            metadata = {
                "backend": {"type": "gcs", "config": {
                    "bucket": teardown.STATE_BUCKET, "prefix": "previews/web-pr-57",
                    "impersonate_service_account": teardown.DEPLOYER,
                }},
            }
            (instance.directory / "terraform.tfstate").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(lifecycle.LifecycleError, "backend identity"):
                instance.check_backend()
        with patch.object(instance, "check_backend"), patch.object(
            teardown.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 1, b"", b"PERMISSION_DENIED"),
        ), patch.object(
            instance, "verify_state_absent",
            side_effect=lifecycle.LifecycleError("Cannot read authoritative PR state"),
        ):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "authoritative PR state"):
                instance.read_state()

    def test_valid_existing_empty_state_is_read_without_manufacturing_identity(self):
        instance = self.make()
        value = empty_state()
        with patch.object(instance, "check_backend"), patch.object(
            teardown.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b""),
        ):
            self.assertEqual(instance.read_state(), value)

    def test_missing_blank_invalid_or_failed_state_reads_never_reach_success(self):
        instance = self.make()
        for result in (
            subprocess.CompletedProcess([], 1, b"No state file was found!", b""),
            subprocess.CompletedProcess([], 1, b"", b"No state file was found!"),
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, b" \n\t", b""),
            subprocess.CompletedProcess([], 0, b"not-json", b""),
            subprocess.CompletedProcess([], 0, b"\xff", b""),
            subprocess.CompletedProcess([], 0, b"null", b""),
            subprocess.CompletedProcess([], 0, b"[]", b""),
            subprocess.CompletedProcess([], 0, b'{"resources":[]}', b""),
            subprocess.CompletedProcess([], 1, b"", b"Permission denied (403)"),
            subprocess.CompletedProcess([], 1, b"No state file was found!", b"PERMISSION_DENIED"),
            subprocess.CompletedProcess([], 1, b"", b"network unavailable"),
            subprocess.CompletedProcess([], 2, b"", b"ambiguous failure"),
            subprocess.CompletedProcess([], 1, json.dumps(empty_state()).encode(), b"failed"),
        ):
            with (
                self.subTest(result=result),
                patch.object(instance, "revalidate"),
                patch.object(instance, "check_secret_workflow"),
                patch.object(instance, "initialize"),
                patch.object(instance, "check_backend"),
                patch.object(instance, "verify_state_absent",
                             side_effect=lifecycle.LifecycleError("State absence unverified")),
                patch.object(teardown.subprocess, "run", return_value=result),
                patch.object(instance, "destroy") as destroy,
                patch.object(teardown, "request_database") as database,
                patch.object(instance, "verify_runtime_absent") as runtime,
                patch.object(instance, "cleanup_tags") as tags,
            ):
                with self.assertRaises(lifecycle.LifecycleError):
                    instance.run()
                self.assertEqual(instance.status, "Cleanup incomplete")
                destroy.assert_not_called()
                database.assert_not_called()
                runtime.assert_not_called()
                tags.assert_not_called()

    def test_failed_pull_is_absent_only_after_authoritative_bucket_check(self):
        instance = self.make()
        with (
            patch.object(instance, "check_backend"),
            patch.object(teardown.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, b"", b"No state file was found!",
            )),
            patch.object(instance, "verify_state_absent") as verify,
        ):
            self.assertIsNone(instance.read_state())
        verify.assert_called_once_with()

    def test_state_absence_requires_successful_empty_exact_prefix_listing(self):
        instance = self.make()
        for listing, success in (
            ({"kind": "storage#objects"}, True),
            ({"kind": "storage#objects", "items": []}, True),
            ({"kind": "storage#objects", "items": [{"name": "state"}]}, False),
            ({"kind": "storage#objects", "items": None}, False),
            ({"kind": "storage#objects", "nextPageToken": "more"}, False),
            ({"error": {"code": 403}}, False),
            ({}, False),
        ):
            response = io.BytesIO(json.dumps(listing).encode())
            response.status = 200
            with (
                self.subTest(listing=listing),
                patch.object(teardown.Commands, "run", return_value=b"access-token"),
                patch.object(teardown.urllib.request, "urlopen", return_value=response) as read,
            ):
                if success:
                    instance.verify_state_absent()
                else:
                    with self.assertRaises(lifecycle.LifecycleError):
                        instance.verify_state_absent()
                self.assertIn(
                    "prefix=previews%2Fweb-pr-56%2Fdefault.tfstate",
                    read.call_args.args[0].full_url,
                )
        for code in (401, 403, 404, 500):
            with (
                self.subTest(code=code),
                patch.object(teardown.Commands, "run", return_value=b"access-token"),
                patch.object(teardown.urllib.request, "urlopen", side_effect=(
                    teardown.urllib.error.HTTPError("https://storage.googleapis.com/fixed",
                                                   code, "failure", {}, io.BytesIO())
                )),
                self.assertRaises(lifecycle.LifecycleError),
            ):
                instance.verify_state_absent()

    def test_never_deployed_closed_pr_is_verified_noop_without_mutation(self):
        instance = self.make()
        with (
            patch.object(instance, "revalidate"),
            patch.object(instance, "check_secret_workflow"),
            patch.object(instance, "initialize"),
            patch.object(instance, "read_state", return_value=None),
            patch.object(instance, "verify_runtime_absent", return_value=set()),
            patch.object(instance, "verify_runtime_iam_absent") as iam,
            patch.object(instance, "verify_state_absent") as state_absence,
            patch.object(teardown.Commands, "json", return_value=[]) as inventories,
            patch.object(instance, "destroy") as destroy,
            patch.object(instance, "cleanup_tags") as tags,
            patch.object(teardown, "request_database") as database,
        ):
            instance.run()
        self.assertEqual(instance.status, "No-op: no tracked preview resources")
        self.assertEqual(inventories.call_count, 2)
        iam.assert_called_once_with({}, set())
        state_absence.assert_called_once_with()
        destroy.assert_not_called()
        tags.assert_not_called()
        database.assert_not_called()

    def test_secret_listing_permission_failure_blocks_both_noop_paths_without_mutation(self):
        for value in (None, empty_state()):
            instance = self.make()
            with (
                self.subTest(state=value),
                patch.object(instance, "revalidate"),
                patch.object(instance, "check_secret_workflow"),
                patch.object(instance, "initialize"),
                patch.object(instance, "read_state", return_value=value),
                patch.object(instance, "verify_runtime_absent", return_value=set()),
                patch.object(instance, "verify_runtime_iam_absent"),
                patch.object(teardown.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 1, b"", b"PERMISSION_DENIED: secretmanager.secrets.list private-details",
                )) as command,
                patch.object(instance, "destroy") as destroy,
                patch.object(instance, "cleanup_tags") as tags,
                patch.object(teardown, "request_database") as database,
                self.assertRaises(lifecycle.LifecycleError) as error,
            ):
                instance.run()
            message = str(error.exception)
            self.assertIn("secretmanager.secrets.list", message)
            self.assertIn("No-op teardown is blocked", message)
            self.assertIn("explicit approval", message)
            self.assertNotIn("private-details", message)
            self.assertEqual(instance.status, "Cleanup incomplete")
            command.assert_called_once()
            self.assertEqual(command.call_args.args[0][:3], ["gcloud", "secrets", "list"])
            destroy.assert_not_called()
            tags.assert_not_called()
            database.assert_not_called()

    def test_retained_empty_state_still_retries_owned_tag_cleanup(self):
        instance = self.make()
        tag_prefix = (
            f"projects/{teardown.PREVIEW_PROJECT}/locations/{teardown.PREVIEW_REGION}"
            "/repositories/haunted-halls-preview/packages/frontend/tags/"
        )
        tag = f"pr-56-{SHA}-run-123-attempt-1"
        with (
            patch.object(instance, "revalidate"),
            patch.object(instance, "check_secret_workflow"),
            patch.object(instance, "initialize"),
            patch.object(instance, "read_state", return_value=empty_state()),
            patch.object(instance, "verify_runtime_absent", return_value=set()),
            patch.object(instance, "verify_runtime_iam_absent"),
            patch.object(teardown.Commands, "json", side_effect=[
                [], [{"tag": tag_prefix + tag}], [],
            ]),
            patch.object(teardown.Commands, "run") as run,
            patch.object(teardown, "request_database") as database,
        ):
            instance.run()
        self.assertEqual(instance.status, "No-op: no tracked preview resources")
        run.assert_called_once()
        self.assertIn(f"{teardown.PREVIEW_FRONTEND_REPOSITORY}:{tag}", run.call_args.args[0])
        database.assert_not_called()

    def test_never_deployed_pr_with_untracked_resources_fails_without_adoption(self):
        for kind in ("runtime", "iam", "secret", "tag", "state"):
            instance = self.make()
            error = lifecycle.LifecycleError("Untracked resource")
            def inventory(arguments, **kwargs):
                if "secrets" in arguments:
                    return [{"name": "projects/fixed/secrets/hh-web-pr-56-i-orphan"}] if kind == "secret" else []
                return [{"tag": "projects/fixed/tags/pr-56-orphan"}] if kind == "tag" else []
            with (
                self.subTest(kind=kind),
                patch.object(instance, "revalidate"),
                patch.object(instance, "check_secret_workflow"),
                patch.object(instance, "initialize"),
                patch.object(instance, "read_state", return_value=None),
                patch.object(instance, "verify_runtime_absent",
                             side_effect=error if kind == "runtime" else None),
                patch.object(instance, "verify_runtime_iam_absent",
                             side_effect=error if kind == "iam" else None),
                patch.object(instance, "verify_state_absent",
                             side_effect=error if kind == "state" else None),
                patch.object(teardown.Commands, "json", side_effect=inventory),
                patch.object(instance, "destroy") as destroy,
                patch.object(teardown, "request_database") as database,
                patch.object(instance, "cleanup_tags") as tags,
            ):
                with self.assertRaises(lifecycle.LifecycleError):
                    instance.run()
                self.assertEqual(instance.status, "Cleanup incomplete")
                destroy.assert_not_called()
                database.assert_not_called()
                tags.assert_not_called()

    def test_cloud_run_and_iap_policy_reads_reject_remaining_and_api_errors(self):
        instance = self.make()
        engine = "hh-web-pr-56-engine"
        owned = {
            "etag": "BwZfURixDfo=",
            "bindings": [{"role": "roles/run.invoker", "members": [
                "serviceAccount:hh-preview-frontend@hh-preview-458395246135.iam.gserviceaccount.com",
            ]}],
        }
        with patch.object(teardown.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, json.dumps(owned).encode(), b"",
        )):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "binding remains"):
                instance.verify_cloud_run_iam_absent(engine, parent_absent=True)
        missing_service = subprocess.CompletedProcess(
            [], 1, b"", f"NOT_FOUND: resource {engine}".encode(),
        )
        with patch.object(teardown.subprocess, "run", return_value=missing_service):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "policy could not be verified"):
                instance.verify_cloud_run_iam_absent(engine, parent_absent=False)
            instance.verify_cloud_run_iam_absent(engine, parent_absent=True)
        with patch.object(teardown.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 1, b"", b"PERMISSION_DENIED",
        )):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "policy could not be verified"):
                instance.verify_cloud_run_iam_absent(engine, parent_absent=True)

        empty_response = io.BytesIO(b'{"bindings":[]}')
        empty_response.status = 200
        with (
            patch.object(teardown.Commands, "run", return_value=b"access-token"),
            patch.object(teardown.urllib.request, "urlopen", return_value=empty_response),
        ):
            instance.verify_iap_iam_absent(parent_absent=True)
        owned_response = io.BytesIO(json.dumps({
            "bindings": [{"role": "roles/iap.httpsResourceAccessor",
                          "members": ["user:tester@example.com"]}],
        }).encode())
        owned_response.status = 200
        with (
            patch.object(teardown.Commands, "run", return_value=b"access-token"),
            patch.object(teardown.urllib.request, "urlopen", return_value=owned_response),
        ):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "IAP tester binding remains"):
                instance.verify_iap_iam_absent(parent_absent=True)
        not_found = lifecycle.urllib.error.HTTPError(
            "https://iap.googleapis.com/fixed", 404, "not found", {}, io.BytesIO(),
        )
        with (
            patch.object(teardown.Commands, "run", return_value=b"access-token"),
            patch.object(teardown.urllib.request, "urlopen", side_effect=not_found),
        ):
            instance.verify_iap_iam_absent(parent_absent=True)
        not_found = lifecycle.urllib.error.HTTPError(
            "https://iap.googleapis.com/fixed", 404, "not found", {}, io.BytesIO(),
        )
        with (
            patch.object(teardown.Commands, "run", return_value=b"access-token"),
            patch.object(teardown.urllib.request, "urlopen", side_effect=not_found),
        ):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "policy API failed"):
                instance.verify_iap_iam_absent(parent_absent=False)

    def test_etag_only_policy_is_empty_for_cloud_run_and_iap(self):
        instance = self.make()
        policy = {"etag": "BwZfURixDfo="}
        self.assertEqual(instance.policy_members(policy, "roles/run.invoker"), set())
        with patch.object(teardown.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, json.dumps(policy).encode(), b"",
        )):
            instance.verify_cloud_run_iam_absent("hh-web-pr-56-engine", parent_absent=True)
        response = io.BytesIO(json.dumps(policy).encode())
        response.status = 200
        with (
            patch.object(teardown.Commands, "run", return_value=b"access-token"),
            patch.object(teardown.urllib.request, "urlopen",
                         return_value=response),
        ):
            instance.verify_iap_iam_absent(parent_absent=True)

    def test_policy_parser_rejects_malformed_or_unexpected_empty_responses(self):
        for policy in (
            None, [], {}, {"etag": ""}, {"etag": 123}, {"etag": None},
            {"etag": "BwZfURixDfo=", "error": {"code": 403}},
            {"etag": "BwZfURixDfo=", "unexpected": []},
            {"etag": "BwZfURixDfo=", "bindings": None},
            {"bindings": {}}, {"bindings": [None]},
            {"bindings": [{"role": "roles/run.invoker", "members": "not-a-list"}]},
            {"bindings": [{"role": "roles/run.invoker", "members": [123]}]},
            {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"],
                           "condition": {"expression": "true"}}]},
        ):
            with self.subTest(policy=policy), self.assertRaises(lifecycle.LifecycleError):
                teardown.PreviewTeardown.policy_members(policy, "roles/run.invoker")

    def test_cloud_run_empty_policy_does_not_mask_errors_or_bad_json(self):
        instance = self.make()
        engine = "hh-web-pr-56-engine"
        for result in (
            subprocess.CompletedProcess([], 0, b"not-json", b""),
            subprocess.CompletedProcess([], 0, b'{"error":{"code":403}}', b""),
            subprocess.CompletedProcess([], 1, b'{"etag":"BwZfURixDfo="}', b"PERMISSION_DENIED"),
            subprocess.CompletedProcess([], 1, b"", f"NOT_FOUND {engine} 403".encode()),
            subprocess.CompletedProcess([], 1, b"", b"NOT_FOUND hh-web-pr-57-engine"),
            subprocess.CompletedProcess([], 1, b"", b"connection unavailable"),
        ):
            with (
                self.subTest(result=result),
                patch.object(teardown.subprocess, "run", return_value=result),
                self.assertRaises(lifecycle.LifecycleError),
            ):
                instance.verify_cloud_run_iam_absent(engine, parent_absent=True)

    def test_runtime_iam_requires_verified_parent_absence_even_with_partial_inventory(self):
        instance = self.make()
        remaining = {address: values for address, values in inventory().items()
                     if address.split("[", 1)[0] not in teardown.RUNTIME}
        for absent in (set(), {"hh-web-pr-56-engine"}):
            with (
                patch.object(instance, "verify_cloud_run_iam_absent") as cloud_run,
                patch.object(instance, "verify_iap_iam_absent") as iap,
                self.assertRaisesRegex(lifecycle.LifecycleError, "parent absence"),
            ):
                instance.verify_runtime_iam_absent(remaining, absent)
            cloud_run.assert_not_called()
            iap.assert_not_called()

    def test_iap_policy_read_does_not_treat_authorization_or_transport_errors_as_absent(self):
        instance = self.make()
        for error in (
            lifecycle.urllib.error.HTTPError(
                "https://iap.googleapis.com/fixed", 403, "permission denied", {}, io.BytesIO(),
            ),
            lifecycle.urllib.error.HTTPError(
                "https://iap.googleapis.com/fixed", 500, "unavailable", {}, io.BytesIO(),
            ),
            lifecycle.urllib.error.URLError("connection unavailable"),
        ):
            with (
                self.subTest(error=error),
                patch.object(teardown.Commands, "run", return_value=b"access-token"),
                patch.object(teardown.urllib.request, "urlopen", side_effect=error),
                self.assertRaises(lifecycle.LifecycleError),
            ):
                instance.verify_iap_iam_absent(parent_absent=True)

    def test_terraform_apply_failure_does_not_claim_success(self):
        instance = self.make()
        instance.state = state()
        with tempfile.TemporaryDirectory() as directory:
            instance.directory = Path(directory)
            with (
                patch.object(instance, "guard"),
                patch.object(teardown, "run_terraform_plan"),
                patch.object(teardown.Commands, "json", return_value=plan()),
                patch.object(teardown.Commands, "run", side_effect=lifecycle.LifecycleError("Terraform apply failed")),
            ):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "Terraform apply failed"):
                    instance.destroy(runtime_only=False)
            self.assertFalse((instance.directory / "destroy.tfplan").exists())
        self.assertEqual(instance.status, "Cleanup incomplete")
        self.assertIn("secret cleanup started, completion unverified", instance.progress)


class ProvisionerTests(unittest.TestCase):
    def test_existing_provisioner_rejects_wrong_owner_and_accepts_already_absent(self):
        source = (
            Path(__file__).resolve().parents[2]
            / "infra/terraform/preview-foundation/db-provisioner/provisioner.py"
        )
        spec = importlib.util.spec_from_file_location("teardown_provisioner_test", source)
        provisioner = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"psycopg": MagicMock(), "psycopg.rows": MagicMock()}):
            spec.loader.exec_module(provisioner)
        connection = MagicMock()
        with patch.object(provisioner, "connect") as connect:
            connect.return_value.__enter__.return_value = connection
            connection.execute.return_value.fetchone.return_value = {"owner": "haunted_halls_staging_app"}
            with self.assertRaisesRegex(RuntimeError, "not owned by the preview app"):
                provisioner.drop_preview_database("haunted_halls_web_pr_56")
            self.assertEqual(connection.execute.call_count, 1)
            connection.execute.reset_mock()
            connection.execute.return_value.fetchone.return_value = None
            self.assertEqual(provisioner.drop_preview_database("haunted_halls_web_pr_56"),
                             {"database": "haunted_halls_web_pr_56", "dropped": False, "operation": "drop"})
            self.assertEqual(connection.execute.call_count, 1)

    def service(self):
        from test_provisioner_token import ProvisionerTokenTests
        service = ProvisionerTokenTests().service()
        service["spec"] = {"template": {"spec": {
            "serviceAccountName": "hh-preview-db-provisioner@haunted-halls-development.iam.gserviceaccount.com",
            "containers": [{"env": [
                {"name": "DB_HOST", "value": "/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"},
                {"name": "DB_PORT", "value": "5432"}, {"name": "DB_NAME", "value": "postgres"},
                {"name": "DB_USER", "value": "haunted_halls_preview_provisioner"},
            ]}],
        }}}
        return service

    def test_drop_uses_fixed_target_and_rechecks_before_post(self):
        response = {"operation": "drop", "database": "haunted_halls_web_pr_56", "dropped": False}
        guard = Mock()
        with (
            tempfile.NamedTemporaryFile() as credentials,
            patch.dict(os.environ, {"GOOGLE_BACKEND_CREDENTIALS": credentials.name}),
            patch.object(lifecycle.Commands, "json", return_value=self.service()),
            patch.object(lifecycle.Commands, "run", return_value=b"private-token"),
            patch.object(lifecycle.urllib.request.OpenerDirector, "open", return_value=io.BytesIO(json.dumps(response).encode())) as post,
        ):
            self.assertEqual(lifecycle.request_database("56", "drop", guard), response)
        guard.assert_called_once()
        self.assertEqual(json.loads(post.call_args.args[0].data),
                         {"operation": "drop", "repository_key": "web", "pull_request_number": 56})

    def test_wrong_sql_target_never_sends_drop(self):
        service = self.service()
        service["spec"]["template"]["spec"]["containers"][0]["env"][0]["value"] = "/cloudsql/production"
        with patch.object(lifecycle.Commands, "json", return_value=service), patch.object(lifecycle.urllib.request.OpenerDirector, "open") as post:
            with self.assertRaisesRegex(lifecycle.LifecycleError, "manual cleanup"):
                lifecycle.request_database("56", "drop")
            post.assert_not_called()

    def test_legacy_provisioner_drop_preserves_runtime_and_sql_identity_checks(self):
        origin = "https://hh-preview-db-provisioner-lt5viwug5a-ue.a.run.app"
        response = {"operation": "drop", "database": "haunted_halls_web_pr_56", "dropped": False}
        service = self.service()
        service["status"]["url"] = origin
        with (
            tempfile.NamedTemporaryFile() as credentials,
            patch.dict(os.environ, {"GOOGLE_BACKEND_CREDENTIALS": credentials.name}),
            patch.object(lifecycle.Commands, "json", return_value=service),
            patch.object(lifecycle.Commands, "run", return_value=b"test-token") as token,
            patch.object(lifecycle.urllib.request.OpenerDirector, "open",
                         return_value=io.BytesIO(json.dumps(response).encode())) as post,
        ):
            self.assertEqual(lifecycle.request_database("56", "drop"), response)
            self.assertIn(f"--audiences={origin}", token.call_args.args[0])
            self.assertEqual(post.call_args.args[0].full_url, origin + "/provision")
            for mutate in (
                lambda s: s.update(serviceAccountName="untrusted@example.com"),
                lambda s: s["containers"][0]["env"][0].update(value="/cloudsql/other"),
                lambda s: s["containers"][0]["env"][2].update(value="haunted_halls_staging"),
                lambda s: s["containers"][0]["env"][3].update(value="other_user"),
            ):
                altered = copy.deepcopy(service)
                mutate(altered["spec"]["template"]["spec"])
                with patch.object(lifecycle.Commands, "json", return_value=altered):
                    token.reset_mock()
                    post.reset_mock()
                    with self.subTest(mutate=mutate), self.assertRaisesRegex(
                        lifecycle.LifecycleError, "Database target is unverified",
                    ):
                        lifecycle.request_database("56", "drop")
                    token.assert_not_called()
                    post.assert_not_called()

    def test_late_guard_failure_never_posts_and_gcp_failure_is_sanitized(self):
        with (
            tempfile.NamedTemporaryFile() as credentials,
            patch.dict(os.environ, {"GOOGLE_BACKEND_CREDENTIALS": credentials.name}),
            patch.object(lifecycle.Commands, "json", return_value=self.service()),
            patch.object(lifecycle.Commands, "run", return_value=b"private-token"),
            patch.object(lifecycle.urllib.request.OpenerDirector, "open") as post,
        ):
            with self.assertRaisesRegex(lifecycle.LifecycleError, "reopened"):
                lifecycle.request_database("56", "drop", Mock(side_effect=lifecycle.LifecycleError("reopened")))
            post.assert_not_called()
            post.side_effect = lifecycle.urllib.error.URLError("private-provider-details")
            with self.assertRaises(lifecycle.LifecycleError) as error:
                lifecycle.request_database("56", "drop", Mock())
            self.assertNotIn("private-provider-details", str(error.exception))


class ReportingAndWorkflowTests(unittest.TestCase):
    def test_main_reports_partial_failure_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory) / "context.json"
            context.write_text(json.dumps(CONTEXT))
            summary = Path(directory) / "summary"
            github = Mock()
            github.api.return_value = closed()
            with (
                patch.dict(os.environ, {**ENV, "GH_TOKEN": "test-token", "GITHUB_STEP_SUMMARY": str(summary)}),
                patch.object(teardown, "Github", return_value=github),
                patch.object(teardown.PreviewTeardown, "run", side_effect=lifecycle.LifecycleError("GCP unavailable")),
                patch.object(teardown, "preview_comments", return_value=[]),
                patch("sys.argv", ["teardown.py", "run", "--context", str(context)]),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(teardown.main(), 1)
            self.assertIn("Cleanup incomplete", summary.read_text())
            self.assertIn("GCP unavailable", summary.read_text())

    def test_comment_failure_does_not_change_successful_infrastructure_status(self):
        github = Mock()
        instance = teardown.PreviewTeardown(CONTEXT, github)
        instance.status = "Removed"
        github.api.side_effect = lifecycle.LifecycleError("comment permission denied")
        with patch.object(instance, "revalidate"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            instance.report(None)
        self.assertEqual(instance.status, "Removed")
        self.assertIn("comment update failed", stderr.getvalue())

    def test_existing_comment_is_updated_not_duplicated_with_timestamp_and_partial_status(self):
        github = Mock()
        github.api.return_value = [{
            "id": 17, "body": teardown.COMMENT_MARKER,
            "user": {"type": "Bot", "login": "github-actions[bot]"},
        }]
        instance = teardown.PreviewTeardown(CONTEXT, github)
        with patch.object(instance, "revalidate"), redirect_stdout(io.StringIO()):
            instance.report("Terraform unavailable")
        write = github.api.call_args
        self.assertEqual(write.kwargs["method"], "PATCH")
        body = write.kwargs["data"]["body"]
        self.assertIn("Cleanup incomplete", body)
        self.assertIn("Terraform unavailable", body)
        self.assertIn("Completed at", body)
        self.assertEqual(body.count(teardown.COMMENT_MARKER), 1)

    def test_workflow_uses_same_lock_trusted_source_and_existing_wif_only(self):
        root = Path(__file__).resolve().parents[2] / ".github/workflows"
        workflow = (root / "preview-deploy.yml").read_text()
        job = workflow.split("\n  teardown:\n", 1)[1]
        executor = (root / "preview-teardown-executor.yml").read_text()
        self.assertIn("pull_request_target:\n    branches: [main]\n    types: [closed]", workflow)
        self.assertIn("group: frontend-preview-pr-${{ github.event.pull_request.number || inputs.pull_request_number }}", job)
        self.assertIn("cancel-in-progress: false", job)
        self.assertIn("uses: ./.github/workflows/preview-teardown-executor.yml", job)
        self.assertIn("ref: ${{ github.sha }}", executor)
        self.assertNotIn("pull_request.head", job)
        self.assertLess(
            executor.index("Validate closed PR before cloud authentication"),
            executor.index("uses: google-github-actions/auth"),
        )
        self.assertIn("service_account: ${{ env.DEPLOY_SERVICE_ACCOUNT }}", executor)
        self.assertNotIn("actions: write", job)
        self.assertNotIn("continue-on-error", executor)

    def test_teardown_and_secret_preparation_share_inner_lock_under_outer_per_pr_lock(self):
        root = Path(__file__).resolve().parents[2] / ".github/workflows"
        deployment = (root / "preview-deploy.yml").read_text()
        teardown_job = deployment.split("\n  teardown:\n", 1)[1]
        secret_preparation = (root / "preview-secret-prepare.yml").read_text()
        executor = (root / "preview-teardown-executor.yml").read_text()

        outer_lock = "frontend-preview-pr-${{ github.event.pull_request.number || inputs.pull_request_number }}"
        inner_lock = "preview-secret-preparation-${{ inputs.pull_request_number }}"
        self.assertIn(outer_lock, teardown_job)
        self.assertIn("group: frontend-preview-pr-${{ inputs.pull_request_number }}", deployment)
        self.assertIn("group: preview-secret-preparation-${{ inputs.pull_request_number }}", secret_preparation)
        self.assertIn(inner_lock, executor)
        self.assertNotEqual(outer_lock, inner_lock)
        self.assertIn("with:\n      pull_request_number: ${{ github.event.pull_request.number || inputs.pull_request_number }}", teardown_job)

        self.assertIn(f"\nconcurrency:\n  group: {inner_lock}\n  cancel-in-progress: false\n", secret_preparation)
        executor_job = executor.split("\njobs:\n", 1)[1]
        self.assertIn(f"\n    concurrency:\n      group: {inner_lock}\n      cancel-in-progress: false\n", executor_job)
        self.assertEqual(re.findall(r"^  ([a-z_-]+):$", executor_job, re.M), ["teardown"])
        self.assertEqual(
            re.findall(r"^  ([a-z_-]+):$", secret_preparation.split("\njobs:\n", 1)[1], re.M),
            ["prepare"],
        )
        self.assertNotIn("frontend-preview-pr-", secret_preparation)
        self.assertNotIn("frontend-preview-pr-", executor)
        self.assertIn("python tools/preview-secret-preparer/prepare.py", secret_preparation)
        self.assertIn("python tools/preview-deploy/teardown.py run", executor_job)

    def test_reusable_executor_trust_gate_uses_original_caller_context(self):
        if shutil.which("jq") is None:
            self.skipTest("jq is required to execute the workflow trust gate.")
        workflow = (Path(__file__).resolve().parents[2]
                    / ".github/workflows/preview-teardown-executor.yml").read_text()
        self.assertIn("on:\n  workflow_call:\n", workflow)
        script = workflow.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
        script = "\n".join(line.removeprefix("          ") for line in script.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            for name, payload in (
                ("pull_request_target", {"pull_request": {"number": 56}}),
                ("workflow_dispatch", {"inputs": {"operation": "teardown", "pull_request_number": "56"}}),
            ):
                event.write_text(json.dumps(payload))
                for override in (
                    {},
                    {"INPUT_PR_NUMBER": "57"},
                    {"GITHUB_EVENT_NAME": "workflow_call"},
                    {"GITHUB_REF": "refs/heads/untrusted"},
                    {"GITHUB_REPOSITORY": "someone/other"},
                    {"GITHUB_WORKFLOW_REF": f"{teardown.REPOSITORY}/.github/workflows/preview-teardown-executor.yml@refs/heads/main"},
                ):
                    with self.subTest(event=name, override=override):
                        result = subprocess.run(
                            ["bash", "-c", script],
                            env={**os.environ, **ENV, "GITHUB_EVENT_NAME": name,
                                 "INPUT_PR_NUMBER": "56", "GITHUB_EVENT_PATH": str(event), **override},
                            capture_output=True, text=True, timeout=10, check=False,
                        )
                        self.assertEqual(result.returncode == 0, not override, result.stderr)


if __name__ == "__main__":
    unittest.main()
