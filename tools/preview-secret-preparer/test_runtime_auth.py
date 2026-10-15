import contextlib
import io
import os
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import prepare


class GoogleAuthError(Exception):
    pass


class RefreshError(GoogleAuthError):
    pass


class RuntimeAuthTests(unittest.TestCase):
    def runtime(self, *, request_error=None, response=None, service_account=None):
        credentials = SimpleNamespace(
            service_account_email=service_account or prepare.PREPARER_SERVICE_ACCOUNT,
        )
        session = Mock()
        session.get.side_effect = request_error
        session.get.return_value = response or SimpleNamespace(
            status_code=200, json=lambda: {"projectNumber": prepare.PREVIEW_PROJECT_NUMBER},
        )
        default = Mock(return_value=(credentials, "ignored-adc-project"))
        authorized = Mock(return_value=session)
        storage_client = Mock()
        secret_client = Mock()
        modules = {
            name: ModuleType(name) for name in (
                "google", "google.auth", "google.auth.exceptions", "google.auth.transport",
                "google.auth.transport.requests", "google.cloud", "google.cloud.storage",
                "google.cloud.secretmanager",
            )
        }
        modules["google"].auth = modules["google.auth"]
        modules["google.auth"].default = default
        modules["google.auth.exceptions"].GoogleAuthError = GoogleAuthError
        modules["google.auth.transport.requests"].AuthorizedSession = authorized
        modules["google.cloud"].storage = modules["google.cloud.storage"]
        modules["google.cloud"].secretmanager = modules["google.cloud.secretmanager"]
        modules["google.cloud.storage"].Client = storage_client
        modules["google.cloud.secretmanager"].SecretManagerServiceClient = secret_client
        stack = contextlib.ExitStack()
        stack.enter_context(patch.dict(sys.modules, modules))
        stack.enter_context(patch.dict(os.environ, {
            "GOOGLE_CLOUD_PROJECT": prepare.PREVIEW_PROJECT_ID,
            "GOOGLE_AUTH_SCOPES": "private-untrusted-scope",
            "CLOUD_PLATFORM_SCOPE": "private-untrusted-scope",
        }))
        return stack, credentials, default, authorized, storage_client, secret_client, session

    def test_fixed_scope_and_same_credentials_used_by_all_clients(self):
        stack, credentials, default, authorized, storage, secret, session = self.runtime()
        with stack, patch.object(
            prepare, "validate_runtime_context", wraps=prepare.validate_runtime_context,
        ) as validate:
            prepare._build_runtime()
        default.assert_called_once_with(
            scopes=("https://www.googleapis.com/auth/cloud-platform",),
        )
        authorized.assert_called_once_with(credentials)
        storage.assert_called_once_with(
            project=prepare.PREVIEW_PROJECT_ID, credentials=credentials,
        )
        secret.assert_called_once_with(credentials=credentials)
        session.get.assert_called_once_with(
            "https://cloudresourcemanager.googleapis.com/v3/projects/"
            + prepare.PREVIEW_PROJECT_ID,
            timeout=20,
        )
        validate.assert_called_once_with(
            prepare.PREVIEW_PROJECT_ID, prepare.PREVIEW_PROJECT_NUMBER,
            prepare.PREPARER_SERVICE_ACCOUNT,
        )

    def test_authentication_and_existing_network_errors_are_sanitized(self):
        for kind in (GoogleAuthError, RefreshError, TimeoutError, ConnectionError, OSError):
            stack, _, _, _, storage, secret, _ = self.runtime(
                request_error=kind("private IAM body /tmp/credentials.json token"),
            )
            output = io.StringIO()
            with (
                self.subTest(kind=kind.__name__), stack,
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output),
            ):
                with self.assertRaises(prepare.PreparationError) as error:
                    prepare._build_runtime()
                self.assertEqual(
                    str(error.exception), "Could not verify the preview project identity.",
                )
                self.assertTrue(error.exception.__suppress_context__)
                storage.assert_not_called()
                secret.assert_not_called()
            self.assertEqual(output.getvalue(), "")

    def test_non_200_response_fails_safely_without_reading_body(self):
        response = Mock(status_code=403)
        stack, _, _, _, storage, secret, _ = self.runtime(response=response)
        with stack:
            with self.assertRaisesRegex(
                prepare.PreparationError, "^Could not verify the preview project identity\\.$",
            ):
                prepare._build_runtime()
        response.json.assert_not_called()
        storage.assert_not_called()
        secret.assert_not_called()

    def test_malformed_project_number_responses_fail_safely(self):
        for payload in ({}, None, [], {"projectNumber": "not-accepted"}):
            response = SimpleNamespace(status_code=200, json=lambda: payload)
            stack, _, _, _, storage, secret, _ = self.runtime(response=response)
            with self.subTest(payload=payload), stack:
                with self.assertRaises(prepare.PreparationError) as error:
                    prepare._build_runtime()
                self.assertIn(str(error.exception), (
                    "The preview project identity response was malformed.",
                    "The active Google Cloud project number is not the accepted preview number.",
                ))
            storage.assert_not_called()
            secret.assert_not_called()

    def test_wrong_service_account_still_fails_runtime_validation(self):
        stack, _, _, _, storage, secret, _ = self.runtime(
            service_account="wrong@example.iam.gserviceaccount.com",
        )
        with stack:
            with self.assertRaises(prepare.PreparationError):
                prepare._build_runtime()
        storage.assert_not_called()
        secret.assert_not_called()


if __name__ == "__main__":
    unittest.main()
