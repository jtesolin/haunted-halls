import unittest

from db_names import (
    InvalidProvisioningRequest,
    derive_database_name,
    validate_database_name,
    validate_provisioner_search_path,
    validate_preview_role_attributes,
    validate_role_memberships,
    validate_request,
)


class DatabaseNameTests(unittest.TestCase):
    def test_accepts_only_noinherit_roles_without_replication_or_rls_bypass(self) -> None:
        validate_preview_role_attributes(
            {
                "haunted_halls_preview_app": {
                    "rolinherit": False,
                    "rolreplication": False,
                    "rolbypassrls": False,
                },
                "haunted_halls_preview_provisioner": {
                    "rolinherit": False,
                    "rolreplication": False,
                    "rolbypassrls": False,
                },
            }
        )

    def test_rejects_inheritance_replication_or_rls_bypass(self) -> None:
        for role_name, attribute in (
            ("haunted_halls_preview_app", "rolinherit"),
            ("haunted_halls_preview_provisioner", "rolinherit"),
            ("haunted_halls_preview_app", "rolreplication"),
            ("haunted_halls_preview_provisioner", "rolreplication"),
            ("haunted_halls_preview_app", "rolbypassrls"),
            ("haunted_halls_preview_provisioner", "rolbypassrls"),
        ):
            roles = {
                "haunted_halls_preview_app": {
                    "rolinherit": False,
                    "rolreplication": False,
                    "rolbypassrls": False,
                },
                "haunted_halls_preview_provisioner": {
                    "rolinherit": False,
                    "rolreplication": False,
                    "rolbypassrls": False,
                },
            }
            roles[role_name][attribute] = True
            with self.subTest(roles=roles), self.assertRaises(ValueError):
                validate_preview_role_attributes(roles)

    def test_rejects_missing_preview_role_or_attributes(self) -> None:
        incomplete = {
            "haunted_halls_preview_app": {
                "rolinherit": False,
                "rolreplication": False,
                "rolbypassrls": False,
            }
        }
        with self.assertRaises(ValueError):
            validate_preview_role_attributes(incomplete)

    def test_accepts_only_pg_catalog_search_path(self) -> None:
        validate_provisioner_search_path(
            "pg_catalog", ["search_path=pg_catalog", "application_name=preview-db"]
        )

    def test_rejects_unhardened_search_paths(self) -> None:
        invalid_settings = (
            ("$user, public", ["search_path=pg_catalog"]),
            ("pg_catalog, public", ["search_path=pg_catalog"]),
            ("pg_catalog", ["search_path=pg_catalog, public"]),
            ("pg_catalog", ["search_path=pg_catalog", "search_path=public"]),
            ("pg_catalog", None),
            (None, ["search_path=pg_catalog"]),
        )
        for search_path, role_config in invalid_settings:
            with (
                self.subTest(search_path=search_path, role_config=role_config),
                self.assertRaises(ValueError),
            ):
                validate_provisioner_search_path(search_path, role_config)

    def test_accepts_only_the_exact_preview_role_memberships(self) -> None:
        validate_role_memberships(
            {
                "haunted_halls_preview_app": set(),
                "haunted_halls_preview_provisioner": {"haunted_halls_preview_app"},
            }
        )

    def test_rejects_app_role_memberships(self) -> None:
        with self.assertRaises(ValueError):
            validate_role_memberships(
                {
                    "haunted_halls_preview_app": {"haunted_halls_app"},
                    "haunted_halls_preview_provisioner": {"haunted_halls_preview_app"},
                }
            )

    def test_rejects_any_extra_provisioner_membership(self) -> None:
        with self.assertRaises(ValueError):
            validate_role_memberships(
                {
                    "haunted_halls_preview_app": set(),
                    "haunted_halls_preview_provisioner": {
                        "haunted_halls_preview_app",
                        "unexpected_privileged_role",
                    },
                }
            )

    def test_rejects_missing_or_unexpected_role_entries(self) -> None:
        for memberships in (
            {"haunted_halls_preview_app": set()},
            {
                "haunted_halls_preview_app": set(),
                "haunted_halls_preview_provisioner": {"haunted_halls_preview_app"},
                "unexpected_role": set(),
            },
        ):
            with self.subTest(memberships=memberships), self.assertRaises(ValueError):
                validate_role_memberships(memberships)

    def test_derives_only_supported_preview_names(self) -> None:
        self.assertEqual(
            derive_database_name("web", 123), "haunted_halls_web_pr_123"
        )
        self.assertEqual(
            derive_database_name("engine", 84), "haunted_halls_engine_pr_84"
        )

    def test_rejects_protected_database_names(self) -> None:
        for name in ("haunted_halls", "haunted_halls_staging"):
            with self.subTest(name=name), self.assertRaises(InvalidProvisioningRequest):
                validate_database_name(name)

    def test_rejects_arbitrary_database_names(self) -> None:
        for name in (
            "postgres",
            "haunted_halls_web_pr_1; DROP DATABASE haunted_halls",
            "haunted_halls_preview_app",
            "haunted_halls_web_pr_0",
        ):
            with self.subTest(name=name), self.assertRaises(InvalidProvisioningRequest):
                validate_database_name(name)

    def test_rejects_noncanonical_request_shapes_and_values(self) -> None:
        invalid_requests = (
            {"operation": "drop", "repository_key": "web", "pull_request_number": 1,
             "database_name": "haunted_halls"},
            {"operation": ["create"], "repository_key": "web", "pull_request_number": 1},
            {"operation": "create", "repository_key": "unknown", "pull_request_number": 1},
            {"operation": "delete", "repository_key": "web", "pull_request_number": 1},
            {"operation": "create", "repository_key": "web", "pull_request_number": True},
            {"operation": "drop", "repository_key": "engine", "pull_request_number": 0},
            {"operation": "drop", "repository_key": "web", "pull_request_number": 1_000_000_000},
        )
        for request in invalid_requests:
            with self.subTest(request=request), self.assertRaises(
                InvalidProvisioningRequest
            ):
                validate_request(request)

    def test_accepts_a_minimal_teardown_request(self) -> None:
        self.assertEqual(
            validate_request(
                {
                    "operation": "drop",
                    "repository_key": "engine",
                    "pull_request_number": 84,
                }
            ),
            ("drop", "haunted_halls_engine_pr_84"),
        )


if __name__ == "__main__":
    unittest.main()
