import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

CONTROL_PATH = os.environ.get("SIM_CONTROL_PATH", "/simulator/control.json")
SCENARIOS = ["temp_spike", "cooling_failure", "sensor_dropout", "power_spike"]


class ScenarioHandler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path != "/scenarios":
            self.send_error(404)
            return
        try:
            with open(CONTROL_PATH, "r", encoding="utf-8") as handle:
                current = json.load(handle)
        except FileNotFoundError:
            current = {}
        self._json({"scenarios": current})

    def do_POST(self):
        if self.path != "/scenarios":
            self.send_error(404)
            return
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        filtered = {name: bool(val) for name, val in data.items() if name in SCENARIOS}
        with open(CONTROL_PATH, "w", encoding="utf-8") as handle:
            json.dump(filtered, handle)
        self._json({"status": "updated", "scenarios": filtered})


def start_http():
    host = os.environ.get("SIM_API_HOST", "0.0.0.0")
    port = int(os.environ.get("SIM_API_PORT", "9100"))
    httpd = HTTPServer((host, port), ScenarioHandler)
    httpd.serve_forever()

