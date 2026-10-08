#!/usr/bin/env python3
"""Trusted, single-attempt preparation of disposable frontend preview secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
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
    """CAS-updated single-object ledger; bucket object versioning retains history."""

    def __init__(self, bucket: Any):
        self.bucket = bucket

    @staticmethod
    def object_name(identity: Identity) -> str:
        return (
            f"secret-preparation/v1/web-pr-{identity.pull_request_number}/"
            f"{identity.pr_incarnation}.json"
        )

    def _read(self, identity: Identity) -> tuple[dict[str, Any] | None, int | None]:
        from google.api_core.exceptions import NotFound

        blob = self.bucket.blob(self.object_name(identity))
        try:
            blob.reload()
        except NotFound:
            return None, None
        try:
            record = json.loads(blob.download_as_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LedgerError("The durable ledger record is unreadable.") from None
        if not isinstance(record, dict):
            raise LedgerError("The durable ledger record is malformed.")
        return record, int(blob.generation)

    def _write(
        self, identity: Identity, record: dict[str, Any], expected_generation: int
    ) -> int:
        from google.api_core.exceptions import PreconditionFailed

        blob = self.bucket.blob(self.object_name(identity))
        try:
            blob.upload_from_string(
                json.dumps(record, sort_keys=True, separators=(",", ":")),
                content_type="application/json",
                if_generation_match=expected_generation,
            )
        except PreconditionFailed:
            raise ReservationConflict("The preview secret ledger changed concurrently.") from None
        return int(blob.generation)

    def reserve(self, identity: Identity, names: dict[str, str]) -> tuple[dict[str, Any], int]:
        previous, generation = self._read(identity)
        if previous is None:
            record = {
                "schema_version": 1,
                "repository_key": identity.repository_key,
                "pull_request_number": identity.pull_request_number,
                "pr_incarnation": identity.pr_incarnation,
                "generation": identity.generation,
                "secret_names": names,
                "state": "reserved",
                "current_role": None,
                "secret_versions": {},
            }
            try:
                return record, self._write(identity, record, 0)
            except ReservationConflict:
                raise ReservationConflict("This preview generation was reserved concurrently.") from None

        _validate_record(previous, identity, names)
        current_generation = int(previous["generation"])
        if identity.generation <= current_generation:
            raise ReservationConflict("This generation was already reserved and cannot be replayed.")
        if previous["state"] != "complete":
            raise ReservationConflict("An unresolved generation holds the non-expiring reservation.")
        if identity.generation != current_generation + 1:
            raise ReservationConflict("Secret generations must advance by exactly one.")
        record = {
            **previous,
            "generation": identity.generation,
            "state": "reserved",
            "current_role": None,
            "secret_versions": {},
        }
        return record, self._write(identity, record, int(generation))

    def update(
        self,
        identity: Identity,
        names: dict[str, str],
        record: dict[str, Any],
        expected_generation: int,
    ) -> int:
        _validate_record(record, identity, names)
        current, current_generation = self._read(identity)
        if current is None or current_generation != expected_generation:
            raise ReservationConflict("The preview secret ledger changed concurrently.")
        if (
            int(record["generation"]) != identity.generation
            or
            current["generation"] != record["generation"]
            or current["state"] in {"complete", "reconciliation-required"}
        ):
            raise ReservationConflict("The preview generation is no longer writable.")
        return self._write(identity, record, expected_generation)

    def read(self, identity: Identity, names: dict[str, str]) -> dict[str, Any] | None:
        record, _ = self._read(identity)
        if record is not None:
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
        record, ledger_generation = self.ledger.reserve(identity, names)

        nextauth = bytearray(secrets.token_hex(32).encode("ascii"))
        internal_token = bytearray(secrets.token_hex(32).encode("ascii"))
        password = bytearray()
        db_url = bytearray()
        try:
            if nextauth == internal_token:
                raise PreparationError("Independent secret generation failed.")
            password = self.secrets.access_database_password()
            db_url = database_url(identity, password)
            payloads = {
                "nextauth": nextauth,
                "internal_token": internal_token,
                "database_url": db_url,
            }
            for role in ROLES:
                record["state"] = "writing"
                record["current_role"] = role
                ledger_generation = self.ledger.update(
                    identity, names, record, ledger_generation
                )
                try:
                    version = self.secrets.add_version(names[role], payloads[role])
                except SecretManagerWriteOutcomeUnknown:
                    record["state"] = "reconciliation-required"
                    try:
                        self.ledger.update(
                            identity, names, record, ledger_generation
                        )
                    except LedgerError:
                        raise ReconciliationRequired(
                            "The write outcome is unknown and the ledger update failed; do not retry."
                        ) from None
                    raise ReconciliationRequired(
                        "The write outcome is unknown; inspect the generation before any continuation."
                    ) from None
                record["secret_versions"][role] = version
                record["current_role"] = None
                try:
                    ledger_generation = self.ledger.update(
                        identity, names, record, ledger_generation
                    )
                except LedgerError:
                    raise ReconciliationRequired(
                        "A version was created but its metadata was not durably recorded; do not retry."
                    ) from None
            record["state"] = "complete"
            record["current_role"] = None
            try:
                self.ledger.update(identity, names, record, ledger_generation)
            except LedgerError:
                raise ReconciliationRequired(
                    "All writes returned versions but completion was not durably recorded; do not retry."
                ) from None
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
            "secret_versions": dict(record["secret_versions"]),
        }

    def reconcile(self, identity: Identity) -> dict[str, Any]:
        names = secret_names(identity)
        self._preflight(identity, names)
        record = self.ledger.read(identity, names)
        if record is None:
            raise PreparationError("No durable intent exists for this preview generation.")
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
