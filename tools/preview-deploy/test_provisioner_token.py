import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
                "namespace": lifecycle.SOURCE_PROJECT_NUMBER,
                "labels": {"cloud.googleapis.com/location": lifecycle.SOURCE_REGION},
            },
            "status": {
                "url": (
                    f"https://{lifecycle.DB_PROVISIONER_SERVICE}-"
                    f"{lifecycle.SOURCE_PROJECT_NUMBER}.{lifecycle.SOURCE_REGION}.run.app"
                ),
            },
        }

    def test_only_exact_project_number_and_verified_legacy_origins_are_accepted(self):
        for origin in (
            self.service()["status"]["url"],
            "https://hh-preview-db-provisioner-lt5viwug5a-ue.a.run.app",
        ):
            for suffix in ("", "/"):
                with self.subTest(origin=origin, suffix=suffix):
                    service = self.service()
                    service["status"]["url"] = origin + suffix
                    self.assertEqual(lifecycle.database_provisioner_url(service), origin)
            for mutate in (
                lambda s: s["metadata"].update(name="other-service"),
                lambda s: s["metadata"].update(namespace="123456789012"),
                lambda s: s["metadata"]["labels"].update({"cloud.googleapis.com/location": "us-west1"}),
            ):
                service = self.service()
                service["status"]["url"] = origin
                mutate(service)
                with self.subTest(origin=origin, mutate=mutate), self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.database_provisioner_url(service)
            for invalid in (
                origin.replace("https:", "http:"),
                origin + ".attacker.example",
                origin + ":443",
                origin + ":invalid",
                origin + "/provision",
                origin + "/;params",
                origin + "?query=value",
                origin + "#fragment",
                origin.replace("https://", "https://user:password@"),
                "\n" + origin,
                origin.replace("https://", "https://\t"),
            ):
                service = self.service()
                service["status"]["url"] = invalid
                with self.subTest(url=invalid), self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.database_provisioner_url(service)
        for invalid in (
            None, 123, [], {}, "", "https://[malformed",
            "https://attacker.example",
            "https://other-service-lt5viwug5a-ue.a.run.app",
            "https://hh-preview-db-provisioner-aaaaaaaaaa-ue.a.run.app",
            "https://hh-preview-db-provisioner-lt5viwug5a-uw.a.run.app",
            "https://hh-preview-db-provisioner-123456789012.us-east1.run.app",
            "https://hh-preview-db-provisioner-458395246135.us-west1.run.app",
        ):
            service = self.service()
            service["status"]["url"] = invalid
            with self.subTest(url=invalid), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.database_provisioner_url(service)

    def test_real_provisioner_transport_refuses_redirects_without_forwarding_token(self):
        received = []
        status = 302

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(self.path)
                self.send_response(status)
                self.send_header("Location", "/untrusted")
                self.end_headers()

            def do_GET(self):
                received.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with (
                tempfile.NamedTemporaryFile() as credentials,
                patch.dict(os.environ, {"GOOGLE_BACKEND_CREDENTIALS": credentials.name}),
                patch.object(lifecycle.Commands, "json", return_value=self.service()),
                patch.object(lifecycle.Commands, "run", return_value=b"test-token"),
                patch.object(lifecycle, "database_provisioner_url",
                             return_value=f"http://127.0.0.1:{server.server_port}"),
            ):
                for status in (301, 302, 303, 307, 308):
                    received.clear()
                    with self.subTest(status=status), self.assertRaisesRegex(
                        lifecycle.LifecycleError, "provisioner failed",
                    ):
                        lifecycle.request_database("56", "create")
                    self.assertEqual(received, ["/provision"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_invalid_credential_paths_fail_before_token_or_request_without_leaking(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in (None, "", "relative-private.json", directory + "/missing.json", directory):
                environment = {} if value is None else {"GOOGLE_BACKEND_CREDENTIALS": value}
                with (
                    self.subTest(value=value),
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(lifecycle.Commands, "json", return_value=self.service()),
                    patch.object(lifecycle.Commands, "run") as run,
                    patch.object(lifecycle.urllib.request.OpenerDirector, "open") as urlopen,
                ):
                    with self.assertRaises(lifecycle.LifecycleError) as error:
                        self.deployment().ensure_database()
                    self.assertEqual(
                        str(error.exception),
                        "Database provisioner direct-WIF credential file is unavailable.",
                    )
                    run.assert_not_called()
                    urlopen.assert_not_called()

    def test_database_drop_rejects_mismatched_provisioner_url_before_token_or_request(self):
        invalid_services = []
        for namespace, host in (
            (
                "123456789012",
                "hh-preview-db-provisioner-123456789012.us-east1.run.app",
            ),
            (
                lifecycle.SOURCE_PROJECT_NUMBER,
                "other-service-458395246135.us-east1.run.app",
            ),
            (
                lifecycle.SOURCE_PROJECT_NUMBER,
                "hh-preview-db-provisioner-458395246135.us-west1.run.app",
            ),
        ):
            service = self.service()
            service["metadata"]["namespace"] = namespace
            service["status"]["url"] = f"https://{host}"
            invalid_services.append(service)

        with tempfile.NamedTemporaryFile() as credentials:
            for service in invalid_services:
                with (
                    patch.dict(os.environ, {"GOOGLE_BACKEND_CREDENTIALS": credentials.name}),
                    patch.object(lifecycle.Commands, "json", return_value=service),
                    patch.object(lifecycle.Commands, "run") as run,
                    patch.object(lifecycle.urllib.request.OpenerDirector, "open") as urlopen,
                ):
                    with self.assertRaises(lifecycle.LifecycleError):
                        lifecycle.request_database("56", "drop")
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
                patch.object(lifecycle.urllib.request.OpenerDirector, "open", return_value=io.BytesIO(
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
            patch.object(lifecycle.urllib.request.OpenerDirector, "open") as urlopen,
        ):
            with self.assertRaises(lifecycle.LifecycleError) as error:
                self.deployment().ensure_database()
            self.assertEqual(str(error.exception), "Database provisioner identity token failed.")
            urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
