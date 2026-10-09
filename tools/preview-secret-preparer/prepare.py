#!/usr/bin/env python3
"""Trusted, single-attempt preparation of disposable frontend preview secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

PREVIEW_PROJECT_ID = "hh-preview-458395246135"
PREVIEW_PROJECT_NUMBER = "1001419903197"
PREPARER_SERVICE_ACCOUNT = (
    "hh-preview-secret-preparer@hh-preview-458395246135.iam.gserviceaccount.com"
)
LEDGER_BUCKET = "hh-preview-458395246135-pr-secret-ledger"
DB_PASSWORD_SECRET = (
    "projects/1001419903197/secrets/hh-preview-db-app-password/versions/latest"
)
SQL_SOCKET = (
    "/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
)
ROLES = ("nextauth", "internal_token", "database_url")
PR_RE = re.compile(r"^[1-9][0-9]{0,8}$")
INCARNATION_RE = re.compile(r"^[0-9a-f]{32}$")
GENERATION_RE = re.compile(r"^[1-9][0-9]{0,8}$")
VERSION_RE = re.compile(r"^[1-9][0-9]*$")
PASSWORD_RE = re.compile(rb"^[0-9a-f]{64}$")
SECRET_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,253}[a-z0-9]$")
KNOWN_SECRET_KEYS = {
    "schema_version",
    "repository_key",
    "pull_request_number",
    "pr_incarnation",
    "generation",
    "secret_names",
    "state",
    "current_role",
    "secret_versions",
}


class PreparationError(Exception):
    """A sanitized, expected failure safe to display in workflow logs."""


class ReservationConflict(PreparationError):
    pass


class LedgerError(PreparationError):
    pass


class SecretManagerWriteOutcomeUnknown(PreparationError):
    pass


class ReconciliationRequired(PreparationError):
    pass


@dataclass(frozen=True)
class Identity:
    repository_key: str
    pull_request_number: str
    pr_incarnation: str
    generation: int


def validate_identity(
    repository_key: str, pull_request_number: str, pr_incarnation: str, generation: str
) -> Identity:
    if repository_key != "web":
        raise PreparationError("repository_key must be exactly 'web'.")
    if not PR_RE.fullmatch(pull_request_number):
        raise PreparationError("pull_request_number must be canonical decimal 1..999999999.")
    if not INCARNATION_RE.fullmatch(pr_incarnation):
        raise PreparationError("pr_incarnation must be 32 lowercase hexadecimal characters.")
    if not GENERATION_RE.fullmatch(generation):
        raise PreparationError("generation must be canonical decimal 1..999999999.")
    return Identity(repository_key, pull_request_number, pr_incarnation, int(generation))


def validate_runtime_context(project_id: str, project_number: str, service_account: str) -> None:
    if project_id != PREVIEW_PROJECT_ID:
        raise PreparationError("The active Google Cloud project is not the fixed preview project.")
    if str(project_number) != PREVIEW_PROJECT_NUMBER:
        raise PreparationError("The active Google Cloud project number is not the accepted preview number.")
    if service_account != PREPARER_SERVICE_ACCOUNT:
        raise PreparationError("The active identity is not the fixed preview secret preparer.")


def secret_names(identity: Identity) -> dict[str, str]:
    prefix = (
        f"hh-web-pr-{identity.pull_request_number}"
        f"-i-{identity.pr_incarnation}"
    )
    names = {
        "nextauth": f"{prefix}-nextauth",
        "internal_token": f"{prefix}-internal-token",
        "database_url": f"{prefix}-database-url",
    }
    if any(not SECRET_ID_RE.fullmatch(name) for name in names.values()):
        raise PreparationError("Derived Secret Manager container name is invalid.")
    return names


def database_name(identity: Identity) -> str:
    name = f"haunted_halls_web_pr_{identity.pull_request_number}"
    if not re.fullmatch(r"haunted_halls_web_pr_[1-9][0-9]{0,8}", name):
        raise PreparationError("Derived preview database name is invalid.")
    return name


def database_url(identity: Identity, password: bytearray) -> bytearray:
    if not PASSWORD_RE.fullmatch(password):
        raise PreparationError("The durable preview app password has an invalid format.")
    return bytearray(
        b"postgresql+psycopg://haunted_halls_preview_app:"
        + password
        + b"@/"
        + database_name(identity).encode("ascii")
        + b"?host="
        + SQL_SOCKET.encode("ascii")
    )


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _validate_record(record: dict[str, Any], identity: Identity, names: dict[str, str]) -> None:
    if set(record) != KNOWN_SECRET_KEYS:
        raise LedgerError("The ledger record has an unsupported or unsafe shape.")
    if (
        record["schema_version"] != 1
        or record["repository_key"] != identity.repository_key
        or record["pull_request_number"] != identity.pull_request_number
        or record["pr_incarnation"] != identity.pr_incarnation
        or record["secret_names"] != names
    ):
        raise LedgerError("The ledger record belongs to a different preview identity.")
    if not GENERATION_RE.fullmatch(str(record["generation"])):
        raise LedgerError("The ledger generation is malformed.")
    if record["state"] not in {
        "reserved",
        "writing",
        "complete",
        "reconciliation-required",
    }:
        raise LedgerError("The ledger state is malformed.")
    if record["current_role"] not in (None, *ROLES):
        raise LedgerError("The ledger append intent is malformed.")
    versions = record["secret_versions"]
    if not isinstance(versions, dict) or not set(versions) <= set(ROLES):
        raise LedgerError("The ledger version metadata is malformed.")
    if any(not isinstance(value, str) or not VERSION_RE.fullmatch(value)
           for value in versions.values()):
        raise LedgerError("The ledger contains a non-numeric Secret Manager version.")
    if record["state"] == "complete" and (
        set(versions) != set(ROLES) or record["current_role"] is not None
    ):
        raise LedgerError("A complete ledger record must contain all three versions and no active append.")


class GcsLedger:
    """Deterministic immutable markers, requiring only object GET and CREATE."""

    def __init__(self, bucket: Any):
        self.bucket = bucket

    @staticmethod
    def object_name(identity: Identity, marker: str = "reservation") -> str:
        return (
            f"secret-preparation/v1/web-pr-{identity.pull_request_number}/"
            f"{identity.pr_incarnation}/generations/{identity.generation}/{marker}.json"
        )

    @staticmethod
    def content(identity: Identity, names: dict[str, str], marker: str,
                version: str | None = None, reservation_id: str | None = None) -> dict[str, Any]:
        record = {
            "schema_version": 1,
            "repository_key": identity.repository_key,
            "pull_request_number": identity.pull_request_number,
            "pr_incarnation": identity.pr_incarnation,
            "generation": identity.generation,
            "secret_names": names,
            "marker": marker,
        }
        if version is not None:
            record["version"] = version
        if reservation_id is not None:
            record["reservation_id"] = reservation_id
        return record

    def _get(self, identity: Identity, marker: str) -> dict[str, Any] | None:
        from google.api_core.exceptions import GoogleAPICallError, NotFound
        try:
            data = self.bucket.blob(self.object_name(identity, marker)).download_as_bytes(
                retry=None, timeout=30
            )
        except NotFound:
            return None
        except (GoogleAPICallError, TimeoutError, ConnectionError, OSError):
            raise LedgerError("Could not authoritatively read the immutable ledger marker.") from None
        try:
            record = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LedgerError("The durable ledger marker is unreadable.") from None
        if not isinstance(record, dict):
            raise LedgerError("The durable ledger marker is malformed.")
        return record

    def _create(self, identity: Identity, names: dict[str, str], marker: str,
                version: str | None = None) -> None:
        from google.api_core.exceptions import GoogleAPICallError, PreconditionFailed
        expected = self.content(
            identity, names, marker, version,
            secrets.token_hex(16) if marker == "reservation" else None,
        )
        try:
            self.bucket.blob(self.object_name(identity, marker)).upload_from_string(
                json.dumps(expected, sort_keys=True, separators=(",", ":")),
                content_type="application/json",
                if_generation_match=0,
                retry=None,
                timeout=30,
            )
        except PreconditionFailed:
            raise ReservationConflict("The immutable ledger marker already exists; do not replay.") from None
        except (GoogleAPICallError, TimeoutError, ConnectionError, OSError):
            # Only this invocation's uncertain create may be adopted, never a replay.
            if self._get(identity, marker) == expected:
                return
            raise LedgerError("Immutable marker creation was not established; do not retry.") from None

    def _marker(self, identity: Identity, names: dict[str, str], marker: str,
                result: bool = False) -> dict[str, Any] | None:
        record = self._get(identity, marker)
        if record is None:
            return None
        version = record.get("version") if result else None
        reservation_id = record.get("reservation_id") if marker == "reservation" else None
        if marker == "reservation" and (
            not isinstance(reservation_id, str) or not INCARNATION_RE.fullmatch(reservation_id)
        ):
            raise LedgerError("The immutable reservation identifier is malformed.")
        if result and (not isinstance(version, str) or not VERSION_RE.fullmatch(version)):
            raise LedgerError("The immutable result contains a non-numeric version.")
        if (type(record.get("generation")) is not int
                or type(record.get("schema_version")) is not int
                or record != self.content(identity, names, marker, version, reservation_id)):
            raise LedgerError("The immutable ledger marker has mismatched or unsafe content.")
        return record

    def reserve(self, identity: Identity, names: dict[str, str]) -> None:
        if identity.generation > 1:
            previous = self.read(replace(identity, generation=identity.generation - 1), names)
            if previous is None or previous["state"] != "complete":
                raise ReservationConflict("The preceding generation is not complete; no takeover allowed.")
        self._create(identity, names, "reservation")

    def intent(self, identity: Identity, names: dict[str, str], role: str) -> None:
        self._create(identity, names, f"{role.replace('_', '-')}.intent")

    def result(self, identity: Identity, names: dict[str, str], role: str, version: str) -> None:
        if not VERSION_RE.fullmatch(version):
            raise LedgerError("The append returned a non-numeric version.")
        self._create(identity, names, f"{role.replace('_', '-')}.result", version)

    def require_reconciliation(self, identity: Identity, names: dict[str, str]) -> None:
        self._create(identity, names, "reconciliation-required")

    def complete(self, identity: Identity, names: dict[str, str]) -> None:
        record = self.read(identity, names)
        if (record is None or set(record["secret_versions"]) != set(ROLES)
                or record["state"] == "reconciliation-required"):
            raise LedgerError("Completion requires all three durable results without ambiguity.")
        self._create(identity, names, "complete")

    def read(self, identity: Identity, names: dict[str, str]) -> dict[str, Any] | None:
        reservation = self._marker(identity, names, "reservation")
        versions = {}
        current_role = None
        started = False
        for role in ROLES:
            marker = role.replace("_", "-")
            intent = self._marker(identity, names, f"{marker}.intent")
            result = self._marker(identity, names, f"{marker}.result", result=True)
            if result is not None and intent is None:
                raise LedgerError("A result exists without its durable intent.")
            if intent is not None:
                if len(versions) != ROLES.index(role):
                    raise LedgerError("An append intent exists before preceding durable results.")
                started = True
                if result is None:
                    current_role = role
                else:
                    versions[role] = result["version"]
        ambiguous = self._marker(identity, names, "reconciliation-required")
        complete = self._marker(identity, names, "complete")
        if reservation is None:
            if started or ambiguous is not None or complete is not None:
                raise LedgerError("Generation markers exist without a reservation.")
            return None
        if complete is not None and (
            set(versions) != set(ROLES) or ambiguous is not None or current_role is not None
        ):
            raise LedgerError("The complete marker conflicts with generation state.")
        state = "reserved"
        if started:
            state = "writing"
        if ambiguous is not None or current_role is not None:
            state = "reconciliation-required"
        if complete is not None:
            state = "complete"
        record = {
            **{key: value for key, value in reservation.items()
               if key not in {"marker", "reservation_id"}},
            "state": state,
            "current_role": current_role,
            "secret_versions": versions,
        }
        _validate_record(record, identity, names)
        return record


class SecretManagerGateway:
    def __init__(self, client: Any):
        self.client = client

    @staticmethod
    def resource_name(secret_id: str) -> str:
        return f"projects/{PREVIEW_PROJECT_NUMBER}/secrets/{secret_id}"

    @staticmethod
    def numeric_version(secret_id: str, resource_name: str) -> str:
        prefix = (
            f"projects/{PREVIEW_PROJECT_NUMBER}/secrets/{secret_id}/versions/"
        )
        if not resource_name.startswith(prefix):
            raise SecretManagerWriteOutcomeUnknown(
                "Secret Manager returned a version for an unexpected secret."
            )
        version = resource_name[len(prefix):]
        if not VERSION_RE.fullmatch(version):
            raise SecretManagerWriteOutcomeUnknown(
                "Secret Manager returned no usable numeric version identifier."
            )
        return version

    def labels(self, secret_id: str) -> dict[str, str]:
        secret = self.client.get_secret(request={"name": self.resource_name(secret_id)})
        return dict(secret.labels)

    def add_version(self, secret_id: str, payload: bytearray) -> str:
        from google.api_core.exceptions import GoogleAPICallError

        try:
            result = self.client.add_secret_version(
                request={
                    "parent": self.resource_name(secret_id),
                    "payload": {"data": bytes(payload)},
                },
                retry=None,
                timeout=30,
            )
        except (GoogleAPICallError, TimeoutError, ConnectionError, OSError):
            raise SecretManagerWriteOutcomeUnknown(
                "Secret Manager did not provide an authoritative addVersion response."
            ) from None
        return self.numeric_version(secret_id, result.name)

    def access_database_password(self) -> bytearray:
        result = self.client.access_secret_version(request={"name": DB_PASSWORD_SECRET})
        return bytearray(result.payload.data)

    def version_metadata(self, secret_id: str) -> list[dict[str, str]]:
        result = []
        for version in self.client.list_secret_versions(
            request={"parent": self.resource_name(secret_id)}
        ):
            number = version.name.rsplit("/", 1)[-1]
            if not VERSION_RE.fullmatch(number):
                raise PreparationError("Secret Manager returned malformed version metadata.")
            create_time = version.create_time
            if isinstance(create_time, datetime):
                create_time = create_time.isoformat()
            result.append(
                {
                    "version": number,
                    "state": getattr(version.state, "name", str(version.state)),
                    "create_time": str(create_time),
                }
            )
        return result


def _check_labels(labels: dict[str, str], identity: Identity) -> None:
    expected = {
        "app": "haunted-halls",
        "environment": "preview",
        "repository": identity.repository_key,
        "pull_request": identity.pull_request_number,
        "incarnation": identity.pr_incarnation,
        "managed_by": "terraform",
    }
    if any(labels.get(key) != value for key, value in expected.items()):
        raise PreparationError("A Secret Manager container has missing or mismatched ownership labels.")


class SecretPreparer:
    def __init__(self, ledger: Any, secrets_gateway: Any):
        self.ledger = ledger
        self.secrets = secrets_gateway

    def _preflight(self, identity: Identity, names: dict[str, str]) -> None:
        for role in ROLES:
            _check_labels(self.secrets.labels(names[role]), identity)

    def prepare(self, identity: Identity) -> dict[str, Any]:
        names = secret_names(identity)
        self._preflight(identity, names)
        versions = {}

        nextauth = bytearray()
        internal_token = bytearray()
        password = bytearray()
        db_url = bytearray()
        try:
            nextauth = bytearray(secrets.token_hex(32).encode("ascii"))
            internal_token = bytearray(secrets.token_hex(32).encode("ascii"))
            if (not PASSWORD_RE.fullmatch(nextauth)
                    or not PASSWORD_RE.fullmatch(internal_token)
                    or nextauth == internal_token):
                raise PreparationError("Independent secret generation failed.")
            password = self.secrets.access_database_password()
            db_url = database_url(identity, password)
            payloads = {
                "nextauth": nextauth,
                "internal_token": internal_token,
                "database_url": db_url,
            }
            self.ledger.reserve(identity, names)
            for role in ROLES:
                try:
                    self.ledger.intent(identity, names, role)
                except (LedgerError, ReservationConflict):
                    self._stop(identity, names, "The append intent was not durably established.")
                try:
                    version = self.secrets.add_version(names[role], payloads[role])
                except SecretManagerWriteOutcomeUnknown:
                    self._stop(identity, names, "The Secret Manager write outcome is unknown.")
                try:
                    self.ledger.result(identity, names, role, version)
                except (LedgerError, ReservationConflict):
                    self._stop(identity, names, "A version result was not durably established.")
                versions[role] = version
            try:
                self.ledger.complete(identity, names)
            except (LedgerError, ReservationConflict):
                self._stop(identity, names, "Generation completion was not durably established.")
        finally:
            _wipe(nextauth)
            _wipe(internal_token)
            _wipe(password)
            _wipe(db_url)

        return {
            "repository_key": identity.repository_key,
            "pull_request_number": identity.pull_request_number,
            "pr_incarnation": identity.pr_incarnation,
            "generation": identity.generation,
            "state": "complete",
            "secret_names": names,
            "secret_versions": versions,
        }

    def _stop(self, identity: Identity, names: dict[str, str], reason: str) -> None:
        try:
            self.ledger.require_reconciliation(identity, names)
        except (LedgerError, ReservationConflict):
            raise ReconciliationRequired(
                f"{reason} Reconciliation marker unavailable; reservation still blocks replay. Do not retry."
            ) from None
        raise ReconciliationRequired(f"{reason} Reconcile; do not retry.") from None

    def reconcile(self, identity: Identity) -> dict[str, Any]:
        names = secret_names(identity)
        self._preflight(identity, names)
        record = self.ledger.read(identity, names)
        if record is None:
            return {
                "repository_key": identity.repository_key,
                "pull_request_number": identity.pull_request_number,
                "pr_incarnation": identity.pr_incarnation,
                "generation": identity.generation,
                "state": "absent",
                "in_flight_role": None,
                "secret_names": names,
                "secret_versions": {},
                "observed_version_metadata": {},
                "automatic_resume_allowed": False,
                "operator_disposition_required": False,
            }
        if int(record["generation"]) != identity.generation:
            raise PreparationError("The ledger currently contains a different generation.")
        versions = {
            role: self.secrets.version_metadata(names[role])
            for role in ROLES
        }
        recorded = record["secret_versions"]
        for role in ROLES:
            for item in versions[role]:
                item["recorded"] = item["version"] == recorded.get(role)
        unresolved = record["state"] != "complete"
        return {
            "repository_key": identity.repository_key,
            "pull_request_number": identity.pull_request_number,
            "pr_incarnation": identity.pr_incarnation,
            "generation": identity.generation,
            "state": record["state"],
            "in_flight_role": record["current_role"],
            "secret_names": names,
            "secret_versions": recorded,
            "observed_version_metadata": versions,
            "automatic_resume_allowed": False,
            "operator_disposition_required": unresolved,
        }


def _credential_service_account(credentials: Any) -> str:
    identity = (
        getattr(credentials, "service_account_email", None)
        or getattr(credentials, "target_principal", None)
        or getattr(credentials, "_target_principal", None)
    )
    if identity:
        return str(identity)
    impersonation_url = getattr(credentials, "service_account_impersonation_url", "") or ""
    match = re.search(r"/serviceAccounts/([^/:]+):generateAccessToken$", impersonation_url)
    if match:
        return match.group(1)
    raise PreparationError("The active credentials do not identify an impersonated service account.")


def _build_runtime() -> tuple[GcsLedger, SecretManagerGateway]:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    from google.cloud import secretmanager, storage

    if os.environ.get("GOOGLE_CLOUD_PROJECT") != PREVIEW_PROJECT_ID:
        raise PreparationError("GOOGLE_CLOUD_PROJECT must be the fixed preview project.")
    credentials, _ = google.auth.default()
    service_account = _credential_service_account(credentials)
    session = AuthorizedSession(credentials)
    try:
        response = session.get(
            f"https://cloudresourcemanager.googleapis.com/v3/projects/{PREVIEW_PROJECT_ID}",
            timeout=20,
        )
    except (TimeoutError, ConnectionError, OSError):
        raise PreparationError("Could not verify the preview project identity.") from None
    if response.status_code != 200:
        raise PreparationError("Could not verify the preview project identity.")
    try:
        project_number = str(response.json()["projectNumber"])
    except (KeyError, TypeError, ValueError):
        raise PreparationError("The preview project identity response was malformed.") from None
    validate_runtime_context(PREVIEW_PROJECT_ID, project_number, service_account)
    return (
        GcsLedger(storage.Client(project=PREVIEW_PROJECT_ID, credentials=credentials).bucket(LEDGER_BUCKET)),
        SecretManagerGateway(
            secretmanager.SecretManagerServiceClient(credentials=credentials)
        ),
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="preview-secret-preparer")
    parser.add_argument("mode", choices=("prepare", "reconcile"))
    parser.add_argument("--repository-key", default="web")
    parser.add_argument("--pull-request-number", required=True)
    parser.add_argument("--pr-incarnation", required=True)
    parser.add_argument("--generation", required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        identity = validate_identity(
            args.repository_key,
            args.pull_request_number,
            args.pr_incarnation,
            args.generation,
        )
        ledger, gateway = _build_runtime()
        preparer = SecretPreparer(ledger, gateway)
        result = (
            preparer.prepare(identity)
            if args.mode == "prepare"
            else preparer.reconcile(identity)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except PreparationError as error:
        print(f"preview-secret-preparer: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
