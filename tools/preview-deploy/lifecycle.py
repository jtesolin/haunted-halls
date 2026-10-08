#!/usr/bin/env python3
"""Trusted orchestration for the frontend-only PR preview create/update lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "preview-secret-preparer"))
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "infra/terraform/preview-foundation/db-provisioner"),
)
from db_names import derive_database_name as provisioner_database_name
from terraform_targets import TARGETS
from validate_pr import validate_pr as validate_secret_preparation_pr


REPOSITORY = "jtesolin/haunted-halls"
PREVIEW_PROJECT = "hh-preview-458395246135"
PREVIEW_PROJECT_NUMBER = "1001419903197"
PREVIEW_REGION = "us-east1"
SOURCE_PROJECT = "haunted-halls-development"
SOURCE_REGION = "us-east1"
SOURCE_ENGINE_REPOSITORY = (
    "us-east1-docker.pkg.dev/haunted-halls-development/haunted-halls/engine"
)
PREVIEW_ENGINE_REPOSITORY = (
    "us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/engine"
)
PREVIEW_FRONTEND_REPOSITORY = (
    "us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/frontend"
)
STATE_BUCKET = "hh-preview-458395246135-per-pr-tf-state"
DEPLOYER = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"
SECRET_WORKFLOW = "preview-secret-prepare.yml"
SECRET_ARTIFACT = "preview-secret-version-metadata"
SECRET_ROLES = {"nextauth", "internal_token", "database_url"}
PR_RE = re.compile(r"[1-9][0-9]{0,8}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
INCARNATION_RE = re.compile(r"[0-9a-f]{32}")
VERSION_RE = re.compile(r"[1-9][0-9]*")
STATE_GENERATION_RE = re.compile(r"(?:0|[1-9][0-9]{0,8})")
COMMENT_MARKER = "<!-- haunted-halls-preview-environment -->"
TERRAFORM_ROOT = Path("infra/terraform/preview-pr")


class LifecycleError(Exception):
    """Sanitized, expected lifecycle failure."""


class NoDeployment(LifecycleError):
    """The PR is no longer eligible or a successful build is stale."""


@dataclass(frozen=True)
class BuildContext:
    pull_request_number: str
    head_sha: str
    workflow_run_id: int
    run_attempt: int
    artifact_id: int
    artifact_digest: str
    artifact_name: str
    image_tar: str

    @classmethod
    def from_json(cls, value: object) -> "BuildContext":
        if not isinstance(value, dict):
            raise LifecycleError("Preview provenance context is malformed.")
        try:
            context = cls(**value)
        except (TypeError, ValueError):
            raise LifecycleError("Preview provenance context is malformed.") from None
        if (
            not PR_RE.fullmatch(context.pull_request_number)
            or not SHA_RE.fullmatch(context.head_sha)
            or type(context.workflow_run_id) is not int
            or context.workflow_run_id < 1
            or type(context.run_attempt) is not int
            or context.run_attempt < 1
            or type(context.artifact_id) is not int
            or context.artifact_id < 1
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", context.artifact_digest)
            or not context.artifact_name
            or not Path(context.image_tar).is_absolute()
        ):
            raise LifecycleError("Preview provenance context is malformed.")
        return context


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise LifecycleError(message)


def derive_database_name(pull_request_number: str) -> str:
    _expect(
        isinstance(pull_request_number, str) and PR_RE.fullmatch(pull_request_number),
        "PR number is not canonical.",
    )
    return provisioner_database_name("web", int(pull_request_number))


def eligibility(run: object, pr: object) -> tuple[str, str] | None:
    """Return the current PR number/head or None when a successful run is stale/draft."""
    if not isinstance(run, dict):
        raise LifecycleError("The successful CI run metadata is malformed.")
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list) or len(pull_requests) != 1:
        raise LifecycleError("The CI run is not bound to exactly one frontend PR.")
    linked = pull_requests[0]
    number = linked.get("number") if isinstance(linked, dict) else None
    if type(number) is not int or not PR_RE.fullmatch(str(number)):
        raise LifecycleError("The CI run PR identity is invalid.")
    if not isinstance(pr, dict) or pr.get("state") != "open" or pr.get("draft") is not False:
        return None
    head = pr.get("head")
    base = pr.get("base")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    linked_head = linked.get("head") if isinstance(linked, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (
        not isinstance(head, dict)
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != REPOSITORY
        or not isinstance(base_repo, dict)
        or base_repo.get("full_name") != REPOSITORY
        or not SHA_RE.fullmatch(str(head.get("sha", "")))
        or not isinstance(linked_head, dict)
        or linked_head.get("sha") != head.get("sha")
    ):
        return None
    run_pr = linked.get("number") if isinstance(linked, dict) else None
    pr_number = pr.get("number")
    if type(pr_number) is not int or pr_number != run_pr:
        return None
    return str(number), str(head["sha"])


def artifact_name(number: str, sha: str, attempt: int) -> str:
    _expect(PR_RE.fullmatch(number) is not None, "PR number is not canonical.")
    _expect(SHA_RE.fullmatch(sha) is not None, "PR SHA is invalid.")
    _expect(type(attempt) is int and attempt > 0, "Workflow attempt is invalid.")
    return f"frontend-pr-image-{number}-{sha}-attempt-{attempt}"


def validate_artifact_record(
    run_id: int, expected_name: str, artifacts: object
) -> dict[str, Any]:
    _expect(type(run_id) is int and run_id > 0, "CI workflow run ID is invalid.")
    _expect(isinstance(artifacts, list), "GitHub artifact metadata is malformed.")
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("name") == expected_name]
    _expect(len(matches) == 1, "The exact CI image artifact is missing or ambiguous.")
    artifact = matches[0]
    _expect(artifact.get("expired") is False, "The CI image artifact has expired.")
    _expect(type(artifact.get("id")) is int and artifact["id"] > 0, "Artifact ID is invalid.")
    _expect(
        isinstance(artifact.get("digest"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]),
        "GitHub did not provide an immutable artifact digest.",
    )
    return artifact


def extract_artifact_zip(
    archive: bytes, expected_digest: str, required_files: set[str]
) -> dict[str, bytes]:
    _expect(
        hashlib.sha256(archive).hexdigest() == expected_digest.removeprefix("sha256:"),
        "The downloaded GitHub artifact digest does not match its API provenance.",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            names = source.namelist()
            _expect(
                set(names) == required_files and len(names) == len(required_files),
                "The GitHub artifact contains unexpected or missing files.",
            )
            _expect(
                all(Path(name).name == name and not name.startswith("/") for name in names),
                "The GitHub artifact contains an unsafe file path.",
            )
            return {name: source.read(name) for name in names}
    except (OSError, zipfile.BadZipFile, KeyError):
        raise LifecycleError("The GitHub artifact archive is invalid.") from None


def validate_image_archive(files: dict[str, bytes], number: str, sha: str) -> str:
    _expect(set(files) == {"frontend-image.tar", "frontend-image.tar.sha256"},
            "The frontend image artifact has an invalid file set.")
    image = files["frontend-image.tar"]
    expected = hashlib.sha256(image).hexdigest()
    sidecar = files["frontend-image.tar.sha256"].decode("ascii", errors="strict").strip()
    _expect(
        sidecar == f"{expected}  frontend-image.tar",
        "The frontend image artifact checksum is invalid.",
    )
    return f"hh-web-pr-{number}-frontend:{sha}"


def staging_engine_digest(service: object, revision: object) -> str:
    if not isinstance(service, dict) or not isinstance(revision, dict):
        raise LifecycleError("Staging engine metadata is malformed.")
    service_name = str(service.get("name", service.get("metadata", {}).get("name", "")))
    _expect(
        service_name.rsplit("/", 1)[-1] == "haunted-halls-engine-staging",
        "The staging service is not the expected engine service.",
    )
    service_status = _resource_status(service)
    _expect(_ready(service_status.get("conditions")), "Staging engine service is not Ready.")
    ready_revision = service_status.get("latestReadyRevisionName")
    created_revision = service_status.get("latestCreatedRevisionName")
    _expect(
        isinstance(ready_revision, str)
        and ready_revision
        and isinstance(created_revision, str)
        and ready_revision.rsplit("/", 1)[-1] == created_revision.rsplit("/", 1)[-1],
        "The staging engine does not have one current Ready revision.",
    )
    ready_revision_id = ready_revision.rsplit("/", 1)[-1]
    traffic = service_status.get("trafficStatuses")
    _expect(isinstance(traffic, list), "Staging engine traffic status is unavailable.")
    serving = [
        item for item in traffic
        if isinstance(item, dict) and item.get("percent") == 100
    ]
    _expect(
        len(serving) == 1
        and isinstance(serving[0].get("revision"), str)
        and serving[0]["revision"].rsplit("/", 1)[-1] == ready_revision_id
        and len([item for item in traffic if isinstance(item, dict) and item.get("percent", 0) > 0]) == 1,
        "Staging traffic is not serving exactly the latest Ready engine revision.",
    )
    revision_name = str(revision.get("name", revision.get("metadata", {}).get("name", "")))
    _expect(
        revision_name.rsplit("/", 1)[-1] == ready_revision_id,
        "The described staging revision is not the service's Ready revision.",
    )
    revision_status = _resource_status(revision)
    _expect(
        isinstance(revision_status, dict)
        and _ready(revision_status.get("conditions")),
        "The staging engine revision is not Ready.",
    )
    containers = revision_status.get("containerStatuses")
    digests = [
        item.get("imageDigest")
        for item in containers
        if isinstance(item, dict) and isinstance(item.get("imageDigest"), str)
    ] if isinstance(containers, list) else []
    _expect(
        not isinstance(containers, list) or len(containers) == 1,
        "The staging revision does not have exactly one serving container.",
    )
    if not digests and isinstance(revision_status.get("imageDigest"), str):
        digests.append(revision_status["imageDigest"])
    if not digests and isinstance(revision_status.get("image"), str):
        digests.append(revision_status["image"])
    _expect(len(digests) == 1, "The staging revision does not expose one immutable image digest.")
    image = digests[0]
    _expect(
        image.startswith(f"{SOURCE_ENGINE_REPOSITORY}@")
        and DIGEST_RE.search(image) is not None
        and image.endswith(DIGEST_RE.search(image).group(0)),
        "The staging engine digest is not in the expected source Artifact Registry.",
    )
    return image


def _ready(conditions: object) -> bool:
    if not isinstance(conditions, list):
        return False
    matches = [
        condition for condition in conditions
        if isinstance(condition, dict) and condition.get("type") == "Ready"
    ]
    return len(matches) == 1 and matches[0].get("state", matches[0].get("status")) in {
        "CONDITION_SUCCEEDED",
        "True",
    }


def _resource_status(resource: object) -> dict[str, Any]:
    if not isinstance(resource, dict):
        raise LifecycleError("Cloud Run resource metadata is malformed.")
    status = resource.get("status")
    if isinstance(status, dict):
        normalized = dict(status)
        if "latestReadyRevisionName" not in normalized:
            normalized["latestReadyRevisionName"] = normalized.get("latestReadyRevision")
        if "latestCreatedRevisionName" not in normalized:
            normalized["latestCreatedRevisionName"] = normalized.get("latestCreatedRevision")
        return normalized
    state = resource.get("state")
    if state in {"CONDITION_SUCCEEDED", "True"}:
        return {
            "conditions": [{"type": "Ready", "state": state}],
            "latestReadyRevisionName": resource.get("revision"),
            "url": resource.get("uri"),
            "containerStatuses": [
                {"imageDigest": resource.get("imageDigest")}
            ] if isinstance(resource.get("imageDigest"), str) else [],
            "succeededCount": resource.get("succeededCount"),
        }
    return {}


def state_secret_identity(state: object, number: str) -> tuple[str, int] | None:
    _expect(isinstance(state, dict) and isinstance(state.get("resources"), list),
            "Terraform state is malformed.")
    entries = state["resources"]
    _expect(all(isinstance(item, dict) for item in entries), "Terraform state is malformed.")
    secrets_state = [
        item for item in entries
        if item.get("mode") == "managed"
        and item.get("type") == "google_secret_manager_secret"
        and item.get("name") == "pr"
    ]
    if not secrets_state:
        _expect(not entries, "Terraform state has resources but no PR secret identity.")
        return None
    instances: dict[str, dict[str, Any]] = {}
    for resource in secrets_state:
        for instance in resource.get("instances", []):
            if not isinstance(instance, dict):
                raise LifecycleError("Terraform secret state is malformed.")
            role = instance.get("index_key")
            attributes = instance.get("attributes")
            _expect(
                role in SECRET_ROLES and isinstance(attributes, dict),
                "Terraform secret state has an unexpected role.",
            )
            _expect(role not in instances, "Terraform state has duplicate PR secret roles.")
            instances[role] = attributes
    _expect(bool(instances), "Terraform state has no per-PR secret instances.")
    incarnations: set[str] = set()
    generations: set[str] = set()
    for role, attributes in instances.items():
        secret_id = attributes.get("secret_id")
        labels = attributes.get("labels")
        _expect(isinstance(secret_id, str) and isinstance(labels, dict),
                "Terraform secret state is incomplete.")
        match = re.fullmatch(
            rf"hh-web-pr-{re.escape(number)}-i-([0-9a-f]{{32}})-"
            rf"{'internal-token' if role == 'internal_token' else role.replace('_', '-')}",
            secret_id,
        )
        _expect(match is not None, "Terraform secret state belongs to a different PR.")
        incarnations.add(match.group(1))
        expected_labels = {
            "app": "haunted-halls",
            "environment": "preview",
            "repository": "web",
            "pull_request": number,
            "managed_by": "terraform",
        }
        _expect(
            all(labels.get(key) == value for key, value in expected_labels.items()),
            "Terraform secret labels do not match the preview identity.",
        )
        _expect(
            labels.get("incarnation") == match.group(1),
            "Terraform secret incarnation label differs from its resource name.",
        )
        generation = labels.get("secret_generation")
        _expect(
            isinstance(generation, str) and STATE_GENERATION_RE.fullmatch(generation) is not None,
            "Terraform secret generation is missing or invalid.",
        )
        generations.add(generation)
    _expect(len(incarnations) == 1 and len(generations) == 1,
            "Terraform PR secret incarnation or generation is inconsistent.")
    incarnation = next(iter(incarnations))
    generation = int(next(iter(generations)))
    _expect(len(instances) == len(SECRET_ROLES), "Terraform state has only some PR secret containers.")
    _expect(INCARNATION_RE.fullmatch(incarnation) is not None, "PR incarnation is invalid.")
    return incarnation, generation


def validate_secret_metadata(
    metadata: object, number: str, incarnation: str, generation: int
) -> dict[str, str]:
    _expect(isinstance(metadata, dict), "Secret version artifact is malformed.")
    _expect(
        set(metadata)
        == {
            "pull_request_number",
            "pr_incarnation",
            "generation",
            "state",
            "secret_versions",
        }
        and metadata.get("pull_request_number") == number
        and metadata.get("pr_incarnation") == incarnation
        and metadata.get("generation") == str(generation),
        "Secret version artifact belongs to a different preview generation.",
    )
    _expect(
        metadata.get("state")
        in {"complete", "absent", "reserved", "writing", "reconciliation-required"},
        "Secret version artifact contains an unknown ledger state.",
    )
    versions = metadata.get("secret_versions")
    _expect(
        isinstance(versions, dict)
        and set(versions) <= SECRET_ROLES
        and (
            metadata["state"] != "complete"
            or set(versions) == SECRET_ROLES
        )
        and (
            metadata["state"] != "absent"
            or not versions
        )
        and all(isinstance(value, str) and VERSION_RE.fullmatch(value) for value in versions.values()),
        "Secret preparation did not return exactly three numeric versions.",
    )
    return versions


def select_secret_generation(current: int, reconciliation_state: str) -> int:
    _expect(type(current) is int and 0 <= current < 999_999_999,
            "Current secret generation is invalid.")
    if current == 0:
        _expect(reconciliation_state == "absent", "New preview unexpectedly has secret history.")
        return 1
    if reconciliation_state == "absent":
        return current
    _expect(
        reconciliation_state == "complete",
        "An incomplete secret generation requires explicit operator reconciliation.",
    )
    return current + 1


def validate_database_result(payload: object, expected_database: str) -> bool:
    _expect(
        isinstance(payload, dict)
        and payload.get("database") == expected_database
        and payload.get("operation") == "create"
        and type(payload.get("created")) is bool,
        "The database provisioner returned an unexpected result.",
    )
    return payload["created"]


def validate_plan(plan: object, allowed_addresses: set[str]) -> None:
    _expect(isinstance(plan, dict), "Terraform plan JSON is malformed.")
    changes = plan.get("resource_changes")
    _expect(isinstance(changes, list), "Terraform plan has no resource change inventory.")
    for item in changes:
        _expect(isinstance(item, dict), "Terraform plan contains an invalid resource change.")
        address = item.get("address")
        actions = item.get("change", {}).get("actions") if isinstance(item.get("change"), dict) else None
        base_address = address.split("[", 1)[0] if isinstance(address, str) else None
        _expect(
            base_address in allowed_addresses,
            "Terraform plan addresses an unexpected resource.",
        )
        _expect(
            isinstance(actions, list) and actions and all(isinstance(action, str) for action in actions),
            "Terraform plan contains an invalid action.",
        )
        _expect("delete" not in actions, "Terraform plan would destroy an existing preview resource.")


def execution_succeeded(execution: object) -> bool:
    if not isinstance(execution, dict):
        return False
    status = _resource_status(execution)
    if not isinstance(status, dict) or status.get("succeededCount") != 1:
        return False
    conditions = status.get("conditions")
    if not isinstance(conditions, list):
        return False
    completed = [
        item for item in conditions
        if isinstance(item, dict)
        and item.get("type") in {"Completed", "CompletedCondition"}
    ]
    return len(completed) == 1 and completed[0].get(
        "state", completed[0].get("status")
    ) in {"CONDITION_SUCCEEDED", "True"}


def service_image_and_url(service: object, name: str, expected_image: str) -> str:
    _expect(isinstance(service, dict), "Preview Cloud Run service metadata is malformed.")
    actual_name = str(service.get("name", service.get("metadata", {}).get("name", "")))
    _expect(actual_name.rsplit("/", 1)[-1] == name, "A different Cloud Run service was returned.")
    status = _resource_status(service)
    template = service.get("template")
    configuration = service.get("template") or service.get("spec", {}).get("template")
    if not isinstance(configuration, dict):
        configuration = {}
    _expect(
        isinstance(status, dict)
        and _ready(status.get("conditions"))
        and isinstance(configuration.get("containers"), list)
        and len(configuration["containers"]) == 1,
        "Preview Cloud Run service is not Ready or has unexpected containers.",
    )
    image = configuration["containers"][0].get("image")
    _expect(image == expected_image, "Deployed service image differs from its frozen digest.")
    url = status.get("url") or service.get("uri")
    _expect(isinstance(url, str) and url.startswith("https://"), "Preview Cloud Run URL is unavailable.")
    return url


def comment_body(
    number: str,
    sha: str,
    frontend_image: str,
    staging_engine_image: str,
    preview_engine_image: str,
    database: str,
    database_created: bool | None,
    updated: datetime,
    url: str,
) -> str:
    timestamp = updated.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return "\n".join(
        [
            COMMENT_MARKER,
            "## Preview Environment",
            "",
            "**Status:** Ready",
            f"**Preview URL:** {url}",
            f"**PR head SHA:** `{sha}`",
            f"**Frontend digest:** `{frontend_image}`",
            f"**Frozen staging engine digest:** `{staging_engine_image}`",
            f"**Preview engine digest:** `{preview_engine_image}`",
            f"**PR database:** `{database}` "
            f"({'created' if database_created else 'reused' if database_created is False else 'status unknown'})",
            "**Migration:** Alembic upgrade and head verification succeeded",
            f"**Last updated:** {timestamp}",
            "",
            "This preview is private to the configured IAP testers.",
        ]
    )


class Commands:
    """Small subprocess boundary that never echoes cloud output or arguments."""

    @staticmethod
    def run(
        arguments: list[str],
        *,
        input_data: bytes | None = None,
        label: str,
        timeout: int = 300,
    ) -> bytes:
        try:
            result = subprocess.run(
                arguments,
                input=input_data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise LifecycleError(f"{label} could not be completed.") from None
        if result.returncode != 0:
            raise LifecycleError(f"{label} failed.")
        return result.stdout

    @classmethod
    def json(cls, arguments: list[str], *, label: str, timeout: int = 300) -> Any:
        raw = cls.run(arguments, label=label, timeout=timeout)
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LifecycleError(f"{label} returned invalid metadata.") from None


class Github:
    def __init__(self, token: str):
        _expect(bool(token), "GitHub workflow token is unavailable.")
        self.token = token

    def api(self, endpoint: str, method: str = "GET", data: object | None = None) -> Any:
        arguments = ["gh", "api", "--method", method, endpoint]
        raw_data = None
        if data is not None:
            arguments.extend(["--input", "-"])
            raw_data = json.dumps(data, separators=(",", ":")).encode()
        output = Commands.run(
            arguments,
            input_data=raw_data,
            label="GitHub API request",
            timeout=120,
        )
        if method != "GET":
            return output
        try:
            return json.loads(output)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LifecycleError("GitHub API returned invalid metadata.") from None

    def artifact_zip(self, artifact_id: int, digest: str) -> bytes:
        archive = Commands.run(
            [
                "gh",
                "api",
                f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
            ],
            label="GitHub artifact download",
            timeout=180,
        )
        _expect(
            hashlib.sha256(archive).hexdigest() == digest.removeprefix("sha256:"),
            "GitHub artifact bytes do not match the immutable API digest.",
        )
        return archive


def prepare(args: argparse.Namespace) -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    git_ref = os.environ.get("GITHUB_REF", "")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    _expect(repository == REPOSITORY, "Preview workflow repository is not trusted.")
    _expect(
        workflow_ref == f"{REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main"
        and git_ref == "refs/heads/main"
        and event_name == "workflow_run",
        "Preview deployment did not start in the trusted default-branch workflow.",
    )
    try:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise LifecycleError("The workflow event payload is invalid.") from None
    event_run = event.get("workflow_run") if isinstance(event, dict) else None
    _expect(isinstance(event_run, dict), "The workflow event has no source CI run.")
    run_id = event_run.get("id")
    _expect(type(run_id) is int and run_id > 0, "The source CI run ID is invalid.")

    github = Github(os.environ.get("GH_TOKEN", ""))
    workflow = github.api(f"repos/{REPOSITORY}/actions/workflows/ci.yml")
    run = github.api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    _expect(
        isinstance(workflow, dict)
        and workflow.get("path") == ".github/workflows/ci.yml"
        and type(workflow.get("id")) is int
        and isinstance(run, dict)
        and run.get("workflow_id") == workflow.get("id")
        and run.get("path") == ".github/workflows/ci.yml"
        and run.get("event") == "pull_request"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success",
        "The source run is not a successful run of the trusted frontend CI workflow.",
    )
    _expect(
        isinstance(run.get("head_repository"), dict)
        and run["head_repository"].get("full_name") == REPOSITORY,
        "Fork workflow runs cannot create frontend previews.",
    )
    _expect(
        isinstance(run.get("head_sha"), str) and SHA_RE.fullmatch(run["head_sha"]),
        "The source CI run head SHA is invalid.",
    )
    _expect(
        event_run.get("head_sha") == run.get("head_sha")
        and event_run.get("id") == run.get("id"),
        "The workflow event does not match the exact source CI run.",
    )
    linked_prs = run.get("pull_requests")
    _expect(
        isinstance(linked_prs, list)
        and len(linked_prs) == 1
        and type(linked_prs[0].get("number")) is int
        and isinstance(linked_prs[0].get("head"), dict),
        "The source CI run is not bound to exactly one PR.",
    )
    number = str(linked_prs[0]["number"])
    pr = github.api(f"repos/{REPOSITORY}/pulls/{number}")
    current = eligibility(run, pr)
    output = Path(args.github_output)
    if current is None:
        output.write_text("deploy=false\n", encoding="utf-8")
        return 0
    expected_number, sha = current
    _expect(
        expected_number == number
        and sha == linked_prs[0]["head"].get("sha"),
        "The workflow event, CI run and current PR head do not match.",
    )
    attempt = run.get("run_attempt")
    expected_name = artifact_name(number, sha, attempt)
    artifact_response = github.api(
        f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"
    )
    _expect(
        isinstance(artifact_response, dict),
        "GitHub artifact metadata is malformed.",
    )
    artifact = validate_artifact_record(
        run_id, expected_name, artifact_response.get("artifacts")
    )
    archive = github.artifact_zip(artifact["id"], artifact["digest"])
    files = extract_artifact_zip(
        archive,
        artifact["digest"],
        {"frontend-image.tar", "frontend-image.tar.sha256"},
    )
    image_tar = validate_image_archive(files, number, sha)
    image_path = Path(args.output_directory) / "frontend-image.tar"
    image_path.write_bytes(files["frontend-image.tar"])
    image_path.chmod(0o600)
    loaded = Commands.run(
        ["docker", "load", "--input", str(image_path)],
        label="Untrusted frontend image import",
        timeout=300,
    ).decode("utf-8", errors="replace")
    _expect(
        f"Loaded image: {image_tar}" in loaded,
        "The downloaded image does not contain the expected PR tag.",
    )
    inspect = Commands.json(
        ["docker", "image", "inspect", image_tar],
        label="Frontend artifact inspection",
    )
    _expect(isinstance(inspect, list) and len(inspect) == 1, "Frontend artifact is ambiguous.")
    labels = inspect[0].get("Config", {}).get("Labels")
    _expect(
        isinstance(labels, dict)
        and labels.get("org.opencontainers.image.source") == f"https://github.com/{REPOSITORY}"
        and labels.get("org.opencontainers.image.revision") == sha,
        "Frontend image labels do not bind it to the current repository and PR head.",
    )
    context = BuildContext(
        pull_request_number=number,
        head_sha=sha,
        workflow_run_id=run_id,
        run_attempt=attempt,
        artifact_id=artifact["id"],
        artifact_digest=artifact["digest"],
        artifact_name=expected_name,
        image_tar=str(image_path.resolve()),
    )
    context_path = Path(args.output_directory) / "preview-context.json"
    context_path.write_text(json.dumps(context.__dict__, sort_keys=True), encoding="utf-8")
    context_path.chmod(0o600)
    output.write_text("deploy=true\n", encoding="utf-8")
    return 0


class PreviewDeployment:
    def __init__(self, context: BuildContext, github: Github):
        self.context = context
        self.github = github
        self.number = context.pull_request_number
        self.sha = context.head_sha
        self.database = derive_database_name(self.number)
        self.terraform_root = TERRAFORM_ROOT
        self.tf_data_dir: Path | None = None
        self.values: dict[str, Any] = {}
        self.source_engine_image = ""
        self.preview_engine_image = ""
        self.frontend_image = ""
        self.secret_versions: dict[str, str] = {}
        self.database_was_created: bool | None = None

    def revalidate_pr(self) -> dict[str, Any]:
        metadata = self.github.api(f"repos/{REPOSITORY}/pulls/{self.number}")
        _expect(
            validate_secret_preparation_pr(self.number, metadata, self.sha),
            "The PR is closed, draft, forked, or no longer at the artifact head SHA.",
        )
        return metadata

    def run(self) -> None:
        _expect(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_WORKFLOW_REF")
            == f"{REPOSITORY}/.github/workflows/preview-deploy.yml@refs/heads/main"
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("GITHUB_EVENT_NAME") == "workflow_run",
            "Deployment lost its trusted default-branch context.",
        )
        self.revalidate_pr()
        parse_testers(os.environ.get("PREVIEW_IAP_TESTERS", ""))
        database_provisioner_url()
        self.source_engine_image, self.preview_engine_image = self.freeze_and_copy_engine()
        self.revalidate_pr()
        self.frontend_image = self.publish_frontend_image()
        self.initialize_backend()
        incarnation, current_generation = self.bootstrap_secrets()
        self.revalidate_pr()
        database_created = self.ensure_database()
        self.database_was_created = database_created
        self.secret_versions, generation = self.prepare_secret_generation(
            incarnation,
            current_generation,
        )
        self.revalidate_pr()
        self.prepare_migration_job(incarnation, generation)
        self.revalidate_pr()
        self.run_migration()
        self.revalidate_pr()
        self.apply_runtime(incarnation, generation)
        url = self.verify_runtime(database_created)
        self.revalidate_pr()
        self.update_comment(url)

    def publish_frontend_image(self) -> str:
        tag = (
            f"pr-{self.number}-{self.sha}-run-{self.context.workflow_run_id}"
            f"-attempt-{self.context.run_attempt}"
        )
        destination = f"{PREVIEW_FRONTEND_REPOSITORY}:{tag}"
        image_tar = Path(self.context.image_tar)
        _expect(image_tar.is_file(), "The verified frontend image artifact is unavailable.")
        Commands.run(
            ["gcloud", "auth", "configure-docker", "us-east1-docker.pkg.dev", "--quiet"],
            label="Artifact Registry authentication configuration",
        )
        local_image = f"hh-web-pr-{self.number}-frontend:{self.sha}"
        Commands.run(
            ["docker", "tag", local_image, destination],
            label="Frontend image staging",
        )
        Commands.run(
            ["docker", "push", destination],
            label="Frontend image publication",
            timeout=600,
        )
        metadata = Commands.json(
            ["gcloud", "artifacts", "docker", "images", "describe", destination, "--format=json"],
            label="Frontend artifact digest resolution",
        )
        digest = _artifact_digest(metadata)
        image = f"{PREVIEW_FRONTEND_REPOSITORY}@{digest}"
        self.revalidate_pr()
        return image

    def freeze_and_copy_engine(self) -> tuple[str, str]:
        service = Commands.json(
            [
                "gcloud",
                "run",
                "services",
                "describe",
                "haunted-halls-engine-staging",
                f"--project={SOURCE_PROJECT}",
                f"--region={SOURCE_REGION}",
                "--format=json",
            ],
            label="Staging engine service read",
        )
        service_status = _resource_status(service)
        revision_name = service_status.get("latestReadyRevisionName")
        _expect(isinstance(revision_name, str) and revision_name,
                "Staging engine has no Ready revision.")
        if not str(revision_name).startswith("projects/"):
            revision_name = (
                f"projects/{SOURCE_PROJECT}/locations/{SOURCE_REGION}/revisions/"
                f"{revision_name}"
            )
        revision_id = revision_name.rsplit("/", 1)[-1]
        revision = Commands.json(
            [
                "gcloud",
                "run",
                "revisions",
                "describe",
                revision_id,
                f"--project={SOURCE_PROJECT}",
                f"--region={SOURCE_REGION}",
                "--format=json",
            ],
            label="Staging engine revision read",
        )
        source_image = staging_engine_digest(service, revision)
        digest = source_image.rsplit("@", 1)[1]
        destination_tag = f"{PREVIEW_ENGINE_REPOSITORY}:frozen-{digest.removeprefix('sha256:')}"
        Commands.run(
            [
                "gcloud",
                "artifacts",
                "docker",
                "images",
                "copy",
                source_image,
                f"--destination={destination_tag}",
            ],
            label="Immutable staging engine artifact copy",
            timeout=600,
        )
        copied = Commands.json(
            [
                "gcloud",
                "artifacts",
                "docker",
                "images",
                "describe",
                destination_tag,
                "--format=json",
            ],
            label="Preview engine artifact digest resolution",
        )
        copied_digest = _artifact_digest(copied)
        _expect(
            copied_digest == digest,
            "The preview engine registry copy did not preserve the staging image digest.",
        )
        return source_image, f"{PREVIEW_ENGINE_REPOSITORY}@{copied_digest}"

    def initialize_backend(self) -> None:
        prefix = f"previews/web-pr-{self.number}"
        self.tf_data_dir = (
            Path(os.environ.get("RUNNER_TEMP", "/tmp"))
            / f"terraform-web-pr-{self.number}-run-{self.context.workflow_run_id}"
            f"-attempt-{self.context.run_attempt}"
        )
        self.tf_data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ["TF_DATA_DIR"] = str(self.tf_data_dir)
        Commands.run(
            [
                "terraform",
                f"-chdir={self.terraform_root}",
                "init",
                "-input=false",
                "-no-color",
                "-reconfigure",
                f"-backend-config=bucket={STATE_BUCKET}",
                f"-backend-config=prefix={prefix}",
                f"-backend-config=impersonate_service_account={DEPLOYER}",
            ],
            label="PR Terraform backend initialization",
            timeout=600,
        )
        self.check_backend()
        workspace = Commands.run(
            ["terraform", f"-chdir={self.terraform_root}", "workspace", "show"],
            label="PR Terraform workspace verification",
        ).decode("utf-8", errors="replace").strip()
        _expect(workspace == "default", "Preview state must use the default workspace.")

    def check_backend(self) -> None:
        _expect(self.tf_data_dir is not None, "PR Terraform backend is not initialized.")
        metadata_path = self.tf_data_dir / "terraform.tfstate"
        Commands.run(
            [
                "python",
                "infra/terraform/preview-pr/check_backend.py",
                "web",
                self.number,
                "--metadata",
                str(metadata_path),
            ],
            label="PR Terraform backend identity verification",
        )

    def terraform_state(self) -> dict[str, Any]:
        self.check_backend()
        result = subprocess.run(
            ["terraform", f"-chdir={self.terraform_root}", "state", "pull"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            diagnostic = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            _expect(
                "No state file was found" in diagnostic,
                "The per-PR Terraform state could not be read authoritatively.",
            )
            return {"resources": []}
        try:
            state = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LifecycleError("The per-PR Terraform state is malformed.") from None
        return state

    def bootstrap_secrets(self) -> tuple[str, int]:
        state = self.terraform_state()
        existing = state_secret_identity(state, self.number)
        if existing is None:
            incarnation, generation = secrets.token_hex(16), 0
        else:
            incarnation, generation = existing
        self.values = {
            "pr_incarnation": incarnation,
            "secret_generation": str(generation),
        }
        self.apply_plan(
            "secret-containers",
            self.tf_arguments(
                incarnation,
                generation,
                {"nextauth": "1", "internal_token": "1", "database_url": "1"},
            ),
            set(TARGETS["containers"]),
            allowed=set(TARGETS["containers"]),
        )
        persisted = state_secret_identity(self.terraform_state(), self.number)
        _expect(
            persisted == (incarnation, generation),
            "Terraform did not durably record the preview secret incarnation and generation.",
        )
        return incarnation, generation

    def tf_arguments(
        self,
        incarnation: str,
        generation: int,
        versions: dict[str, str],
    ) -> list[str]:
        testers = parse_testers(os.environ.get("PREVIEW_IAP_TESTERS", ""))
        database_provisioner_url()
        values: dict[str, Any] = {
            "repository_key": "web",
            "pull_request_number": self.number,
            "pr_incarnation": incarnation,
            "secret_generation": str(generation),
            "backend_state_prefix": f"previews/web-pr-{self.number}",
            "preview_project_number": PREVIEW_PROJECT_NUMBER,
            "frontend_image": self.frontend_image,
            "engine_image": self.preview_engine_image,
            "iap_testers": sorted(testers),
            "nextauth_secret_version": versions["nextauth"],
            "internal_engine_service_token_version": versions["internal_token"],
            "database_url_secret_version": versions["database_url"],
        }
        arguments = []
        for name, value in values.items():
            encoded = json.dumps(value, separators=(",", ":")) if isinstance(value, (str, list)) else str(value)
            arguments.append(f"-var={name}={encoded}")
        return arguments

    def apply_plan(
        self,
        name: str,
        variables: list[str],
        targets: set[str],
        *,
        allowed: set[str],
    ) -> None:
        self.check_backend()
        plan_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / f"preview-{self.number}-{name}.tfplan"
        plan_args = [
            "terraform",
            f"-chdir={self.terraform_root}",
            "plan",
            "-input=false",
            "-no-color",
            f"-out={plan_path}",
        ]
        plan_args.extend(f"-target={target}" for target in sorted(targets))
        plan_args.extend(variables)
        Commands.run(plan_args, label=f"{name} Terraform plan", timeout=900)
        plan_json = Commands.json(
            [
                "terraform",
                f"-chdir={self.terraform_root}",
                "show",
                "-json",
                str(plan_path),
            ],
            label=f"{name} Terraform plan inspection",
            timeout=300,
        )
        validate_plan(plan_json, allowed)
        self.check_backend()
        Commands.run(
            [
                "terraform",
                f"-chdir={self.terraform_root}",
                "apply",
                "-input=false",
                "-no-color",
                "-auto-approve",
                str(plan_path),
            ],
            label=f"{name} Terraform apply",
            timeout=900,
        )
        plan_path.unlink(missing_ok=True)

    def ensure_database(self) -> bool:
        url = database_provisioner_url()
        token = Commands.run(
            ["gcloud", "auth", "print-identity-token", f"--audiences={url}"],
            label="Database provisioner identity token",
        ).decode("utf-8", errors="strict").strip()
        _expect(bool(token), "Database provisioner identity token is unavailable.")
        request = urllib.request.Request(
            f"{url}/provision",
            data=json.dumps(
                {
                    "operation": "create",
                    "repository_key": "web",
                    "pull_request_number": int(self.number),
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        del token
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise LifecycleError("The fixed preview database provisioner failed.") from None
        return validate_database_result(payload, self.database)

    def prepare_secret_generation(
        self, incarnation: str, current_generation: int
    ) -> tuple[dict[str, str], int]:
        self.revalidate_pr()
        if current_generation == 0:
            reconciliation = {"state": "absent"}
        else:
            reconciliation = self.run_secret_workflow(
                "reconcile",
                incarnation,
                current_generation,
            )
        generation = select_secret_generation(
            current_generation,
            reconciliation["state"],
        )
        if generation > 999_999_999:
            raise LifecycleError("Secret generation limit was reached.")
        self.apply_plan(
            "secret-generation",
            self.tf_arguments(
                incarnation,
                generation,
                {"nextauth": "1", "internal_token": "1", "database_url": "1"},
            ),
            set(TARGETS["containers"]),
            allowed=set(TARGETS["containers"]),
        )
        persisted = state_secret_identity(self.terraform_state(), self.number)
        _expect(
            persisted == (incarnation, generation),
            "Terraform did not durably record the attempted secret generation.",
        )
        prepared = self.run_secret_workflow("prepare", incarnation, generation)
        _expect(
            prepared.get("state") == "complete",
            "The secret preparer did not complete the requested generation.",
        )
        return prepared["secret_versions"], generation

    def run_secret_workflow(
        self, operation: str, incarnation: str, generation: int
    ) -> dict[str, Any]:
        _expect(operation in {"prepare", "reconcile"}, "Secret workflow operation is invalid.")
        self.revalidate_pr()
        testers = parse_testers(os.environ.get("PREVIEW_IAP_TESTERS", ""))
        _expect(bool(testers), "No explicit preview IAP testers are configured.")
        dispatch_time = time.time()
        title = (
            f"Preview secret preparation {operation} "
            f"PR-{self.number}-{incarnation}-gen-{generation}"
        )
        self.github.api(
            f"repos/{REPOSITORY}/actions/workflows/{SECRET_WORKFLOW}/dispatches",
            method="POST",
            data={
                "ref": "main",
                "inputs": {
                    "operation": operation,
                    "pull_request_number": self.number,
                    "pr_incarnation": incarnation,
                    "generation": str(generation),
                    "expected_head_sha": self.sha,
                },
            },
        )
        run = self.wait_for_secret_workflow(title, dispatch_time)
        artifact_response = self.github.api(
            f"repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts?per_page=100"
        )
        artifact = validate_artifact_record(
            run["id"], SECRET_ARTIFACT, artifact_response.get("artifacts")
        )
        archive = self.github.artifact_zip(artifact["id"], artifact["digest"])
        files = extract_artifact_zip(
            archive,
            artifact["digest"],
            {"secret-version-metadata.json"},
        )
        try:
            metadata = json.loads(files["secret-version-metadata.json"])
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LifecycleError("Secret version artifact is invalid.") from None
        versions = validate_secret_metadata(metadata, self.number, incarnation, generation)
        return {
            "state": metadata["state"],
            "secret_versions": versions,
        }

    def wait_for_secret_workflow(self, expected_title: str, dispatch_time: float) -> dict[str, Any]:
        workflow = self.github.api(f"repos/{REPOSITORY}/actions/workflows/{SECRET_WORKFLOW}")
        _expect(
            isinstance(workflow, dict)
            and type(workflow.get("id")) is int
            and workflow.get("path") == f".github/workflows/{SECRET_WORKFLOW}",
            "The trusted secret-preparation workflow identity is unavailable.",
        )
        endpoint = (
            f"repos/{REPOSITORY}/actions/workflows/{SECRET_WORKFLOW}/runs"
            "?event=workflow_dispatch&per_page=100"
        )
        deadline = time.monotonic() + 15 * 60
        matched_id: int | None = None
        while time.monotonic() < deadline:
            response = self.github.api(endpoint)
            _expect(
                isinstance(response, dict) and isinstance(response.get("workflow_runs"), list),
                "Secret-preparation workflow metadata is malformed.",
            )
            candidates = [
                item for item in response["workflow_runs"]
                if isinstance(item, dict)
                and item.get("display_title") == expected_title
                and item.get("event") == "workflow_dispatch"
                and item.get("head_branch") == "main"
                and item.get("workflow_id") == workflow["id"]
                and isinstance(item.get("created_at"), str)
                and _parse_time(item["created_at"]).timestamp() >= dispatch_time - 30
            ]
            _expect(len(candidates) <= 1, "Secret-preparation dispatch is ambiguous.")
            if candidates:
                run = candidates[0]
                matched_id = run.get("id")
                if run.get("status") == "completed":
                    _expect(
                        run.get("conclusion") == "success"
                        and type(matched_id) is int
                        and matched_id > 0
                        and run.get("path") == f".github/workflows/{SECRET_WORKFLOW}",
                        "The trusted secret-preparation workflow did not complete successfully.",
                    )
                    return run
            time.sleep(10)
        del matched_id
        raise LifecycleError("The trusted secret-preparation workflow did not finish in time.")

    def prepare_migration_job(self, incarnation: str, generation: int) -> None:
        self.apply_plan(
            "migration-prerequisites",
            self.tf_arguments(incarnation, generation, self.secret_versions),
            set(TARGETS["migration"]),
            allowed={
                *TARGETS["containers"],
                *TARGETS["migration"],
            },
        )

    def run_migration(self) -> None:
        job = f"hh-web-pr-{self.number}-migrate"
        result = Commands.json(
            [
                "gcloud",
                "run",
                "jobs",
                "execute",
                job,
                f"--project={PREVIEW_PROJECT}",
                f"--region={PREVIEW_REGION}",
                "--wait",
                "--format=json",
            ],
            label="Alembic migration execution",
            timeout=900,
        )
        _expect(isinstance(result, dict), "Migration execution metadata is malformed.")
        execution_name = result.get("name")
        if not isinstance(execution_name, str):
            metadata = result.get("metadata")
            execution_name = metadata.get("name") if isinstance(metadata, dict) else None
        _expect(isinstance(execution_name, str) and execution_name,
                "Migration execution name is unavailable.")
        execution_id = execution_name.rsplit("/", 1)[-1]
        execution = Commands.json(
            [
                "gcloud",
                "run",
                "jobs",
                "executions",
                "describe",
                execution_id,
                f"--project={PREVIEW_PROJECT}",
                f"--region={PREVIEW_REGION}",
                "--format=json",
            ],
            label="Alembic migration result verification",
        )
        _expect(
            execution_succeeded(execution),
            "Alembic migration did not complete successfully at head.",
        )

    def apply_runtime(self, incarnation: str, generation: int) -> None:
        allowed = {
            "google_secret_manager_secret.pr",
            "google_secret_manager_secret_iam_member.runtime",
            "google_cloud_run_v2_job.migration",
            "google_cloud_run_v2_service.engine",
            "google_cloud_run_v2_service.frontend",
            "google_cloud_run_v2_service_iam_member.engine_frontend",
            "google_cloud_run_v2_service_iam_member.frontend_iap",
            "google_iap_web_cloud_run_service_iam_member.tester",
        }
        self.apply_plan(
            "runtime-rollout",
            self.tf_arguments(incarnation, generation, self.secret_versions),
            set(),
            allowed=allowed,
        )

    def verify_runtime(self, database_created: bool) -> str:
        output = Commands.json(
            ["terraform", f"-chdir={self.terraform_root}", "output", "-json", "preview_identity"],
            label="Preview Terraform output verification",
        )
        _expect(isinstance(output, dict), "Preview Terraform identity output is malformed.")
        _expect(
            output.get("database_name") == self.database
            and output.get("repository_key") == "web"
            and output.get("pr_number") == self.number,
            "Preview Terraform identity output does not match this PR.",
        )
        expected_frontend = output.get("frontend_image")
        expected_engine = output.get("engine_image")
        _expect(
            expected_frontend == self.frontend_image
            and expected_engine == self.preview_engine_image,
            "Terraform does not record the exact frontend and frozen engine digests.",
        )
        frontend_name = f"hh-web-pr-{self.number}-frontend"
        engine_name = f"hh-web-pr-{self.number}-engine"
        frontend = Commands.json(
            [
                "gcloud", "run", "services", "describe", frontend_name,
                f"--project={PREVIEW_PROJECT}", f"--region={PREVIEW_REGION}", "--format=json",
            ],
            label="Frontend service readiness verification",
        )
        engine = Commands.json(
            [
                "gcloud", "run", "services", "describe", engine_name,
                f"--project={PREVIEW_PROJECT}", f"--region={PREVIEW_REGION}", "--format=json",
            ],
            label="Engine service readiness verification",
        )
        url = service_image_and_url(frontend, frontend_name, self.frontend_image)
        service_image_and_url(engine, engine_name, self.preview_engine_image)
        _expect(
            frontend.get("iapEnabled") is True
            and url.startswith("https://")
            and urllib.parse.urlparse(url).hostname
            == f"{frontend_name}-{PREVIEW_PROJECT_NUMBER}.{PREVIEW_REGION}.run.app",
            "The frontend IAP URL or direct Cloud Run configuration is unexpected.",
        )
        self.verify_testers()
        verify_unauthenticated_denied(
            f"{url}/", allow_google_redirect=True
        )
        engine_url = output.get("engine_url")
        _expect(isinstance(engine_url, str) and engine_url.startswith("https://"),
                "Preview engine URL is unavailable.")
        verify_unauthenticated_denied(f"{engine_url}/health", allow_google_redirect=False)
        _expect(
            type(database_created) is bool and self.database_was_created == database_created,
            "Database create/reuse status is malformed.",
        )
        return url

    def verify_testers(self) -> None:
        state = self.terraform_state()
        resources = state.get("resources", [])
        members: set[str] = set()
        for resource in resources:
            if (
                isinstance(resource, dict)
                and resource.get("mode") == "managed"
                and resource.get("type") == "google_iap_web_cloud_run_service_iam_member"
                and resource.get("name") == "tester"
            ):
                for instance in resource.get("instances", []):
                    attributes = instance.get("attributes", {}) if isinstance(instance, dict) else {}
                    member = attributes.get("member") if isinstance(attributes, dict) else None
                    _expect(
                        isinstance(attributes, dict)
                        and attributes.get("role") == "roles/iap.httpsResourceAccessor"
                        and attributes.get("cloud_run_service_name")
                        == f"hh-web-pr-{self.number}-frontend"
                        and attributes.get("project") == PREVIEW_PROJECT
                        and attributes.get("location") == PREVIEW_REGION
                        and isinstance(member, str),
                        "IAP tester state contains a grant on an unexpected resource.",
                    )
                    members.add(member)
        _expect(
            members == parse_testers(os.environ.get("PREVIEW_IAP_TESTERS", "")),
            "IAP tester grants differ from the explicitly configured tester set.",
        )

    def update_comment(self, url: str) -> None:
        comments: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self.github.api(
                f"repos/{REPOSITORY}/issues/{self.number}/comments?per_page=100&page={page}"
            )
            _expect(isinstance(batch, list), "PR comment metadata is malformed.")
            comments.extend(
                item for item in batch
                if isinstance(item, dict)
                and isinstance(item.get("body"), str)
                and COMMENT_MARKER in item["body"]
            )
            if len(batch) < 100:
                break
            page += 1
        _expect(len(comments) <= 1, "Multiple Preview Environment comments already exist.")
        body = comment_body(
            self.number,
            self.sha,
            self.frontend_image,
            self.source_engine_image,
            self.preview_engine_image,
            self.database,
            self.database_was_created,
            datetime.now(timezone.utc),
            url,
        )
        if comments:
            comment_id = comments[0].get("id")
            _expect(type(comment_id) is int and comment_id > 0, "Preview comment ID is invalid.")
            endpoint = f"repos/{REPOSITORY}/issues/comments/{comment_id}"
            self.github.api(endpoint, method="PATCH", data={"body": body})
        else:
            self.github.api(
                f"repos/{REPOSITORY}/issues/{self.number}/comments",
                method="POST",
                data={"body": body},
            )


def _artifact_digest(metadata: object) -> str:
    if not isinstance(metadata, dict):
        raise LifecycleError("Artifact Registry returned malformed metadata.")
    summary = metadata.get("image_summary")
    digest = summary.get("digest") if isinstance(summary, dict) else None
    _expect(
        isinstance(digest, str) and DIGEST_RE.fullmatch(digest),
        "Artifact Registry did not return an immutable sha256 digest.",
    )
    return digest


def parse_testers(value: str) -> set[str]:
    members = {item.strip() for item in value.split(",") if item.strip()}
    _expect(bool(members), "No explicit preview IAP testers are configured.")
    _expect(
        all(re.fullmatch(r"(?:user|group):[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", item)
            for item in members),
        "Preview IAP tester configuration must contain only explicit user/group email principals.",
    )
    return members


def database_provisioner_url() -> str:
    value = os.environ.get("PREVIEW_DB_PROVISIONER_URL", "")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        port = -1
    _expect(
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.endswith(".run.app")
        and parsed.hostname.count(".") >= 2
        and port is None
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password,
        "The fixed preview DB provisioner URL is missing or invalid.",
    )
    return value.rstrip("/")


def verify_unauthenticated_denied(url: str, allow_google_redirect: bool) -> None:
    request = urllib.request.Request(url, method="GET")
    status: int | None = None
    location = ""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                             headers: Any, new_url: str) -> None:
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=20) as response:
            status = response.status
            location = response.headers.get("Location", "")
    except urllib.error.HTTPError as error:
        status = error.code
        location = error.headers.get("Location", "")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LifecycleError("Unauthenticated Cloud Run privacy verification failed.") from None
    allowed = {401, 403}
    if allow_google_redirect and status == 302:
        host = urllib.parse.urlparse(location).hostname or ""
        _expect(
            host == "google.com" or host.endswith(".google.com"),
            "Unauthenticated frontend redirect is not the Google IAP sign-in flow.",
        )
        return
    _expect(status in allowed, "Unauthenticated request was not denied by IAP or Cloud Run IAM.")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise LifecycleError("GitHub workflow time metadata is invalid.") from None


def deploy(args: argparse.Namespace) -> int:
    try:
        context_json = json.loads(Path(args.context).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise LifecycleError("Preview deployment context is invalid.") from None
    context = BuildContext.from_json(context_json)
    github = Github(os.environ.get("GH_TOKEN", ""))
    PreviewDeployment(context, github).run()
    print("Preview Environment verified and updated.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--event", required=True)
    prepare_parser.add_argument("--output-directory", required=True)
    prepare_parser.add_argument("--github-output", required=True)
    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--context", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "prepare":
            return prepare(arguments)
        return deploy(arguments)
    except NoDeployment:
        return 0
    except LifecycleError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("ERROR: Preview lifecycle stopped on an unexpected sanitized failure.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
