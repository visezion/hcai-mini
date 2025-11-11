import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Dict

import numpy as np
import paho.mqtt.publish as publish

from .api import start_http

MQTT_HOST = os.environ.get("SIM_MQTT_HOST", "localhost")
SITE = os.environ.get("SIM_SITE", "sim_dc")
RACKS = os.environ.get("SIM_RACKS", "R1,R2,R3,R4").split(",")
INTERVAL = float(os.environ.get("SIM_INTERVAL", "2"))
CONTROL_PATH = Path(os.environ.get("SIM_CONTROL_PATH", "/simulator/control.json"))

SCENARIOS = {
    "temp_spike": "Rapid temperature rise",
    "cooling_failure": "Cooling failure in zone",
    "sensor_dropout": "Sensor dropout",
    "power_spike": "Power/UPS spike",
}


def base_state() -> Dict[str, float]:
    return {
        "temp_c": 24.0,
        "hum_pct": 45.0,
        "power_kw": 3.5,
        "airflow_cfm": 150.0,
        "fan_rpm": 1200.0,
        "ups_load_pct": 35.0,
    }


class DataCenterSimulator:
    def __init__(self) -> None:
        self.state: Dict[str, Dict[str, float]] = {rack: base_state().copy() for rack in RACKS}
        self.active: Dict[str, bool] = {name: False for name in SCENARIOS}

    def set_scenario(self, name: str, enabled: bool) -> None:
        if name in self.active:
            self.active[name] = enabled

    def _apply(self, rack: str) -> None:
        state = self.state[rack]
        if self.active.get("temp_spike"):
            state["temp_c"] += random.uniform(0.5, 1.5)
            state["fan_rpm"] += random.uniform(30, 60)
        if self.active.get("cooling_failure") and rack in RACKS[:2]:
            state["temp_c"] += random.uniform(2.0, 4.0)
            state["airflow_cfm"] -= random.uniform(10, 20)
        if self.active.get("sensor_dropout") and rack == RACKS[-1]:
            state["temp_c"] = np.nan
            state["hum_pct"] = np.nan
        if self.active.get("power_spike"):
            state["power_kw"] += random.uniform(0.5, 1.0)
            state["ups_load_pct"] += random.uniform(5, 10)

    def _decay(self, rack: str) -> None:
        baseline = base_state()
        state = self.state[rack]
        for key, target in baseline.items():
            if np.isnan(state[key]):
                continue
            state[key] += (target - state[key]) * 0.05
            state[key] += random.uniform(-0.1, 0.1)

    def tick(self) -> None:
        for rack in RACKS:
            self._apply(rack)
            self._decay(rack)
            self._publish(rack)

    def _publish(self, rack: str) -> None:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "site": SITE,
            "rack": rack,
            "metrics": {k: (None if np.isnan(v) else round(v, 2)) for k, v in self.state[rack].items()},
        }
        publish.single(
            f"site/{SITE}/rack/{rack}/telemetry",
            json.dumps(payload),
            hostname=MQTT_HOST,
            qos=1,
        )


SIM = DataCenterSimulator()


def control_poll_loop() -> None:
    while True:
        if CONTROL_PATH.exists():
            try:
                data = json.loads(CONTROL_PATH.read_text())
            except json.JSONDecodeError:
                data = {}
            for name, val in data.items():
                SIM.set_scenario(name, bool(val))
        time.sleep(1)


def main_loop() -> None:
    while True:
        SIM.tick()
        time.sleep(INTERVAL)


def start() -> None:
    threading.Thread(target=start_http, daemon=True).start()
    threading.Thread(target=control_poll_loop, daemon=True).start()
    main_loop()


if __name__ == "__main__":
    start()
