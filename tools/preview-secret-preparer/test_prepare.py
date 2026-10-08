import json
import re
import unittest
import os
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
from contextlib import ExitStack

import prepare
from terraform_targets import TARGETS
from prepare import (
    DB_PASSWORD_SECRET,
    PREPARER_SERVICE_ACCOUNT,
    PREVIEW_PROJECT_ID,
    PREVIEW_PROJECT_NUMBER,
    ROLES,
    GcsLedger,
    LedgerError,
    PreparationError,
    ReconciliationRequired,
    ReservationConflict,
    SecretManagerGateway,
    SecretManagerWriteOutcomeUnknown,
    SecretPreparer,
    _validate_record,
    database_name,
    database_url,
    secret_names,
    validate_identity,
    validate_runtime_context,
)


INCARNATION = "a" * 32
PASSWORD = b"0123456789abcdef" * 4


class ApiError(Exception):
    pass


class NotFound(ApiError):
    pass


class PreconditionFailed(ApiError):
    pass


class FakeBucket:
    """Model CREATE/GET only: overwrites, deletes and listing are unavailable."""

    def __init__(self):
        self.objects = {}
        self.creates = []
        self.failures = {}

    def blob(self, name):
        bucket = self

        class Blob:
            def download_as_bytes(self, *, retry, timeout):
                if name not in bucket.objects:
                    raise NotFound()
                return bucket.objects[name].encode()

            def upload_from_string(self, data, *, content_type, if_generation_match,
                                   retry, timeout):
                if if_generation_match != 0 or retry is not None:
                    raise AssertionError("Every create must be single-attempt and create-only.")
                bucket.creates.append(name)
                if name in bucket.objects:
                    raise PreconditionFailed()
                failure = bucket.failures.get(name)
                if failure == "absent":
                    raise TimeoutError()
                if failure == "conflict":
                    raise PreconditionFailed()
                bucket.objects[name] = data if failure != "mismatch" else "{}"
                if failure in {"committed", "mismatch"}:
                    raise TimeoutError()

        return Blob()


class FakeSecrets:
    def __init__(self, fail_role=None, labels=None):
        self.calls = []
        self.access_calls = 0
        self.list_calls = []
        self.fail_role = fail_role
        self.labels_map = labels or {}
        self.payloads = []

    def labels(self, secret_id):
        if secret_id in self.labels_map:
            return self.labels_map[secret_id]
        identity = re.search(r"hh-web-pr-([0-9]+)-i-([a-f0-9]{32})", secret_id)
        return {
            "app": "haunted-halls",
            "environment": "preview",
            "repository": "web",
            "pull_request": identity.group(1),
            "incarnation": identity.group(2),
            "managed_by": "terraform",
        }

    def access_database_password(self):
        self.access_calls += 1
        return bytearray(PASSWORD)

    def add_version(self, secret_id, payload):
        role = next(role for role in ROLES if secret_id.endswith(role.replace("_", "-")))
        self.calls.append(role)
        self.payloads.append(bytes(payload))
        if role == self.fail_role:
            raise SecretManagerWriteOutcomeUnknown("simulated lost response")
        return str(len(self.calls))

    def version_metadata(self, secret_id):
        self.list_calls.append(secret_id)
        index = next(i + 1 for i, role in enumerate(ROLES)
                     if secret_id.endswith(role.replace("_", "-")))
        return [{
            "version": str(index),
            "state": "ENABLED",
            "create_time": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        }]


class IdentityTests(unittest.TestCase):
    def test_deterministic_names_and_database_binding(self):
        first = validate_identity("web", "123", INCARNATION, "1")
        second = validate_identity("web", "123", INCARNATION, "2")
        other_pr = validate_identity("web", "124", INCARNATION, "1")
        other_incarnation = validate_identity("web", "123", "b" * 32, "1")
        self.assertEqual(secret_names(first), secret_names(second))
        self.assertNotEqual(secret_names(first), secret_names(other_pr))
        self.assertNotEqual(secret_names(first), secret_names(other_incarnation))
        self.assertNotEqual(GcsLedger.object_name(first), GcsLedger.object_name(other_pr))
        self.assertNotEqual(GcsLedger.object_name(first), GcsLedger.object_name(other_incarnation))
        self.assertEqual(database_name(first), "haunted_halls_web_pr_123")
        self.assertEqual(set(secret_names(first)), set(ROLES))
        self.assertTrue(all(len(value) <= 255 for value in secret_names(first).values()))
        self.assertEqual(
            GcsLedger.object_name(first),
            f"secret-preparation/v1/web-pr-123/{INCARNATION}/generations/1/reservation.json",
        )

    def test_rejects_malformed_repository_pr_incarnation_and_generation(self):
        invalid_identities = [
            ("engine", "1", INCARNATION, "1"),
            ("WEB", "1", INCARNATION, "1"),
            ("web", "0", INCARNATION, "1"),
            ("web", "01", INCARNATION, "1"),
            ("web", "1000000000", INCARNATION, "1"),
            ("web", "../1", INCARNATION, "1"),
            ("web", "1", "A" * 32, "1"),
            ("web", "1", "a" * 31, "1"),
            ("web", "1", INCARNATION, "0"),
            ("web", "1", INCARNATION, "01"),
            ("web", "1", INCARNATION, "1.0"),
        ]
        for values in invalid_identities:
            with self.subTest(values=values), self.assertRaises(PreparationError):
                validate_identity(*values)

    def test_rejects_wrong_project_number_or_runtime_identity(self):
        for values in (
            ("production", PREVIEW_PROJECT_NUMBER, PREPARER_SERVICE_ACCOUNT),
            (PREVIEW_PROJECT_ID, "12345", PREPARER_SERVICE_ACCOUNT),
            (PREVIEW_PROJECT_ID, PREVIEW_PROJECT_NUMBER, "other@example.com"),
        ):
            with self.subTest(values=values), self.assertRaises(PreparationError):
                validate_runtime_context(*values)
        validate_runtime_context(
            PREVIEW_PROJECT_ID, PREVIEW_PROJECT_NUMBER, PREPARER_SERVICE_ACCOUNT
        )

    def test_database_url_is_exact_and_uses_only_preview_database(self):
        identity = validate_identity("web", "91", INCARNATION, "1")
        value = database_url(identity, bytearray(PASSWORD))
        self.assertEqual(
            bytes(value),
            b"postgresql+psycopg://haunted_halls_preview_app:"
            + PASSWORD
            + b"@/haunted_halls_web_pr_91?host="
            + b"/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres",
        )
        self.assertNotIn(b"production", value)
        self.assertNotIn(b"staging", value)
        with self.assertRaises(PreparationError):
            database_url(identity, bytearray(b"not-a-valid-password"))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        sdk = patch.dict("sys.modules", {
            "google.api_core.exceptions": SimpleNamespace(
                GoogleAPICallError=ApiError, NotFound=NotFound,
                PreconditionFailed=PreconditionFailed,
            )
        })
        sdk.start()
        self.addCleanup(sdk.stop)
        self.reset_runtime()

    def reset_runtime(self):
        self.identity = validate_identity("web", "123", INCARNATION, "1")
        self.bucket = FakeBucket()
        self.ledger = GcsLedger(self.bucket)
        self.secrets = FakeSecrets()
        self.preparer = SecretPreparer(self.ledger, self.secrets)

    def test_password_access_failure_leaves_no_ledger_and_same_generation_can_retry(self):
        with patch.object(self.secrets, "access_database_password",
                          side_effect=PreparationError("Password unavailable.")):
            with self.assertRaises(PreparationError):
                self.preparer.prepare(self.identity)
        self.assertFalse(self.bucket.creates)
        self.assertFalse(self.bucket.objects)
        self.assertFalse(self.secrets.calls)
        self.assertEqual(self.preparer.prepare(self.identity)["state"], "complete")

    def test_sensitive_buffers_are_wiped_on_every_preparation_exit(self):
        phases = (
            "generation", "invalid_generation", "duplicate_generation",
            "password_access", "invalid_password", "database_url",
            "reservation_conflict", "reservation_failure", "intent",
            "append", "result", "complete", "success",
        )
        for phase in phases:
            with self.subTest(phase=phase), ExitStack() as stack:
                self.reset_runtime()
                wiped = []
                original_wipe = prepare._wipe

                def wipe(value):
                    wiped.append((value, len(value)))
                    original_wipe(value)

                stack.enter_context(patch("prepare._wipe", side_effect=wipe))
                if phase in {"generation", "invalid_generation", "duplicate_generation"}:
                    second = {
                        "generation": PreparationError("Generation failed."),
                        "invalid_generation": "invalid",
                        "duplicate_generation": "a" * 64,
                    }[phase]
                    stack.enter_context(patch("prepare.secrets.token_hex",
                                              side_effect=["a" * 64, second]))
                elif phase == "password_access":
                    stack.enter_context(patch.object(
                        self.secrets, "access_database_password",
                        side_effect=PreparationError("Password unavailable.")))
                elif phase == "invalid_password":
                    password = bytearray(b"invalid")
                    stack.enter_context(patch.object(
                        self.secrets, "access_database_password", return_value=password))
                elif phase == "database_url":
                    stack.enter_context(patch("prepare.database_url",
                                              side_effect=PreparationError("URL failed.")))
                elif phase.startswith("reservation"):
                    error = (ReservationConflict if phase == "reservation_conflict"
                             else LedgerError)
                    stack.enter_context(patch.object(self.ledger, "reserve",
                                                      side_effect=error("Reservation failed.")))
                elif phase in {"intent", "result", "complete"}:
                    stack.enter_context(patch.object(self.ledger, phase,
                                                      side_effect=LedgerError("Marker failed.")))
                elif phase == "append":
                    self.secrets.fail_role = "nextauth"

                if phase == "success":
                    self.preparer.prepare(self.identity)
                else:
                    with self.assertRaises(PreparationError):
                        self.preparer.prepare(self.identity)
                self.assertEqual(len(wiped), 4)
                for value, length in wiped:
                    self.assertEqual(value, bytearray(length))
                self.assertEqual(wiped[0][1], 64)
                if phase == "invalid_password":
                    self.assertIs(wiped[2][0], password)
                if phase.startswith("reservation") or phase in {
                        "intent", "append", "result", "complete", "success"}:
                    self.assertTrue(all(length > 0 for _, length in wiped))
                if phase not in {"intent", "append", "result", "complete", "success"}:
                    self.assertFalse(self.bucket.creates)
                    self.assertFalse(self.bucket.objects)
                    self.assertFalse(self.secrets.calls)

    def test_payload_preparation_finishes_before_reservation(self):
        original = self.ledger.reserve

        def reserve(identity, names):
            self.assertEqual(self.secrets.access_calls, 1)
            self.assertFalse(self.secrets.calls)
            self.assertFalse(self.bucket.objects)
            return original(identity, names)

        with patch.object(self.ledger, "reserve", side_effect=reserve):
            self.preparer.prepare(self.identity)

    def test_prepares_three_independent_values_and_emits_only_numeric_versions(self):
        result = self.preparer.prepare(self.identity)
        self.assertEqual(self.secrets.calls, list(ROLES))
        self.assertEqual(self.secrets.access_calls, 1)
        self.assertEqual(len(set(self.secrets.payloads)), 3)
        self.assertRegex(self.secrets.payloads[0].decode(), r"^[0-9a-f]{64}$")
        self.assertRegex(self.secrets.payloads[1].decode(), r"^[0-9a-f]{64}$")
        self.assertEqual(
            self.secrets.payloads[2],
            b"postgresql+psycopg://haunted_halls_preview_app:"
            + PASSWORD
            + b"@/haunted_halls_web_pr_123?host="
            + b"/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres",
        )
        self.assertEqual(
            result["secret_versions"],
            {"nextauth": "1", "internal_token": "2", "database_url": "3"},
        )
        output = json.dumps(result)
        for payload in self.secrets.payloads:
            self.assertNotIn(payload.decode(), output)
        self.assertNotIn("payload", output)
        self.assertNotIn("hash", output)
        record = self.ledger.read(self.identity, secret_names(self.identity))
        self.assertEqual(record["state"], "complete")
        self.assertEqual(
            [json.loads(value)["marker"] for value in self.bucket.objects.values()],
            [
                "reservation",
                "nextauth.intent",
                "nextauth.result",
                "internal-token.intent",
                "internal-token.result",
                "database-url.intent",
                "database-url.result",
                "complete",
            ],
        )
        for data in self.bucket.objects.values():
            ledger_version = json.loads(data)
            self.assertFalse(set(ledger_version) - {
                "schema_version", "repository_key", "pull_request_number",
                "pr_incarnation", "generation", "secret_names", "marker", "version",
                "reservation_id",
            })
            for payload in self.secrets.payloads:
                self.assertNotIn(payload.decode(), data)
            self.assertNotIn("hash", data)

    def test_lost_response_requires_reconciliation_and_never_retries(self):
        self.secrets = FakeSecrets(fail_role="internal_token")
        self.preparer = SecretPreparer(self.ledger, self.secrets)
        with self.assertRaises(ReconciliationRequired):
            self.preparer.prepare(self.identity)
        self.assertEqual(self.secrets.calls, ["nextauth", "internal_token"])
        record = self.ledger.read(self.identity, secret_names(self.identity))
        self.assertEqual(record["state"], "reconciliation-required")
        self.assertEqual(record["current_role"], "internal_token")
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(self.identity)
        self.assertEqual(self.secrets.calls, ["nextauth", "internal_token"])

    def test_generation_replay_and_unresolved_takeover_are_rejected(self):
        self.preparer.prepare(self.identity)
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(self.identity)
        later = validate_identity("web", "123", INCARNATION, "2")
        unresolved_ledger = GcsLedger(FakeBucket())
        unresolved_secrets = FakeSecrets(fail_role="nextauth")
        unresolved = SecretPreparer(unresolved_ledger, unresolved_secrets)
        with self.assertRaises(ReconciliationRequired):
            unresolved.prepare(self.identity)
        with self.assertRaises(ReservationConflict):
            SecretPreparer(unresolved_ledger, FakeSecrets()).prepare(later)

    def test_wrong_ownership_labels_fail_before_reservation_or_payload_read(self):
        names = secret_names(self.identity)
        secret_id = names["database_url"]
        self.secrets = FakeSecrets(labels={secret_id: {"environment": "staging"}})
        self.preparer = SecretPreparer(self.ledger, self.secrets)
        with self.assertRaises(PreparationError):
            self.preparer.prepare(self.identity)
        self.assertFalse(self.bucket.objects)
        self.assertEqual(self.secrets.access_calls, 0)
        self.assertEqual(self.secrets.calls, [])

    def test_cross_pr_and_cross_incarnation_ledger_records_fail_closed(self):
        self.preparer.prepare(self.identity)
        for different_identity in (
            validate_identity("web", "124", INCARNATION, "1"),
            validate_identity("web", "123", "b" * 32, "1"),
        ):
            with self.subTest(identity=different_identity), self.assertRaises(LedgerError):
                _validate_record(
                    self.ledger.read(self.identity, secret_names(self.identity)),
                    different_identity,
                    secret_names(different_identity),
                )

    def test_read_only_reconciliation_lists_metadata_without_accessing_payloads(self):
        self.secrets = FakeSecrets(fail_role="internal_token")
        self.preparer = SecretPreparer(self.ledger, self.secrets)
        with self.assertRaises(ReconciliationRequired):
            self.preparer.prepare(self.identity)
        self.secrets.fail_role = None
        report = self.preparer.reconcile(self.identity)
        self.assertTrue(report["operator_disposition_required"])
        self.assertFalse(report["automatic_resume_allowed"])
        self.assertEqual(len(self.secrets.list_calls), 3)
        self.assertEqual(self.secrets.access_calls, 1)
        self.assertEqual(report["state"], "reconciliation-required")
        self.assertEqual(report["in_flight_role"], "internal_token")
        self.assertFalse(report["automatic_resume_allowed"])
        self.assertNotIn("payload", json.dumps(report))
        self.assertEqual(self.ledger.read(self.identity, secret_names(self.identity))["state"],
                         "reconciliation-required")
        self.assertEqual(len(self.bucket.objects), 5)

    def test_completed_reconciliation_remains_read_only(self):
        self.preparer.prepare(self.identity)
        history_size = len(self.bucket.objects)
        self.secrets.access_calls = 0
        report = self.preparer.reconcile(self.identity)
        self.assertFalse(report["automatic_resume_allowed"])
        self.assertFalse(report["operator_disposition_required"])
        self.assertIsNone(report["in_flight_role"])
        self.assertEqual(len(self.bucket.objects), history_size)
        self.assertEqual(self.secrets.access_calls, 0)

    def test_every_append_observes_its_durable_intent_and_previous_results(self):
        original = self.secrets.add_version

        def append(secret_id, payload):
            role = next(role for role in ROLES if secret_id.endswith(role.replace("_", "-")))
            marker = role.replace("_", "-")
            self.assertIn(GcsLedger.object_name(self.identity, f"{marker}.intent"),
                          self.bucket.objects)
            for previous in ROLES[:ROLES.index(role)]:
                self.assertIn(GcsLedger.object_name(
                    self.identity, f"{previous.replace('_', '-')}.result"), self.bucket.objects)
            return original(secret_id, payload)

        self.secrets.add_version = append
        self.preparer.prepare(self.identity)

    def test_skip_and_unresolved_prior_generation_fail_without_append(self):
        for generation in ("2", "3"):
            with self.assertRaises(ReservationConflict):
                self.preparer.prepare(validate_identity("web", "123", INCARNATION, generation))
        self.ledger.reserve(self.identity, secret_names(self.identity))
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(validate_identity("web", "123", INCARNATION, "2"))
        self.assertEqual(self.secrets.access_calls, 3)
        self.assertFalse(self.secrets.calls)

    def test_next_generation_requires_complete_not_just_all_results(self):
        self.preparer.prepare(self.identity)
        next_identity = validate_identity("web", "123", INCARNATION, "2")
        self.preparer.prepare(next_identity)
        self.assertEqual(self.ledger.read(next_identity, secret_names(next_identity))["state"],
                         "complete")
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(validate_identity("web", "123", INCARNATION, "4"))

    def test_result_persistence_failure_is_reconciliation_not_retryable_conflict(self):
        for failure in ("absent", "mismatch", "conflict"):
            with self.subTest(failure=failure):
                self.reset_runtime()
                name = GcsLedger.object_name(self.identity, "nextauth.result")
                self.bucket.failures[name] = failure
                with self.assertRaises(ReconciliationRequired):
                    self.preparer.prepare(self.identity)
                self.assertEqual(self.secrets.calls, ["nextauth"])
                self.assertIn(GcsLedger.object_name(self.identity, "reconciliation-required"),
                              self.bucket.objects)
                with self.assertRaises(ReservationConflict):
                    self.preparer.prepare(self.identity)
                self.assertEqual(self.secrets.calls, ["nextauth"])

    def test_unresolved_intent_blocks_replay_even_without_reconciliation_marker(self):
        self.bucket.failures[GcsLedger.object_name(self.identity, "nextauth.result")] = "absent"
        self.bucket.failures[
            GcsLedger.object_name(self.identity, "reconciliation-required")
        ] = "absent"
        with self.assertRaises(ReconciliationRequired):
            self.preparer.prepare(self.identity)
        record = self.ledger.read(self.identity, secret_names(self.identity))
        self.assertEqual(record["state"], "reconciliation-required")
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(self.identity)
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(validate_identity("web", "123", INCARNATION, "2"))
        self.assertEqual(self.secrets.calls, ["nextauth"])

    def test_ambiguous_immutable_creates_are_adopted_only_after_exact_get(self):
        for marker in ("reservation", "nextauth.intent", "nextauth.result", "complete"):
            with self.subTest(marker=marker):
                self.reset_runtime()
                name = GcsLedger.object_name(self.identity, marker)
                self.bucket.failures[name] = "committed"
                result = self.preparer.prepare(self.identity)
                self.assertEqual(self.secrets.calls, list(ROLES))
                self.assertEqual(self.bucket.creates.count(name), 1)
                self.assertEqual(result["secret_versions"],
                                 {"nextauth": "1", "internal_token": "2", "database_url": "3"})

    def test_ambiguous_intent_absent_or_mismatched_never_appends(self):
        for failure in ("absent", "mismatch"):
            with self.subTest(failure=failure):
                self.reset_runtime()
                self.bucket.failures[
                    GcsLedger.object_name(self.identity, "nextauth.intent")
                ] = failure
                with self.assertRaises(LedgerError):
                    self.preparer.prepare(self.identity)
                self.assertFalse(self.secrets.calls)
                with self.assertRaises(ReservationConflict):
                    self.preparer.prepare(self.identity)

    def test_all_results_without_complete_blocks_next_generation(self):
        self.bucket.failures[GcsLedger.object_name(self.identity, "complete")] = "absent"
        with self.assertRaises(ReconciliationRequired):
            self.preparer.prepare(self.identity)
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(validate_identity("web", "123", INCARNATION, "2"))
        self.assertEqual(self.secrets.calls, list(ROLES))

    def test_completion_cannot_be_created_without_all_durable_results(self):
        names = secret_names(self.identity)
        self.ledger.reserve(self.identity, names)
        with self.assertRaises(LedgerError):
            self.ledger.complete(self.identity, names)
        self.assertNotIn(GcsLedger.object_name(self.identity, "complete"), self.bucket.objects)

    def test_existing_marker_cannot_be_overwritten_even_with_matching_content(self):
        names = secret_names(self.identity)
        self.ledger.reserve(self.identity, names)
        self.ledger.intent(self.identity, names, "nextauth")
        before = dict(self.bucket.objects)
        with self.assertRaises(ReservationConflict):
            self.ledger.intent(self.identity, names, "nextauth")
        self.assertEqual(self.bucket.objects, before)

    def test_ambiguous_reservation_absent_or_wrong_content_never_appends(self):
        for failure in ("absent", "mismatch"):
            with self.subTest(failure=failure):
                self.reset_runtime()
                self.bucket.failures[GcsLedger.object_name(self.identity)] = failure
                with self.assertRaises(LedgerError):
                    self.preparer.prepare(self.identity)
                self.assertEqual(self.secrets.access_calls, 1)
                self.assertFalse(self.secrets.calls)

    def test_gateway_performs_exactly_one_append_and_sanitizes_unknown_outcome(self):
        client = SimpleNamespace(add_secret_version=unittest.mock.Mock(
            side_effect=ApiError("sensitive response detail")
        ))
        gateway = SecretManagerGateway(client)
        with self.assertRaises(SecretManagerWriteOutcomeUnknown) as caught:
            gateway.add_version(secret_names(self.identity)["nextauth"], bytearray(b"test-value"))
        self.assertEqual(client.add_secret_version.call_count, 1)
        self.assertIsNone(client.add_secret_version.call_args.kwargs["retry"])
        self.assertNotIn("sensitive response detail", str(caught.exception))

    def test_mismatched_marker_identity_and_unsafe_fields_fail_closed(self):
        self.preparer.prepare(self.identity)
        name = GcsLedger.object_name(self.identity, "nextauth.result")
        original = json.loads(self.bucket.objects[name])
        for extra in ({"pull_request_number": "124"}, {"payload": "not-allowed"},
                      {"version": "latest"}, {"generation": True}):
            with self.subTest(extra=extra):
                self.bucket.objects[name] = json.dumps({**original, **extra})
                with self.assertRaises(LedgerError):
                    self.preparer.reconcile(self.identity)


class TrustedWorkflowAndTerraformBoundaryTests(unittest.TestCase):
    def test_privileged_workflow_installs_only_committed_hash_lock(self):
        root = Path(__file__).parents[2]
        workflow = (root / ".github/workflows/preview-secret-prepare.yml").read_text()
        self.assertIn(
            "python -m pip install --require-hashes --only-binary=:all:\n"
            "          --requirement tools/preview-secret-preparer/requirements.lock",
            workflow,
        )
        self.assertNotIn("requirements.txt", workflow)
        self.assertTrue(Path(__file__).with_name("requirements.lock").is_file())

    def test_runtime_lock_contains_only_exact_pins_with_sha256_hashes(self):
        lock = Path(__file__).with_name("requirements.lock").read_text()
        lines = [line for line in lock.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        entries = "\n".join(lines).replace("\\\n", " ").splitlines()
        self.assertTrue(entries)
        names = set()
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertRegex(
                    entry,
                    r"^[a-z0-9]+(?:-[a-z0-9]+)*==[0-9]+(?:\.[0-9]+)*"
                    r"(?:\s+--hash=sha256:[a-f0-9]{64})+\s*$",
                )
                name = entry.split("==", 1)[0]
                self.assertNotIn(name, names)
                names.add(name)
        source = Path(__file__).with_name("requirements.txt").read_text().splitlines()
        for requirement in source:
            if requirement.strip() and not requirement.startswith("#"):
                self.assertTrue(any(entry.startswith(requirement + " ") for entry in entries))

    def test_pre_auth_workflow_rejects_drafts_closed_wrong_repo_and_missing_metadata(self):
        workflow = (
            Path(__file__).parents[2] / ".github/workflows/preview-secret-prepare.yml"
        ).read_text()
        step = workflow.split("run: |", 1)[1].split("\n      - name:", 1)[0]
        script = "\n".join(line[10:] for line in step.splitlines() if line)
        self.assertLess(workflow.index("pr.get(\"draft\") is False"),
                        workflow.index("uses: google-github-actions/auth"))
        valid = {"number": 123, "state": "open", "draft": False,
                 "base": {"repo": {"full_name": "jtesolin/haunted-halls"}}}
        cases = [
            (valid, True),
            ({**valid, "draft": True}, False),
            ({**valid, "state": "closed"}, False),
            ({**valid, "number": 124}, False),
            ({**valid, "base": {"repo": {"full_name": "elsewhere/repo"}}}, False),
            ({key: value for key, value in valid.items() if key != "draft"}, False),
        ]
        for metadata, accepted in cases:
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                gh = root / "gh"
                gh.write_text("#!/bin/sh\nprintf '%s' \"$PR_FIXTURE\"\n")
                gh.chmod(0o700)
                result = subprocess.run(
                    ["bash", "-c", script + "\nprintf AUTHENTICATION_REACHED"],
                    env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                         "GITHUB_WORKFLOW_REF": "jtesolin/haunted-halls/.github/workflows/preview-secret-prepare.yml@refs/heads/main",
                         "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
                         "PR_NUMBER": "123", "RUNNER_TEMP": directory,
                         "PR_FIXTURE": json.dumps(metadata)},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                self.assertEqual("AUTHENTICATION_REACHED" in result.stdout, accepted)

    def test_bootstrap_targets_are_exact_and_never_target_everything(self):
        self.assertEqual(
            TARGETS["containers"],
            (
                "google_secret_manager_secret.pr",
                "google_secret_manager_secret_iam_member.runtime",
            ),
        )
        self.assertEqual(TARGETS["migration"], ("google_cloud_run_v2_job.migration",))
        self.assertNotIn("all", json.dumps(TARGETS))

    def test_workflow_runs_only_trusted_default_branch_code(self):
        workflow = (
            Path(__file__).parents[2] / ".github/workflows/preview-secret-prepare.yml"
        ).read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn(
            "jtesolin/haunted-halls/.github/workflows/preview-secret-prepare.yml@refs/heads/main",
            workflow,
        )
        self.assertIn(PREPARER_SERVICE_ACCOUNT, workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("ref: ${{ github.event.pull_request", workflow)

    def test_only_durable_preview_password_path_is_used(self):
        self.assertEqual(
            DB_PASSWORD_SECRET,
            "projects/1001419903197/secrets/hh-preview-db-app-password/versions/latest",
        )

    def test_secret_manager_append_disables_sdk_retries(self):
        source = (Path(__file__).with_name("prepare.py")).read_text()
        self.assertIn("retry=None", source)

    def test_secret_manager_response_must_name_exact_secret_and_numeric_version(self):
        identity = validate_identity("web", "123", INCARNATION, "1")
        secret_id = secret_names(identity)["database_url"]
        valid = (
            f"projects/{PREVIEW_PROJECT_NUMBER}/secrets/{secret_id}/versions/12"
        )
        self.assertEqual(SecretManagerGateway.numeric_version(secret_id, valid), "12")
        for resource_name in (
            f"projects/{PREVIEW_PROJECT_NUMBER}/secrets/other/versions/12",
            f"projects/{PREVIEW_PROJECT_NUMBER}/secrets/{secret_id}/versions/latest",
            f"projects/{PREVIEW_PROJECT_NUMBER}/secrets/{secret_id}/versions/12/extra",
        ):
            with self.subTest(resource_name=resource_name), self.assertRaises(
                SecretManagerWriteOutcomeUnknown
            ):
                SecretManagerGateway.numeric_version(secret_id, resource_name)


if __name__ == "__main__":
    unittest.main()
