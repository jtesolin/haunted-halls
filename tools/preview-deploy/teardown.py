#!/usr/bin/env python3
"""Bounded trusted teardown of one closed frontend PR; never adopt untracked resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lifecycle import (
    COMMENT_MARKER, DEPLOYER, INCARNATION_RE, PREVIEW_ENGINE_REPOSITORY,
    PREVIEW_FRONTEND_REPOSITORY, PREVIEW_PROJECT, PREVIEW_PROJECT_NUMBER,
    PREVIEW_REGION, PR_RE, REPOSITORY, SECRET_WORKFLOW, SHA_RE, STATE_BUCKET,
    STATE_GENERATION_RE, TERRAFORM_ROOT, Commands, Github, LifecycleError,
    _expect, derive_database_name, preview_comments, request_database,
    run_terraform_plan,
)

sys.path.insert(0, str(TERRAFORM_ROOT.resolve()))
from check_backend import verify_backend


RUNTIME = {
    "google_cloud_run_v2_service.frontend",
    "google_cloud_run_v2_service.engine",
    "google_cloud_run_v2_job.migration",
    "google_cloud_run_v2_service_iam_member.engine_frontend",
    "google_cloud_run_v2_service_iam_member.frontend_iap",
    "google_iap_web_cloud_run_service_iam_member.tester",
}
ALLOWED = RUNTIME | {
    "google_secret_manager_secret.pr", "google_secret_manager_secret_iam_member.runtime",
}
ALLOWED_IAM_ADDRESSES = {
    "google_cloud_run_v2_service_iam_member.engine_frontend",
    "google_cloud_run_v2_service_iam_member.frontend_iap",
    "google_iap_web_cloud_run_service_iam_member.tester",
}
ROLES = {"nextauth": "nextauth", "internal_token": "internal-token", "database_url": "database-url"}
GRANTS = {
    "frontend_nextauth": ("nextauth", "frontend"),
    "frontend_token": ("internal_token", "frontend"),
    "engine_token": ("internal_token", "engine"),
    "engine_database": ("database_url", "engine"),
    "migrate_database": ("database_url", "migration"),
}
PROVIDER = 'provider["registry.terraform.io/hashicorp/google"]'


def trusted_context() -> None:
    _expect(
        os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_WORKFLOW_REF")
        == f"{REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_EVENT_NAME") in {"pull_request_target", "workflow_dispatch"},
        "Teardown requires the trusted main workflow in the fixed frontend repository.",
    )


def closed_pr(github: Github, number: str) -> dict[str, str]:
    _expect(isinstance(number, str) and PR_RE.fullmatch(number), "PR number is not canonical.")
    pr = github.api(f"repos/{REPOSITORY}/pulls/{number}")
    _expect(
        isinstance(pr, dict) and type(pr.get("number")) is int
        and pr["number"] == int(number)
        and pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pr.get("base", {}).get("ref") == "main",
        "The PR identity or target repository is incorrect.",
    )
    _expect(pr.get("state") == "closed", "The PR is open or reopened; teardown refused.")
    sha, closed_at = pr.get("head", {}).get("sha"), pr.get("closed_at")
    _expect(
        isinstance(sha, str) and SHA_RE.fullmatch(sha)
        and isinstance(closed_at, str)
        and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", closed_at),
        "Closed PR metadata is incomplete.",
    )
    return {"number": number, "head_sha": sha, "closed_at": closed_at}


def prepare(args: argparse.Namespace, github: Github) -> None:
    trusted_context()
    event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    _expect(isinstance(event, dict)
            and event.get("repository", {}).get("full_name") == REPOSITORY,
            "The teardown event repository is incorrect.")
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request_target":
        pr = event.get("pull_request", {})
        number = pr.get("number")
        _expect(event.get("action") == "closed" and type(number) is int,
                "Only a PR closure event may request automatic teardown.")
        context = closed_pr(github, str(number))
        _expect(pr.get("closed_at") == context["closed_at"]
                and pr.get("head", {}).get("sha") == context["head_sha"],
                "The closure event is stale; use manual reconciliation.")
    else:
        inputs = event.get("inputs", {})
        _expect(inputs.get("operation") == "teardown", "The dispatch is not a teardown request.")
        context = closed_pr(github, inputs.get("pull_request_number"))
    path = Path(args.context)
    path.write_text(json.dumps(context), encoding="utf-8")
    path.chmod(0o600)
    with Path(args.github_output).open("a", encoding="utf-8") as output:
        output.write(f"pull_request_number={context['number']}\n")


def resource_address(resource: dict[str, Any], instance: dict[str, Any]) -> str:
    base = f"{resource.get('type')}.{resource.get('name')}"
    return base + (f"[{json.dumps(instance['index_key'])}]" if "index_key" in instance else "")


def identity_output(state: dict[str, Any], number: str) -> dict[str, Any] | None:
    output = state.get("outputs", {}).get("preview_identity")
    if output is None:
        return None
    value = output.get("value") if isinstance(output, dict) else None
    _expect(isinstance(value, dict), "Terraform preview identity output is malformed.")
    expected = {
        "project_id": PREVIEW_PROJECT, "repository_key": "web", "pr_number": number,
        "state_bucket": STATE_BUCKET, "state_prefix": f"previews/web-pr-{number}",
        "database_name": derive_database_name(number),
        "frontend_name": f"hh-web-pr-{number}-frontend",
        "engine_name": f"hh-web-pr-{number}-engine",
        "migration_name": f"hh-web-pr-{number}-migrate",
    }
    _expect(all(value.get(key) == item for key, item in expected.items()),
            "Terraform preview identity belongs to a different resource, database, or backend.")
    _expect(isinstance(value.get("pr_incarnation"), str)
            and INCARNATION_RE.fullmatch(value["pr_incarnation"]),
            "Terraform preview incarnation is invalid.")
    return value


def validate_resource(address: str, values: object, number: str, incarnation: str) -> None:
    _expect(isinstance(values, dict), "Resource ownership attributes are missing.")
    base = address.split("[", 1)[0]
    _expect(base in ALLOWED and values.get("project") == PREVIEW_PROJECT,
            "Unexpected Terraform address or project; nothing will be adopted.")
    prefix = f"hh-web-pr-{number}"
    secret_prefix = f"{prefix}-i-{incarnation}"
    if base == "google_secret_manager_secret.pr":
        _expect(address in {f'{base}["{role}"]' for role in ROLES},
                "Unexpected secret role.")
        role = json.loads(address[len(base) + 1:-1])
        secret = f"{secret_prefix}-{ROLES[role]}"
        _expect(values.get("secret_id") == secret
                and values.get("id") == f"projects/{PREVIEW_PROJECT}/secrets/{secret}",
                "Secret resource identity is incorrect.")
    elif base == "google_secret_manager_secret_iam_member.runtime":
        _expect(address in {f'{base}["{key}"]' for key in GRANTS},
                "Unexpected secret IAM grant.")
        role, runtime = GRANTS[json.loads(address[len(base) + 1:-1])]
        _expect(values.get("secret_id") == f"projects/{PREVIEW_PROJECT}/secrets/{secret_prefix}-{ROLES[role]}"
                and values.get("role") == "roles/secretmanager.secretAccessor"
                and values.get("member")
                == f"serviceAccount:hh-preview-{runtime}@{PREVIEW_PROJECT}.iam.gserviceaccount.com"
                and not values.get("condition"),
                "Secret IAM grant does not belong to this preview.")
        _expect(
            iam_member_id_matches(
                values.get("id"), values["secret_id"], values["role"], values["member"]
            ),
            "Secret IAM resource ID is incorrect.",
        )
    else:
        suffix = {
            "google_cloud_run_v2_service.frontend": "frontend",
            "google_cloud_run_v2_service.engine": "engine",
            "google_cloud_run_v2_job.migration": "migrate",
            "google_cloud_run_v2_service_iam_member.engine_frontend": "engine",
            "google_cloud_run_v2_service_iam_member.frontend_iap": "frontend",
            "google_iap_web_cloud_run_service_iam_member.tester": "frontend",
        }[base]
        name = f"{prefix}-{suffix}"
        _expect(values.get("location") == PREVIEW_REGION, "Unexpected resource region.")
        if base == "google_iap_web_cloud_run_service_iam_member.tester":
            member = values.get("member")
            _expect(isinstance(member, str)
                    and re.fullmatch(r"(?:user|group):[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", member)
                    and address == f"{base}[{json.dumps(member)}]"
                    and values.get("cloud_run_service_name") in {
                        name, f"projects/{PREVIEW_PROJECT}/iap_web/cloud_run-{PREVIEW_REGION}/services/{name}",
                    }
                    and values.get("role") == "roles/iap.httpsResourceAccessor"
                    and not values.get("condition"),
                    "IAP binding is not confined to this preview.")
            _expect(
                iam_member_id_matches(
                    values.get("id"),
                    f"projects/{PREVIEW_PROJECT}/iap_web/cloud_run-{PREVIEW_REGION}/services/{name}",
                    values["role"],
                    member,
                ),
                "IAP resource ID is incorrect.",
            )
        else:
            _expect(address == base and values.get("name") in {
                name, f"projects/{PREVIEW_PROJECT}/locations/{PREVIEW_REGION}/services/{name}",
            },
                    "Cloud Run resource name is incorrect.")
            if base.startswith("google_cloud_run_v2_service_iam_member"):
                member = (
                    f"serviceAccount:hh-preview-frontend@{PREVIEW_PROJECT}.iam.gserviceaccount.com"
                    if suffix == "engine" else
                    f"serviceAccount:service-{PREVIEW_PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
                )
                _expect(values.get("role") == "roles/run.invoker"
                        and values.get("member") == member and not values.get("condition"),
                        "Cloud Run IAM binding is incorrect.")
                _expect(
                    iam_member_id_matches(
                        values.get("id"),
                        f"projects/{PREVIEW_PROJECT}/locations/{PREVIEW_REGION}/services/{name}",
                        values["role"],
                        member,
                    ),
                    "Cloud Run IAM resource ID is incorrect.",
                )
            else:
                kind = "jobs" if suffix == "migrate" else "services"
                _expect(values.get("id") == f"projects/{PREVIEW_PROJECT}/locations/{PREVIEW_REGION}/{kind}/{name}",
                        "Cloud Run resource ID is incorrect.")
    if base in {
        "google_secret_manager_secret.pr", "google_cloud_run_v2_service.frontend",
        "google_cloud_run_v2_service.engine", "google_cloud_run_v2_job.migration",
    }:
        labels = values.get("labels")
        expected = {
            "app": "haunted-halls", "environment": "preview", "repository": "web",
            "pull_request": number, "incarnation": incarnation, "managed_by": "terraform",
        }
        _expect(isinstance(labels, dict)
                and all(labels.get(key) == value for key, value in expected.items()),
                "Resource ownership labels are incorrect or from a newer incarnation.")
        if base == "google_secret_manager_secret.pr":
            _expect(isinstance(labels.get("secret_generation"), str)
                    and STATE_GENERATION_RE.fullmatch(labels["secret_generation"]),
                    "Secret generation is invalid.")


def iam_member_id_matches(value: object, resource: str, role: str, member: str) -> bool:
    return isinstance(value, str) and value in (
        f"{resource} {role} {member}",
        f"{resource}/{role}/{member}",
    )


def validate_state(state: object, number: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
    _expect(isinstance(state, dict) and isinstance(state.get("resources"), list),
            "Terraform state is malformed.")
    output = identity_output(state, number)
    incarnations = {output["pr_incarnation"]} if output else set()
    inventory: dict[str, dict[str, Any]] = {}
    for resource in state["resources"]:
        _expect(isinstance(resource, dict) and resource.get("mode") == "managed"
                and not resource.get("module") and resource.get("provider") == PROVIDER
                and isinstance(resource.get("instances"), list),
                "Unexpected state module, data source, provider, or resource.")
        for instance in resource["instances"]:
            _expect(isinstance(instance, dict) and not instance.get("deposed")
                    and isinstance(instance.get("attributes"), dict),
                    "Resource state is incomplete or deposed; manual cleanup is required.")
            address = resource_address(resource, instance)
            _expect(address not in inventory, "Duplicate resource identity.")
            values = instance["attributes"]
            inventory[address] = values
            label = values.get("labels", {}).get("incarnation")
            if label is not None:
                _expect(isinstance(label, str) and INCARNATION_RE.fullmatch(label),
                        "Resource incarnation is malformed.")
                incarnations.add(label)
    if not inventory:
        return (output["pr_incarnation"] if output else None), inventory
    _expect(len(incarnations) == 1, "Preview incarnation is missing or ambiguous; manual cleanup is required.")
    incarnation = next(iter(incarnations))
    for address, values in inventory.items():
        validate_resource(address, values, number, incarnation)
    generations = {
        values["labels"]["secret_generation"] for address, values in inventory.items()
        if address.startswith("google_secret_manager_secret.pr[")
    }
    _expect(len(generations) <= 1, "Secret generations disagree; manual cleanup is required.")
    _expect(isinstance(state.get("lineage"), str) and state["lineage"]
            and type(state.get("serial")) is int and state["serial"] >= 0,
            "Terraform state lineage or serial is missing.")
    return incarnation, inventory


def validate_destroy_plan(
    plan: object, number: str, incarnation: str, inventory: dict[str, dict[str, Any]],
    allowed: set[str],
) -> None:
    _expect(isinstance(plan, dict) and plan.get("errored") is not True
            and isinstance(plan.get("resource_changes", []), list),
            "Terraform destroy plan is malformed.")
    for item in plan.get("resource_changes", []):
        _expect(isinstance(item, dict), "Malformed destroy change.")
        address, change = item.get("address"), item.get("change")
        _expect(isinstance(address, str) and address in inventory
                and item.get("provider_name") == "registry.terraform.io/hashicorp/google"
                and item.get("mode") == "managed" and not item.get("deposed")
                and isinstance(change, dict)
                and change.get("actions") in (["delete"], ["no-op"]),
                "Destroy plan has unexpected resources, changes, or replacements.")
        _expect(change["actions"] == ["no-op"] or address.split("[", 1)[0] in allowed,
                "Destroy plan deletes a resource outside this cleanup step.")
        validate_resource(address, change.get("before"), number, incarnation)
        before_generation = inventory[address].get("labels", {}).get("secret_generation")
        _expect(change["before"].get("labels", {}).get("secret_generation") == before_generation,
                "Secret generation changed during destroy planning.")
        _expect(change.get("actions") != ["delete"] or change.get("after") is None,
                "Destroy plan has an unexpected after-value.")
        _expect(change["actions"] != ["no-op"] or change.get("after") == change["before"],
                "A no-op plan entry contains modifications.")


def state_digest(state: object) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


class PreviewTeardown:
    def __init__(self, context: dict[str, str], github: Github):
        self.context, self.github = context, github
        self.number = context["number"]
        self.directory: Path | None = None
        self.state: dict[str, Any] = {}
        self.status = "Cleanup incomplete"
        self.progress = "No destructive operation completed."

    def revalidate(self) -> None:
        trusted_context()
        _expect(closed_pr(self.github, self.number) == self.context,
                "PR closure identity changed; teardown refused.")

    def initialize(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix=f"teardown-{self.number}-",
                                             dir=os.environ.get("RUNNER_TEMP")))
        os.environ["TF_DATA_DIR"] = str(self.directory)
        Commands.run([
            "terraform", f"-chdir={TERRAFORM_ROOT}", "init", "-input=false", "-no-color",
            "-reconfigure", f"-backend-config=bucket={STATE_BUCKET}",
            f"-backend-config=prefix=previews/web-pr-{self.number}",
            f"-backend-config=impersonate_service_account={DEPLOYER}",
        ], label="Teardown backend initialization", timeout=600)
        self.check_backend()
        workspace = Commands.run(
            ["terraform", f"-chdir={TERRAFORM_ROOT}", "workspace", "show"],
            label="Teardown workspace verification",
        ).decode().strip()
        _expect(workspace == "default", "Teardown requires the default workspace.")

    def check_backend(self) -> None:
        _expect(self.directory is not None, "Teardown backend is not initialized.")
        try:
            verify_backend(json.loads((self.directory / "terraform.tfstate").read_text()),
                           "web", self.number)
        except (OSError, ValueError):
            raise LifecycleError("Teardown backend identity is incorrect or unavailable.") from None

    def read_state(self) -> dict[str, Any]:
        self.check_backend()
        result = subprocess.run(
            ["terraform", f"-chdir={TERRAFORM_ROOT}", "state", "pull"],
            capture_output=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            diagnostic = result.stdout + result.stderr
            _expect(b"No state file was found" in diagnostic
                    and b"403" not in diagnostic and b"PERMISSION_DENIED" not in diagnostic,
                    "Cannot read authoritative PR state; cleanup refused.")
            return {"resources": []}
        if not result.stdout.strip():
            return {"resources": []}
        try:
            return json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise LifecycleError("Teardown state is invalid JSON.") from None

    def guard(self) -> None:
        self.revalidate()
        _expect(state_digest(self.read_state()) == state_digest(self.state),
                "Terraform state changed; retry cleanup after reviewing concurrent operations.")

    def check_secret_workflow(self) -> None:
        # A standalone preparer uses a separate lock so deployment can await it.
        for status in ("in_progress", "queued", "waiting", "pending", "requested"):
            runs = self.github.api(
                f"repos/{REPOSITORY}/actions/workflows/{SECRET_WORKFLOW}/runs"
                f"?status={status}&per_page=100"
            )
            _expect(isinstance(runs, dict) and isinstance(runs.get("workflow_runs"), list)
                    and len(runs["workflow_runs"]) < 100,
                    "Cannot verify active secret preparation; retry when preparation is idle.")
            for run in runs["workflow_runs"]:
                _expect(isinstance(run, dict), "Secret workflow metadata is invalid.")
                _expect(f" PR-{self.number}-" not in str(run.get("display_title", "")),
                        "Secret preparation is still active; retry teardown after it finishes.")

    def variables(self, incarnation: str, inventory: dict[str, dict[str, Any]]) -> list[str]:
        output = identity_output(self.state, self.number) or {}
        def image(key: str, repository: str) -> str:
            value = output.get(key, repository + "@sha256:" + "0" * 64)
            _expect(isinstance(value, str)
                    and re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", value),
                    "Terraform image identity is invalid.")
            return value
        generations = [item["labels"]["secret_generation"] for address, item in inventory.items()
                       if address.startswith("google_secret_manager_secret.pr[")]
        testers = [item["member"] for address, item in inventory.items()
                   if address.startswith("google_iap_web_cloud_run_service_iam_member.tester[")]
        values = {
            "repository_key": "web", "pull_request_number": self.number,
            "backend_state_prefix": f"previews/web-pr-{self.number}",
            "pr_incarnation": incarnation, "secret_generation": generations[0] if generations else "0",
            "preview_project_number": PREVIEW_PROJECT_NUMBER,
            "frontend_image": image("frontend_image", PREVIEW_FRONTEND_REPOSITORY),
            "engine_image": image("engine_image", PREVIEW_ENGINE_REPOSITORY),
            "iap_testers": testers or ["user:unused@example.invalid"],
            "nextauth_secret_version": "1", "internal_engine_service_token_version": "1",
            "database_url_secret_version": "1",
        }
        # Destroy never creates/updates resources; placeholders only satisfy variable validation.
        return [f"-var={key}={json.dumps(value) if isinstance(value, list) else value}"
                for key, value in values.items()]

    def destroy(self, *, runtime_only: bool) -> None:
        incarnation, inventory = validate_state(self.state, self.number)
        if not inventory:
            return
        _expect(incarnation is not None, "No authoritative incarnation.")
        lineage, serial = self.state["lineage"], self.state["serial"]
        allowed = RUNTIME if runtime_only else ALLOWED
        if not any(address.split("[", 1)[0] in allowed for address in inventory):
            return
        plan = self.directory / "destroy.tfplan"
        arguments = [
            "terraform", f"-chdir={TERRAFORM_ROOT}", "plan", "-destroy",
            "-input=false", "-no-color", "-json", f"-out={plan}",
            *self.variables(incarnation, inventory),
        ]
        if runtime_only:
            arguments.extend(f"-target={target}" for target in sorted(RUNTIME))
        self.guard()
        try:
            run_terraform_plan(arguments, label="PR destroy planning", targets=allowed)
            contents = Commands.json(
                ["terraform", f"-chdir={TERRAFORM_ROOT}", "show", "-json", str(plan)],
                label="Destroy plan inspection",
            )
            validate_destroy_plan(contents, self.number, incarnation, inventory, allowed)
            self.guard()
            self.progress = (
                "Runtime cleanup started; completion unverified. Database and secrets retained."
                if runtime_only else
                "Runtime and database cleanup verified; secret cleanup started, completion unverified."
            )
            Commands.run(
                ["terraform", f"-chdir={TERRAFORM_ROOT}", "apply", "-input=false",
                 "-no-color", "-auto-approve", str(plan)],
                label="Validated PR destroy apply", timeout=900,
            )
        finally:
            plan.unlink(missing_ok=True)
        self.state = self.read_state()
        next_incarnation, remaining = validate_state(self.state, self.number)
        _expect(self.state.get("lineage") == lineage
                and type(self.state.get("serial")) is int and self.state["serial"] >= serial
                and next_incarnation in {None, incarnation},
                "State lineage or incarnation changed after apply; stop for manual review.")
        _expect(not any(address.split("[", 1)[0] in allowed for address in remaining),
                "Terraform still tracks resources after destroy; retry or clean up manually.")

    def verify_runtime_absent(self) -> set[str]:
        present: set[str] = set()
        for kind, suffixes in (("services", ("frontend", "engine")), ("jobs", ("migrate",))):
            names = {f"hh-web-pr-{self.number}-{suffix}" for suffix in suffixes}
            values = Commands.json([
                "gcloud", "run", kind, "list", f"--project={PREVIEW_PROJECT}",
                f"--region={PREVIEW_REGION}", "--format=json",
            ], label="PR runtime absence verification")
            _expect(isinstance(values, list), "Cloud Run inventory is malformed.")
            for item in values:
                _expect(isinstance(item, dict), "Cloud Run inventory is malformed.")
                name = item.get("metadata", {}).get("name") or item.get("name")
                _expect(isinstance(name, str), "Cloud Run identity is missing.")
                if name.rsplit("/", 1)[-1] in names:
                    present.add(name.rsplit("/", 1)[-1])
        _expect(not present, "A PR runtime resource remains; database deletion is unsafe.")
        return {f"hh-web-pr-{self.number}-frontend", f"hh-web-pr-{self.number}-engine"}

    @staticmethod
    def policy_members(policy: object, role: str) -> set[str]:
        _expect(isinstance(policy, dict) and isinstance(policy.get("bindings"), list),
                "Resource IAM policy is malformed or unavailable.")
        members: set[str] = set()
        for binding in policy["bindings"]:
            _expect(isinstance(binding, dict)
                    and isinstance(binding.get("role"), str)
                    and isinstance(binding.get("members", []), list),
                    "Resource IAM policy contains a malformed binding.")
            if binding["role"] == role:
                _expect(
                    all(isinstance(member, str) for member in binding.get("members", []))
                    and not binding.get("condition"),
                    "Resource IAM policy contains a conditional or malformed owned binding.",
                )
                members.update(binding.get("members", []))
        return members

    def verify_cloud_run_iam_absent(self, service: str, parent_absent: bool) -> None:
        result = subprocess.run(
            [
                "gcloud", "run", "services", "get-iam-policy", service,
                f"--project={PREVIEW_PROJECT}", f"--region={PREVIEW_REGION}", "--format=json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            diagnostic = result.stdout + result.stderr
            _expect(
                parent_absent
                and (b"NOT_FOUND" in diagnostic or b"not found" in diagnostic.lower())
                and service.encode() in diagnostic
                and b"PERMISSION_DENIED" not in diagnostic and b"403" not in diagnostic,
                "Cloud Run IAM policy could not be verified; database deletion is blocked.",
            )
            return
        try:
            policy = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LifecycleError("Cloud Run IAM policy returned invalid metadata.") from None
        remaining = self.policy_members(policy, "roles/run.invoker")
        _expect(not remaining, "An owned Cloud Run invoker binding remains; database deletion is blocked.")

    def verify_iap_iam_absent(self, parent_absent: bool) -> None:
        token = Commands.run(
            ["gcloud", "auth", "print-access-token"],
            label="IAP teardown policy access token",
        ).decode("utf-8", errors="strict").strip()
        _expect(bool(token), "IAP teardown policy access token is unavailable.")
        resource = (
            f"https://iap.googleapis.com/v1/projects/{PREVIEW_PROJECT_NUMBER}"
            f"/iap_web/cloud_run-{PREVIEW_REGION}/services/"
            f"hh-web-pr-{self.number}-frontend"
        )
        request = urllib.request.Request(
            resource + ":getIamPolicy?options.requestedPolicyVersion=3",
            data=json.dumps({"options": {"requestedPolicyVersion": 3}}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        del token
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                policy = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                _expect(
                    error.code == 404 and parent_absent,
                    "IAP policy API failed; database deletion is blocked.",
                )
                return
            finally:
                error.close()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise LifecycleError("IAP policy could not be verified; database deletion is blocked.") from None
        remaining = self.policy_members(policy, "roles/iap.httpsResourceAccessor")
        _expect(not remaining,
                "An owned IAP tester binding remains; database deletion is blocked.")

    def verify_runtime_iam_absent(
        self, inventory: dict[str, dict[str, Any]], absent_services: set[str],
    ) -> None:
        names = {
            f"hh-web-pr-{self.number}-engine",
            f"hh-web-pr-{self.number}-frontend",
        }
        _expect(names <= absent_services,
                "Runtime parent absence was not verified before checking its IAM policy.")
        expected_addresses = {
            address for address in inventory if "_iam_member." in address
        }
        _expect(expected_addresses <= ALLOWED_IAM_ADDRESSES,
                "Runtime state contains an unexpected IAM address.")
        self.verify_cloud_run_iam_absent(
            f"hh-web-pr-{self.number}-engine",
            f"hh-web-pr-{self.number}-engine" in absent_services,
        )
        self.verify_cloud_run_iam_absent(
            f"hh-web-pr-{self.number}-frontend",
            f"hh-web-pr-{self.number}-frontend" in absent_services,
        )
        self.verify_iap_iam_absent(f"hh-web-pr-{self.number}-frontend" in absent_services)

    def verify_secrets_absent(self, secrets: list[str]) -> None:
        for secret in secrets:
            result = subprocess.run([
                "gcloud", "secrets", "describe", secret,
                f"--project={PREVIEW_PROJECT}", "--format=json",
            ], capture_output=True, timeout=120, check=False)
            _expect(result.returncode != 0 and b"NOT_FOUND" in result.stderr
                    and b"PERMISSION_DENIED" not in result.stderr and b"403" not in result.stderr,
                    "Secret absence is not verified; retry or inspect the owned secret manually.")

    def cleanup_tags(self) -> None:
        self.guard()
        command = [
            "gcloud", "artifacts", "docker", "tags", "list",
            PREVIEW_FRONTEND_REPOSITORY, "--format=json",
        ]
        prefix = (
            f"projects/{PREVIEW_PROJECT}/locations/{PREVIEW_REGION}/repositories/"
            "haunted-halls-preview/packages/frontend/tags/"
        )
        def owned_tags() -> list[str]:
            tags = Commands.json(command, label="Preview frontend tag inventory")
            _expect(isinstance(tags, list), "Frontend image tag inventory is malformed.")
            owned = []
            for item in tags:
                _expect(isinstance(item, dict) and isinstance(item.get("tag"), str)
                        and item["tag"].startswith(prefix), "Unexpected frontend tag repository.")
                tag = item["tag"].removeprefix(prefix)
                if re.fullmatch(rf"pr-{self.number}-[0-9a-f]{{40}}-run-[1-9][0-9]*-attempt-[1-9][0-9]*", tag):
                    owned.append(tag)
            return owned

        for tag in owned_tags():
            self.guard()
            Commands.run([
                "gcloud", "artifacts", "docker", "tags", "delete",
                f"{PREVIEW_FRONTEND_REPOSITORY}:{tag}", "--quiet",
            ], label="Owned frontend image tag removal")
        _expect(not owned_tags(), "PR image tags remain; retry tag cleanup.")

    def run(self) -> None:
        self.revalidate()
        self.check_secret_workflow()
        self.initialize()
        self.state = self.read_state()
        incarnation, inventory = validate_state(self.state, self.number)
        if not inventory and incarnation is None:
            absent_services = self.verify_runtime_absent()
            self.verify_runtime_iam_absent({}, absent_services)
            self.progress = (
                "No database deletion attempted without state ownership evidence. "
                "If state was removed out of band, verify orphan databases/secrets manually."
            )
            self.cleanup_tags()
            self.status = "No-op: no tracked preview resources"
            return
        output = identity_output(self.state, self.number)
        database_secret = inventory.get('google_secret_manager_secret.pr["database_url"]')
        database_grant = any(
            address in inventory for address in (
                'google_secret_manager_secret_iam_member.runtime["engine_database"]',
                'google_secret_manager_secret_iam_member.runtime["migrate_database"]',
            )
        )
        database_owned = (
            output is not None and output["pr_incarnation"] == incarnation
        ) or (
            database_secret is not None and database_grant
            and int(database_secret["labels"]["secret_generation"]) > 0
        )
        secrets = [f"hh-web-pr-{self.number}-i-{incarnation}-{suffix}"
                   for suffix in ROLES.values()]
        self.destroy(runtime_only=True)
        absent_services = self.verify_runtime_absent()
        self.verify_runtime_iam_absent(inventory, absent_services)
        self.progress = "Runtime removed and verified; database and secret cleanup pending."
        _expect(database_owned,
                "Database ownership evidence is incomplete. Database and remaining secrets were left intact; manual cleanup required.")
        self.guard()
        result = request_database(self.number, "drop", self.guard)
        _expect(isinstance(result, dict)
                and result.get("database") == derive_database_name(self.number)
                and result.get("operation") == "drop" and type(result.get("dropped")) is bool,
                "Database deletion was not verified; inspect the provisioner and retry.")
        self.progress = "Runtime and database removed (or already absent); secrets pending."
        self.destroy(runtime_only=False)
        self.verify_secrets_absent(secrets)
        self.progress = "Runtime, database and secrets removed; frontend tag cleanup pending."
        self.cleanup_tags()
        self.status = "Removed"
        self.progress = "Runtime, database, owned secrets and frontend image tags cleaned up."

    def report(self, error: str | None) -> None:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        text = (
            f"## Preview Environment\n\n### Teardown: PR #{self.number}\n\n"
            f"**Status:** {self.status}\n\n{self.progress}\n\n"
            f"**Completed at:** {timestamp}\n"
        )
        if error:
            text += f"\n**Action required:** {error}\nRetry manual teardown after correcting the failure; never remove state to bypass ownership checks.\n"
        print(text)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write(text)
        try:
            # Do not let a late reopen or comment failure restart infrastructure work.
            self.revalidate()
            comments = preview_comments(self.github, self.number)
            if comments:
                comment_id = comments[0].get("id")
                _expect(type(comment_id) is int and comment_id > 0, "Invalid preview comment ID.")
                self.github.api(f"repos/{REPOSITORY}/issues/comments/{comment_id}",
                                method="PATCH", data={"body": COMMENT_MARKER + "\n" + text})
        except LifecycleError as failure:
            warning = f"WARNING: Infrastructure status above is unchanged; comment update failed: {failure}\n"
            print(warning, file=sys.stderr)
            if summary:
                with Path(summary).open("a", encoding="utf-8") as stream:
                    stream.write(warning)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--context", required=True)
    parser.add_argument("--event")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    teardown = None
    error = None
    try:
        trusted_context()
        github = Github(os.environ.get("GH_TOKEN", ""))
        if args.command == "prepare":
            prepare(args, github)
        else:
            context = json.loads(Path(args.context).read_text())
            _expect(isinstance(context, dict) and set(context) == {"number", "head_sha", "closed_at"},
                    "Teardown context is malformed.")
            _expect(closed_pr(github, context["number"]) == context,
                    "PR was reopened or changed since teardown preparation.")
            teardown = PreviewTeardown(context, github)
            teardown.run()
    except LifecycleError as failure:
        error = str(failure)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.TimeoutExpired):
        error = "Teardown stopped on invalid metadata or an unavailable tool; inspect the failed step and retry."
    if teardown is not None:
        teardown.report(error)
    elif error:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
