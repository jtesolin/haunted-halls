import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from check_backend import BUCKET, DEPLOYER, state_prefix, verify_backend


ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "db_names", ROOT.parent / "preview-foundation/db-provisioner/db_names.py"
)
db_names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db_names)


class IdentityTests(unittest.TestCase):
    def metadata(self, repository="web", pr="123"):
        return {
            "backend": {
                "type": "gcs",
                "config": {
                    "bucket": BUCKET,
                    "prefix": state_prefix(repository, pr),
                    "impersonate_service_account": DEPLOYER,
                },
            }
        }

    def test_canonical_namespace_and_provisioner_agree(self):
        prefixes = set()
        for repository in ("web", "engine"):
            for pr in ("1", "123", "999999999"):
                prefix = state_prefix(repository, pr)
                self.assertNotIn(prefix, prefixes)
                prefixes.add(prefix)
                self.assertEqual(
                    db_names.derive_database_name(repository, int(pr)),
                    f"haunted_halls_{repository}_pr_{pr}",
                )
                verify_backend(self.metadata(repository, pr), repository, pr)

    def test_invalid_identity(self):
        for repository in ("WEB", "frontend", "", "../web", "web/engine"):
            with self.subTest(repository=repository), self.assertRaises(ValueError):
                state_prefix(repository, "1")
        for pr in ("0", "-1", "+1", "01", "1.0", "1e3", " 1", "1 ", "1\n",
                   "1000000000", "abc", "../1", "", "1/2"):
            with self.subTest(pr=pr), self.assertRaises(ValueError):
                state_prefix("web", pr)

    def test_backend_mismatches_fail_closed(self):
        for key, value in (
            ("bucket", "hh-preview-458395246135-foundation-tf-state"),
            ("prefix", "preview-foundation"),
            ("prefix", "previews/web-pr-124"),
            ("prefix", "previews/engine-pr-123"),
            ("impersonate_service_account", "other@example.com"),
            ("impersonate_service_account_delegates", ["other@example.com"]),
        ):
            metadata = copy.deepcopy(self.metadata())
            metadata["backend"]["config"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                verify_backend(metadata, "web", "123")
        for metadata in (None, [], {}, {"backend": {"type": "local"}}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                verify_backend(metadata, "web", "123")

    def test_cli_surfaces_errors_without_echoing_metadata(self):
        for content, successful, message in (
            (json.dumps(self.metadata()), True, "verified"),
            ("not json: private-metadata-marker", False, "not valid JSON"),
            (json.dumps({"private": "private-metadata-marker"}), False, "GCS backend"),
            (json.dumps(self.metadata("engine")), False, "differs from preview identity"),
        ):
            with self.subTest(content=content), tempfile.NamedTemporaryFile(mode="w") as metadata:
                metadata.write(content)
                metadata.flush()
                result = subprocess.run(
                    [sys.executable, str(ROOT / "check_backend.py"), "web", "123",
                     "--metadata", metadata.name],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0 if successful else 1)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertNotIn("private-metadata-marker", result.stdout + result.stderr)


class OwnershipTests(unittest.TestCase):
    def test_resource_inventory_has_only_disposable_resources(self):
        source = "\n".join(path.read_text() for path in ROOT.glob("*.tf"))
        inventory = set(re.findall(r'resource\s+"([^"]+)"\s+"([^"]+)"', source))
        self.assertEqual(inventory, {
            ("google_secret_manager_secret", "pr"),
            ("google_secret_manager_secret_version", "nextauth"),
            ("google_secret_manager_secret_version", "internal_token"),
            ("google_secret_manager_secret_version", "database_url"),
            ("google_secret_manager_secret_iam_member", "runtime"),
            ("google_cloud_run_v2_job", "migration"),
            ("google_cloud_run_v2_service", "engine"),
            ("google_cloud_run_v2_service", "frontend"),
            ("google_cloud_run_v2_service_iam_member", "engine_frontend"),
            ("google_cloud_run_v2_service_iam_member", "frontend_iap"),
            ("google_iap_web_cloud_run_service_iam_member", "tester"),
        })
        for forbidden in (r"\bdata\s+\"", r"\bimport\s*\{", r"\bprovisioner\s+\"",
                          r"\bsecret_data\s*=", r"\bpassword\s*=", r"\ballUsers\b",
                          r"\ballAuthenticatedUsers\b", r"\bignore_changes\b"):
            self.assertNotRegex(source, forbidden)
        variables = (ROOT / "variables.tf").read_text()
        for name in ("database_url", "nextauth_secret", "internal_engine_service_token"):
            block = variables.split(f'variable "{name}" {{', 1)[1].split("validation", 1)[0]
            self.assertRegex(block, r"sensitive\s*=\s*true")
            self.assertRegex(block, r"ephemeral\s*=\s*true")
        self.assertEqual((ROOT / "secrets.tf").read_text().count("secret_data_wo "), 3)
        migration = (ROOT / "migration.tf").read_text()
        self.assertNotIn("google_cloud_run_v2_service", migration)


if __name__ == "__main__":
    unittest.main()
