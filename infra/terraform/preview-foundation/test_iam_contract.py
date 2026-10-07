"""Offline source contracts, not an IAM evaluator or live authorization test."""

import json
import re
import unittest
from pathlib import Path


FOUNDATION = Path(__file__).parent
APPLICATION = FOUNDATION.parent
PR_ROOT = APPLICATION / "preview-pr"
DEPLOYER_MEMBER = '"serviceAccount:${google_service_account.deployer.email}"'


def resource(path: Path, kind: str, name: str) -> str:
    pattern = rf'^resource "{re.escape(kind)}" "{re.escape(name)}" \{{\n(.*?)^\}}'
    matches = re.findall(pattern, path.read_text(), re.MULTILINE | re.DOTALL)
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one {kind}.{name} in {path.name}")
    return matches[0]


def attribute(block: str, name: str) -> str:
    matches = re.findall(rf"^\s*{re.escape(name)}\s*=\s*(.+)$", block, re.MULTILINE)
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one {name} attribute")
    return matches[0].strip()


def permissions(block: str) -> set[str]:
    matches = re.findall(r"permissions\s*=\s*\[(.*?)\]", block, re.DOTALL)
    if len(matches) != 1:
        raise AssertionError("Expected one permission list")
    values = re.findall(r'"([^"]+)"', matches[0])
    if len(values) != len(set(values)):
        raise AssertionError("Duplicate permissions")
    return set(values)


class PreviewIamContracts(unittest.TestCase):
    def foundation_resource(self, kind: str, name: str) -> str:
        return resource(FOUNDATION / "deployer-iam.tf", kind, name)

    def test_iap_role_has_only_service_policy_permissions(self):
        block = self.foundation_resource("google_project_iam_custom_role", "preview_iap_tester_policy")
        self.assertEqual(permissions(block), {
            "iap.webServices.getIamPolicy", "iap.webServices.setIamPolicy",
        })

    def test_iap_grant_uses_documented_service_type_and_modified_roles(self):
        block = self.foundation_resource("google_project_iam_member", "deployer_iap_tester_policy")
        self.assertEqual(attribute(block, "project"), "var.preview_project_id")
        self.assertEqual(attribute(block, "member"), DEPLOYER_MEMBER)
        self.assertEqual(attribute(block, "role"), "google_project_iam_custom_role.preview_iap_tester_policy.name")
        self.assertEqual(json.loads(attribute(block, "expression")),
                         'resource.type == "iap.googleapis.com/WebService" && '
                         'api.getAttribute("iam.googleapis.com/modifiedGrantsByRole", []).'
                         'hasOnly(["roles/iap.httpsResourceAccessor"])')
        self.assertNotIn("resource.name", block)

    def test_secret_creation_is_separate_project_creation_only_grant(self):
        role = self.foundation_resource("google_project_iam_custom_role", "preview_per_pr_secret_creator")
        self.assertEqual(permissions(role), {"secretmanager.secrets.create"})
        grant = self.foundation_resource("google_project_iam_member", "deployer_per_pr_secret_creator")
        self.assertEqual(attribute(grant, "project"), "var.preview_project_id")
        self.assertEqual(attribute(grant, "member"), DEPLOYER_MEMBER)
        self.assertEqual(attribute(grant, "role"), "google_project_iam_custom_role.preview_per_pr_secret_creator.name")
        self.assertNotRegex(grant, r"\bcondition\s*\{")

    def test_existing_secret_management_permissions_and_prefixes_are_preserved(self):
        role = self.foundation_resource("google_project_iam_custom_role", "preview_per_pr_secret_manager")
        self.assertEqual(permissions(role), {
            "secretmanager.secrets.delete", "secretmanager.secrets.get",
            "secretmanager.secrets.update", "secretmanager.secrets.getIamPolicy",
            "secretmanager.secrets.setIamPolicy", "secretmanager.versions.add",
            "secretmanager.versions.disable", "secretmanager.versions.enable",
            "secretmanager.versions.destroy", "secretmanager.versions.get",
            "secretmanager.versions.list",
        })
        grant = self.foundation_resource("google_project_iam_member", "deployer_per_pr_secret_manager")
        self.assertEqual(attribute(grant, "project"), "var.preview_project_id")
        self.assertEqual(attribute(grant, "member"), DEPLOYER_MEMBER)
        self.assertEqual(json.loads(attribute(grant, "expression")),
                         '(resource.type == "secretmanager.googleapis.com/Secret" || '
                         'resource.type == "secretmanager.googleapis.com/SecretVersion") && '
                         '(resource.name.startsWith("projects/${data.google_project.preview.number}/secrets/hh-web-pr-") || '
                         'resource.name.startsWith("projects/${data.google_project.preview.number}/secrets/hh-engine-pr-"))')

    def test_quota_use_is_preview_only_without_service_administration(self):
        role = self.foundation_resource("google_project_iam_custom_role", "preview_quota_consumer")
        self.assertEqual(permissions(role), {"serviceusage.services.use"})
        grant = self.foundation_resource("google_project_iam_member", "deployer_quota_consumer")
        self.assertEqual(attribute(grant, "project"), "var.preview_project_id")
        self.assertEqual(attribute(grant, "member"), DEPLOYER_MEMBER)
        self.assertEqual(attribute(grant, "role"), "google_project_iam_custom_role.preview_quota_consumer.name")

    def test_foundation_owns_preview_sql_api_without_deployer_sql_role(self):
        api = resource(FOUNDATION / "apis.tf", "google_project_service", "apis")
        self.assertIn('"sqladmin.googleapis.com"', api)
        self.assertEqual(attribute(api, "project"), "var.preview_project_id")
        self.assertEqual(attribute(api, "disable_on_destroy"), "false")
        deployer = (FOUNDATION / "deployer-iam.tf").read_text()
        self.assertNotIn("cloudsql.", deployer)
        self.assertNotIn("roles/cloudsql.", deployer)
        self.assertNotIn("secretmanager.versions.access", deployer)

    def test_source_role_has_only_named_metadata_reads(self):
        block = resource(APPLICATION / "preview-access-iam.tf",
                         "google_project_iam_custom_role", "preview_staging_engine_metadata")
        self.assertEqual(permissions(block), {"run.services.get", "run.revisions.get"})
        self.assertEqual(attribute(block, "project"), "var.project_id")
        self.assertEqual(attribute(block, "condition"),
                         'var.project_id == "haunted-halls-development" && var.region == "us-east1"')

    def test_source_grant_is_only_the_enabled_staging_engine_service(self):
        block = resource(APPLICATION / "preview-access-iam.tf",
                         "google_cloud_run_v2_service_iam_member", "preview_staging_engine_metadata")
        self.assertEqual(attribute(block, "count"), "var.staging_application_services_enabled ? 1 : 0")
        self.assertEqual(attribute(block, "name"), "google_cloud_run_v2_service.engine_staging[0].name")
        self.assertEqual(attribute(block, "project"), "var.project_id")
        self.assertEqual(attribute(block, "location"), "var.region")
        self.assertEqual(attribute(block, "role"), "google_project_iam_custom_role.preview_staging_engine_metadata.name")
        self.assertEqual(attribute(block, "member"), '"serviceAccount:${local.preview_deployer_email}"')

    def test_source_registry_grant_is_additive_repository_reader_for_deployer_only(self):
        source = (APPLICATION / "preview-access-iam.tf").read_text()
        self.assertIn('preview_deployer_email = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"', source)
        inventory = set(re.findall(r'^resource "([^"]+)" "([^"]+)"', source, re.MULTILINE))
        self.assertEqual(inventory, {
            ("google_project_iam_custom_role", "preview_staging_engine_metadata"),
            ("google_cloud_run_v2_service_iam_member", "preview_staging_engine_metadata"),
            ("google_artifact_registry_repository_iam_member", "preview_source_reader"),
        })
        block = resource(APPLICATION / "preview-access-iam.tf",
                         "google_artifact_registry_repository_iam_member", "preview_source_reader")
        self.assertEqual(attribute(block, "project"), "var.project_id")
        self.assertEqual(attribute(block, "repository"), "google_artifact_registry_repository.app.name")
        self.assertEqual(attribute(block, "location"), "google_artifact_registry_repository.app.location")
        self.assertEqual(attribute(block, "role"), '"roles/artifactregistry.reader"')
        self.assertEqual(attribute(block, "member"), '"serviceAccount:${local.preview_deployer_email}"')
        self.assertEqual(attribute(block, "condition"),
                         'var.project_id == "haunted-halls-development" && var.region == "us-east1"')

    def test_testers_remain_per_frontend_without_project_access_or_self_token_creator(self):
        tester = resource(PR_ROOT / "iam.tf", "google_iap_web_cloud_run_service_iam_member", "tester")
        self.assertEqual(attribute(tester, "cloud_run_service_name"), "google_cloud_run_v2_service.frontend.name")
        self.assertEqual(attribute(tester, "role"), '"roles/iap.httpsResourceAccessor"')
        self.assertEqual(attribute(tester, "member"), "each.value")
        for path in FOUNDATION.glob("*.tf"):
            source = path.read_text()
            self.assertNotRegex(source, r'role\s*=\s*"roles/iap\.httpsResourceAccessor"')
            self.assertNotIn("roles/iam.serviceAccountTokenCreator", source)
        for path in (FOUNDATION / "deployer-iam.tf", APPLICATION / "preview-access-iam.tf"):
            self.assertNotRegex(path.read_text(), r"\ballUsers\b|\ballAuthenticatedUsers\b")

    def test_backend_and_provider_remain_distinct_authentication_surfaces(self):
        backend = (PR_ROOT / "versions.tf").read_text()
        self.assertRegex(backend, r'impersonate_service_account\s*=\s*"hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"')
        provider = (PR_ROOT / "providers.tf").read_text()
        self.assertRegex(provider, r"user_project_override\s*=\s*true")
        self.assertRegex(provider, r"billing_project\s*=\s*local.project_id")
        self.assertNotIn("impersonate_service_account", provider)


if __name__ == "__main__":
    unittest.main()
