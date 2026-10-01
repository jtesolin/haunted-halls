import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from db_names import InvalidProvisioningRequest, validate_request
from provisioner import provision


MAX_BODY_BYTES = 1024
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("preview-db-provisioner")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/provision":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415)
            return

        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(411)
            return
        if not 0 < content_length <= MAX_BODY_BYTES:
            self.send_error(413)
            return

        try:
            request = json.loads(self.rfile.read(content_length))
            operation, database_name = validate_request(request)
        except (json.JSONDecodeError, UnicodeDecodeError, InvalidProvisioningRequest):
            self.send_error(400, "invalid provisioning request")
            return

        try:
            response = provision(operation, database_name)
        except Exception:
            logger.exception("Preview database provisioning failed")
            self.send_error(500, "preview database provisioning failed")
            return

        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        logger.info("request: %s", format_string % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler)
    server.serve_forever()
