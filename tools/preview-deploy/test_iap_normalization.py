import unittest
from unittest.mock import patch

from test_lifecycle import lifecycle
from test_create_update_blockers import deployment


def v1(value):
    return {"metadata": {"annotations": {"run.googleapis.com/iap-enabled": value}}}


class IapNormalizationTests(unittest.TestCase):
    def test_valid_v1_v2_and_matching_dual_representations(self):
        for enabled, annotation in ((True, "true"), (False, "false")):
            for service in (v1(annotation), {"iapEnabled": enabled},
                            {**v1(annotation), "iapEnabled": enabled}):
                with self.subTest(service=service):
                    self.assertIs(lifecycle.cloud_run_iap_enabled(service), enabled)

    def test_conflicting_representations_fail_closed(self):
        for enabled, annotation in ((True, "false"), (False, "true")):
            with self.subTest(enabled=enabled), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.cloud_run_iap_enabled({**v1(annotation), "iapEnabled": enabled})

    def test_explicit_malformed_values_fail_even_with_other_valid_representation(self):
        for value in ("true", 1, 0, None, [], {}):
            for service in ({"iapEnabled": value}, {**v1("true"), "iapEnabled": value}):
                with self.subTest(service=service), self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.cloud_run_iap_enabled(service)
        for value in (True, False, None, "TRUE", "1", "", "arbitrary", [], {}):
            for service in (v1(value), {**v1(value), "iapEnabled": True}):
                with self.subTest(service=service), self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.cloud_run_iap_enabled(service)

    def test_malformed_containers_fail_closed_and_absence_is_false(self):
        for container in (None, [], "private", True):
            for service in ({"metadata": container},
                            {"metadata": {"annotations": container}}):
                with self.subTest(service=service), self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.cloud_run_iap_enabled({**service, "iapEnabled": True})
        for service in ({}, {"metadata": {}}, {"metadata": {"annotations": {}}}):
            with self.subTest(service=service):
                self.assertIs(lifecycle.cloud_run_iap_enabled(service), False)

    def test_runtime_uses_verified_terraform_url_not_service_url_alias(self):
        canonical = "https://hh-web-pr-41-frontend-1001419903197.us-east1.run.app"
        hashed_service_url = "https://service-1234567890-ue.a.run.app"
        engine = "https://hh-web-pr-41-engine-1001419903197.us-east1.run.app"
        for service, service_url, configured_url, error in (
            (v1("true"), hashed_service_url, canonical, None),
            ({"iapEnabled": True}, canonical, canonical, None),
            ({}, hashed_service_url, canonical,
             "The frontend Cloud Run service is not IAP-enabled."),
            (v1("false"), hashed_service_url, canonical,
             "The frontend Cloud Run service is not IAP-enabled."),
            (v1("true"), hashed_service_url,
             "https://hh-web-pr-42-frontend-1001419903197.us-east1.run.app",
             "Terraform frontend URL differs from the deterministic preview URL."),
            (v1("true"), hashed_service_url, canonical + "/",
             "Terraform frontend URL differs from the deterministic preview URL."),
        ):
            current = deployment()
            current.frontend_image = "frontend-digest"
            current.preview_engine_image = "engine-digest"
            current.database_was_created = False
            output = {
                "database_name": current.database, "repository_key": "web", "pr_number": "41",
                "frontend_image": current.frontend_image, "engine_image": current.preview_engine_image,
                "engine_url": engine, "frontend_url": configured_url,
            }
            with (
                self.subTest(service=service, service_url=service_url, configured_url=configured_url),
                patch.object(lifecycle.Commands, "json", side_effect=[output, service, {}, {}, {}]),
                patch.object(lifecycle, "latest_ready_revision_name", return_value="revision"),
                patch.object(lifecycle, "verify_serving_revision",
                             side_effect=[("frontend-digest", service_url), ("engine-digest", engine)]),
                patch.object(current, "verify_invokers"),
                patch.object(current, "verify_testers"),
                patch.object(lifecycle, "verify_unauthenticated_denied") as probe,
            ):
                if error:
                    with self.assertRaises(lifecycle.LifecycleError) as caught:
                        current.verify_runtime(False)
                    self.assertEqual(str(caught.exception), error)
                    if "Terraform frontend URL" in error:
                        self.assertEqual(lifecycle.Commands.json.call_count, 1)
                else:
                    self.assertEqual(current.verify_runtime(False), canonical)
                    self.assertEqual(probe.call_args_list[0].args, (canonical + "/",))
                    self.assertEqual(probe.call_args_list[1].args, (engine + "/health",))


if __name__ == "__main__":
    unittest.main()
