import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

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


class MemoryLedger:
    def __init__(self):
        self.record = None
        self.revision = 0
        self.history = []

    def reserve(self, identity, names):
        if self.record is not None:
            if self.record["state"] != "complete":
                raise ReservationConflict("unresolved")
            if identity.generation <= self.record["generation"]:
                raise ReservationConflict("replay")
            if identity.generation != self.record["generation"] + 1:
                raise ReservationConflict("skip")
        self.record = {
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
        self.revision += 1
        self.history.append(json.loads(json.dumps(self.record)))
        return self.record, self.revision

    def update(self, identity, names, record, expected_generation):
        if expected_generation != self.revision:
            raise ReservationConflict("stale generation")
        self.record = json.loads(json.dumps(record))
        self.revision += 1
        self.history.append(json.loads(json.dumps(self.record)))
        return self.revision

    def read(self, identity, names):
        if self.record is None:
            return None
        return json.loads(json.dumps(self.record))


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
            f"secret-preparation/v1/web-pr-123/{INCARNATION}.json",
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
        self.identity = validate_identity("web", "123", INCARNATION, "1")
        self.ledger = MemoryLedger()
        self.secrets = FakeSecrets()
        self.preparer = SecretPreparer(self.ledger, self.secrets)

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
        self.assertEqual(self.ledger.record["state"], "complete")
        self.assertEqual(
            [entry["state"] for entry in self.ledger.history],
            [
                "reserved",
                "writing",
                "writing",
                "writing",
                "writing",
                "writing",
                "writing",
                "complete",
            ],
        )
        self.assertEqual(
            [entry["current_role"] for entry in self.ledger.history[1:-1]],
            ["nextauth", None, "internal_token", None, "database_url", None],
        )
        for ledger_version in self.ledger.history:
            self.assertFalse(set(ledger_version) - {
                "schema_version", "repository_key", "pull_request_number",
                "pr_incarnation", "generation", "secret_names", "state",
                "current_role", "secret_versions",
            })

    def test_lost_response_requires_reconciliation_and_never_retries(self):
        self.secrets = FakeSecrets(fail_role="internal_token")
        self.preparer = SecretPreparer(self.ledger, self.secrets)
        with self.assertRaises(ReconciliationRequired):
            self.preparer.prepare(self.identity)
        self.assertEqual(self.secrets.calls, ["nextauth", "internal_token"])
        self.assertEqual(self.ledger.record["state"], "reconciliation-required")
        self.assertEqual(self.ledger.record["current_role"], "internal_token")
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(self.identity)
        self.assertEqual(self.secrets.calls, ["nextauth", "internal_token"])

    def test_generation_replay_and_unresolved_takeover_are_rejected(self):
        self.preparer.prepare(self.identity)
        with self.assertRaises(ReservationConflict):
            self.preparer.prepare(self.identity)
        later = validate_identity("web", "123", INCARNATION, "2")
        unresolved_ledger = MemoryLedger()
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
        self.assertIsNone(self.ledger.record)
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
                    self.ledger.record,
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
        self.assertEqual(self.ledger.record["state"], "reconciliation-required")
        self.assertEqual(len(self.ledger.history), 5)

    def test_completed_reconciliation_remains_read_only(self):
        self.preparer.prepare(self.identity)
        history_size = len(self.ledger.history)
        report = self.preparer.reconcile(self.identity)
        self.assertFalse(report["automatic_resume_allowed"])
        self.assertFalse(report["operator_disposition_required"])
        self.assertIsNone(report["in_flight_role"])
        self.assertEqual(len(self.ledger.history), history_size)


class TrustedWorkflowAndTerraformBoundaryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
