"""Small HTTP adapter for the stdin/stdout C++ potential solver."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ENGINE = os.getenv("SPAT_POTENTIAL_ENGINE", "/usr/local/bin/spat-potential-engine")
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, body):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, '{"status":"ok"}')
        else:
            self._json(404, '{"error":"not found"}')

    def do_POST(self):
        path = urlsplit(self.path).path
        if path != "/v1/calculate" and not path.startswith("/v1/projects/"):
            self._json(404, '{"error":"not found"}')
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(413, '{"error":"request too large"}')
            return
        payload = self.rfile.read(length)
        project_id = self.headers.get("X-Project-ID")
        if path.startswith("/v1/projects/"):
            project_id = path.removeprefix("/v1/projects/").split("/", 1)[0]
            if not project_id:
                self._json(400, '{"error":"project id is required"}')
                return
        try:
            completed = subprocess.run(
                [ENGINE], input=payload, capture_output=True, timeout=75, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._json(502, '{"error":"potential engine unavailable"}')
            self.log_error("engine invocation failed: %s", exc)
            return
        if completed.returncode:
            detail = completed.stdout.decode(errors="replace") or completed.stderr.decode(errors="replace")
            self._json(422, json.dumps({"error": detail}))
            return
        response = completed.stdout
        self.send_response(200)
        if project_id:
            self.send_header("X-Project-ID", project_id)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler).serve_forever()
