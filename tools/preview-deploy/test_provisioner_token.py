import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_lifecycle import lifecycle, SHA


class ProvisionerTokenTests(unittest.TestCase):
    def deployment(self):
        return lifecycle.PreviewDeployment(
            lifecycle.BuildContext(
                "41", SHA, 1234, 1, 5678, "sha256:" + "d" * 64, "image", "/tmp/image.tar",
            ),
            object(),
        )

    def service(self):
        return {
            "metadata": {
                "name": "hh-preview-db-provisioner",
                "namespace": "123456789012",
                "labels": {"cloud.googleapis.com/location": "us-east1"},
            },
            "status": {
                "url": "https://hh-preview-db-provisioner-123456789012.us-east1.run.app",
            },
        }

    def test_invalid_credential_paths_fail_before_token_or_request_without_leaking(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in (None, "", "relative-private.json", directory + "/missing.json", directory):
                environment = {} if value is None else {"GOOGLE_BACKEND_CREDENTIALS": value}
                with (
                    self.subTest(value=value),
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(lifecycle.Commands, "json", return_value=self.service()),
                    patch.object(lifecycle.Commands, "run") as run,
                    patch.object(lifecycle.urllib.request, "urlopen") as urlopen,
                ):
                    with self.assertRaises(lifecycle.LifecycleError) as error:
                        self.deployment().ensure_database()
                    self.assertEqual(
                        str(error.exception),
                        "Database provisioner direct-WIF credential file is unavailable.",
                    )
                    run.assert_not_called()
                    urlopen.assert_not_called()

    def test_only_token_subprocess_uses_backend_credentials_and_contents_are_not_read(self):
        private_token = b"private-identity-token"
        with tempfile.NamedTemporaryFile() as credential_file:
            credential_file.write(b"private-federated-credential-contents")
            credential_file.flush()
            environment = {
                "GOOGLE_BACKEND_CREDENTIALS": credential_file.name,
                "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE": "/normal/deployer-auth.json",
            }
            result = subprocess.CompletedProcess([], 0, private_token, b"private stderr")
            captured = io.StringIO()
            with (
                patch.dict(os.environ, environment),
                patch.object(lifecycle.Commands, "json", return_value=self.service()),
                patch.object(lifecycle.subprocess, "run", return_value=result) as run,
                patch.object(Path, "read_text", side_effect=AssertionError("must not read")),
                patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")),
                patch("builtins.open", side_effect=AssertionError("must not read")),
                patch.object(lifecycle.urllib.request, "urlopen", return_value=io.BytesIO(
                    json.dumps({
                        "database": "haunted_halls_web_pr_41", "operation": "create", "created": False,
                    }).encode(),
                )),
                contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured),
            ):
                self.assertFalse(self.deployment().ensure_database())
                token_call = run.call_args
                self.assertEqual(
                    token_call.kwargs["env"]["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"],
                    credential_file.name,
                )
                self.assertEqual(
                    os.environ["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"],
                    "/normal/deployer-auth.json",
                )
                lifecycle.Commands.run(["gcloud", "ordinary", "read"], label="Ordinary read")
                self.assertIsNone(run.call_args.kwargs["env"])
                self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(captured.getvalue(), "")

    def test_token_failure_hides_credentials_path_contents_and_raw_stderr(self):
        with (
            tempfile.NamedTemporaryFile() as credential_file,
            patch.dict(os.environ, {"GOOGLE_BACKEND_CREDENTIALS": credential_file.name}),
            patch.object(lifecycle.Commands, "json", return_value=self.service()),
            patch.object(lifecycle.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, b"private-token", b"private credential contents and stderr",
            )),
            patch.object(lifecycle.urllib.request, "urlopen") as urlopen,
        ):
            with self.assertRaises(lifecycle.LifecycleError) as error:
                self.deployment().ensure_database()
            self.assertEqual(str(error.exception), "Database provisioner identity token failed.")
            urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
