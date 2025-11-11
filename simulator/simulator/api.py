import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

CONTROL_PATH = os.environ.get("SIM_CONTROL_PATH", "/simulator/control.json")
SCENARIOS = ["temp_spike", "cooling_failure", "sensor_dropout", "power_spike"]
SITE = os.environ.get("SIM_SITE", "sim_dc")
RACKS = [r.strip() for r in os.environ.get("SIM_RACKS", "R1,R2,R3,R4").split(",") if r.strip()]


def _device_list() -> list[dict]:
    devices = []
    for rack in RACKS:
        devices.append(
            {
                "id": f"sim_{rack.lower()}",
                "rack": rack,
                "site": SITE,
                "type": "crac",
                "proto": "sim",
                "host": "hcai-sim",
                "port": 0,
                "capabilities": ["cooling", "fan"],
            }
        )
    return devices


class ScenarioHandler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/scenarios":
            try:
                with open(CONTROL_PATH, "r", encoding="utf-8") as handle:
                    current = json.load(handle)
            except FileNotFoundError:
                current = {}
            self._json({"scenarios": current})
            return
        if self.path == "/devices":
            self._json({"devices": _device_list()})
            return
        self.send_error(404)

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
