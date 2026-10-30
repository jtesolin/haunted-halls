import contextlib
import io
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, Mock, patch

from test_lifecycle import lifecycle


class UnauthenticatedProbeTests(unittest.TestCase):
    def exercise(self, status, location="", frontend=True, allowed=False, http_error=True):
        output = io.StringIO()
        opener = Mock()
        headers = {
            "Location": location, "Set-Cookie": "private-cookie",
            "Authorization": "private-authorization", "X-Goog-IAP-JWT-Assertion": "private-assertion",
        } if location is not None else None
        if http_error:
            opener.open.side_effect = urllib.error.HTTPError(
                "https://private-url.run.app/?private-query", status, "private-reason",
                headers, io.BytesIO(b"private-body"),
            )
        else:
            response = MagicMock(status=status, headers=headers)
            response.__enter__.return_value = response
            opener.open.return_value = response
        with (
            contextlib.redirect_stdout(output),
            patch.object(lifecycle.urllib.request, "build_opener", return_value=opener),
        ):
            if allowed:
                lifecycle.verify_unauthenticated_denied("https://preview.run.app/", frontend)
            else:
                with self.assertRaises(lifecycle.LifecycleError) as caught:
                    lifecycle.verify_unauthenticated_denied("https://preview.run.app/", frontend)
                self.assertIn("result=fail", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.header_items(), [])
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 20})
        self.assertNotIn("private", output.getvalue())
        return output.getvalue()

    def test_denial_statuses_pass_for_frontend_and_engine(self):
        for frontend in (True, False):
            for status in (401, 403):
                with self.subTest(frontend=frontend, status=status):
                    output = self.exercise(status, None, frontend, allowed=True)
                    self.assertIn(f"resource={'frontend' if frontend else 'engine'}", output)
                    self.assertIn(f"status={status} redirect=no destination=none", output)
                    self.assertIn("assertion=http-auth-denial result=pass", output)

    def test_frontend_accepts_only_302_to_exact_https_google_accounts(self):
        output = self.exercise(
            302, "https://accounts.google.com/o/oauth2/auth?private-query", allowed=True
        )
        self.assertIn("redirect=yes destination=google-accounts", output)
        self.assertIn("assertion=iap-sign-in-redirect result=pass", output)
        self.assertNotIn("private", output)
        for location in (
            "", None, "/login", "http://accounts.google.com/auth",
            "https://accounts.google.com.evil.example/auth",
            "https://user@accounts.google.com/auth",
            "https://accounts.google.com:443/auth",
            "https://evil.google.com/auth", "https://[malformed",
            "https://accounts.google.com/\nprivate-header", ["private-location"],
        ):
            with self.subTest(location=location):
                self.exercise(302, location)
        for status in (301, 303, 307, 308):
            with self.subTest(status=status):
                output = self.exercise(status, "https://accounts.google.com/auth")
                self.assertIn("assertion=unexpected-redirect-status", output)

    def test_engine_never_accepts_redirects_even_to_google(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                output = self.exercise(status, "https://accounts.google.com/auth", frontend=False)
                self.assertIn("endpoint=engine-health", output)
                self.assertIn("assertion=engine-redirect-forbidden", output)

    def test_success_and_service_errors_are_distinct_but_both_fail_closed(self):
        for frontend in (True, False):
            for status in (200, 201, 204, 404, 429, 500, 502, 503):
                with self.subTest(frontend=frontend, status=status):
                    output = self.exercise(
                        status, frontend=frontend, http_error=status >= 400
                    )
                    assertion = "unexpected-success" if status < 300 else "unexpected-http-status"
                    self.assertIn(f"status={status}", output)
                    self.assertIn(f"assertion={assertion} result=fail", output)

    def test_malformed_or_missing_status_fails_without_emitting_raw_value(self):
        for status in (None, True, "private-status", [], {}, 0, 600):
            with self.subTest(status=status):
                output = self.exercise(status, http_error=False)
                self.assertIn("status=unavailable", output)
                self.assertIn("assertion=malformed-response-status", output)
                self.assertNotIn("private", output)

    def test_transport_failure_is_sanitized(self):
        output = io.StringIO()
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("private-provider-details")
        with (
            contextlib.redirect_stdout(output),
            patch.object(lifecycle.urllib.request, "build_opener", return_value=opener),
            self.assertRaises(lifecycle.LifecycleError) as caught,
        ):
            lifecycle.verify_unauthenticated_denied("https://preview.run.app/?private-query", True)
        self.assertIn("assertion=transport-failure", output.getvalue())
        self.assertNotIn("private", output.getvalue() + str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_diagnostics_do_not_emit_response_bodies_headers_or_redirect_contents(self):
        output = self.exercise(302, "https://untrusted.example/private-path?private-token=secret")
        self.assertIn("destination=untrusted", output)
        for private in ("untrusted.example", "private", "secret", "https://"):
            self.assertNotIn(private, output)

    def test_real_opener_does_not_follow_redirect_or_send_authentication(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path, dict(self.headers)))
                self.send_response(302)
                self.send_header("Location", "/login?private-token")
                self.send_header("Set-Cookie", "private-cookie")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(lifecycle.LifecycleError):
                lifecycle.verify_unauthenticated_denied(
                    f"http://127.0.0.1:{server.server_port}/", True
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "/")
        self.assertNotIn("Authorization", received[0][1])
        self.assertNotIn("Cookie", received[0][1])


if __name__ == "__main__":
    unittest.main()
