"""Combined Mock Reolink Camera that sends webhooks and handles snap requests from the app."""

import base64
import json
import ssl
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES_DIR = Path("/fixtures")
STATE = {"active_fixture": ""}

# Minimal valid 1x1 dark JPEG fallback when no fixture is staged
_FALLBACK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////"
    "////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBAB"
    "AAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    """Send JSON with correct headers."""
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _serve_snap(handler: BaseHTTPRequestHandler, query: str) -> None:
    """Serve a test snapshot image."""
    params = parse_qs(query)
    if params.get("cmd") != ["Snap"]:
        _send_json(handler, 400, {"error": "Unsupported cmd"})
        return

    fixture = STATE["active_fixture"]
    if fixture and (FIXTURES_DIR / fixture).is_file():
        img_bytes = (FIXTURES_DIR / fixture).read_bytes()
    else:
        img_bytes = _FALLBACK_JPEG

    handler.send_response(200)
    handler.send_header("Content-Type", "image/jpeg")
    handler.send_header("Content-Length", str(len(img_bytes)))
    handler.end_headers()
    handler.wfile.write(img_bytes)


class HttpControlHandler(BaseHTTPRequestHandler):
    """Serves control API (/health, /stage, /trigger-webhook) and HTTP Snap on :8080."""

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Handle GET requests from the app."""
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _send_json(
                self,
                200,
                {
                    "status": "ok",
                    "active_fixture": STATE["active_fixture"] or "blank",
                },
            )
            return

        if parsed.path == "/cgi-bin/api.cgi":
            _serve_snap(self, parsed.query)
            return

        _send_json(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        """Send a test webhook to the app."""
        parsed = urlparse(self.path)
        if parsed.path.startswith("/stage/"):
            raw_name = parsed.path.removeprefix("/stage/")
            safe_name = Path(raw_name).name
            target = (FIXTURES_DIR / safe_name).resolve()
            if (
                not safe_name
                or target.parent != FIXTURES_DIR.resolve()
                or not target.is_file()
            ):
                _send_json(self, 404, {"error": f"Fixture not found: {raw_name}"})
                return
            STATE["active_fixture"] = safe_name
            _send_json(self, 200, {"staged": safe_name})
            return

        if parsed.path == "/trigger-webhook":
            length = int(self.headers.get("Content-Length", "0"))
            req_body = json.loads(self.rfile.read(length) or b"{}")
            target_url = req_body["target_url"]
            secret = req_body.get("secret", "")
            payload = json.dumps(req_body.get("payload", {})).encode("utf-8")

            req = urllib.request.Request(
                target_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Secret": secret,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    resp_bytes = resp.read()
                    _send_json(
                        self,
                        200,
                        {
                            "status_code": resp.status,
                            "body": json.loads(resp_bytes or b"{}"),
                        },
                    )
            except urllib.error.HTTPError as exc:
                _send_json(
                    self,
                    200,
                    {
                        "status_code": exc.code,
                        "body": exc.read().decode("utf-8", errors="replace"),
                    },
                )
            return

        _send_json(self, 404, {"error": "Not found"})

    def log_message(
        self, format: str, *args: object
    ) -> None:  # pylint: disable=redefined-builtin
        """Suppress noisy default stderr request logs during pytest runs."""
        return


class HttpsCameraHandler(BaseHTTPRequestHandler):
    """Serves HTTPS :443 Reolink Snap API + web UI for Traefik /cctv1 tests."""

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Handle GET requests from the app."""
        parsed = urlparse(self.path)
        if parsed.path == "/cgi-bin/api.cgi":
            _serve_snap(self, parsed.query)
            return

        body = f"<h1>Mock Camera ({self.path})</h1>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(
        self, format: str, *args: object
    ) -> None:  # pylint: disable=redefined-builtin
        """Suppress noisy default stderr request logs during pytest runs."""
        return


def main() -> None:
    """This main needs no introduction (or docstring)."""
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            "/tmp/k.pem",
            "-out",
            "/tmp/c.pem",
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=mock-camera",
        ],
        check=True,
    )

    https_server = ThreadingHTTPServer(("0.0.0.0", 443), HttpsCameraHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("/tmp/c.pem", "/tmp/k.pem")
    https_server.socket = ctx.wrap_socket(https_server.socket, server_side=True)
    threading.Thread(target=https_server.serve_forever, daemon=True).start()

    http_server = ThreadingHTTPServer(("0.0.0.0", 8080), HttpControlHandler)
    http_server.serve_forever()


if __name__ == "__main__":
    main()
