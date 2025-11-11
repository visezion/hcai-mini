import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import paho.mqtt.publish as publish
from paho.mqtt import client as mqtt

from .api import start_http

MQTT_HOST = os.environ.get("SIM_MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("SIM_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("SIM_MQTT_USER", "")
MQTT_PASS = os.environ.get("SIM_MQTT_PASS", "")
SITE = os.environ.get("SIM_SITE", "sim_dc")
RACKS = [r.strip() for r in os.environ.get("SIM_RACKS", "R1,R2,R3,R4").split(",") if r.strip()]
INTERVAL = float(os.environ.get("SIM_INTERVAL", "2"))
CONTROL_PATH = Path(os.environ.get("SIM_CONTROL_PATH", "/simulator/control.json"))

SCENARIOS = {
    "temp_spike": "Rapid temperature rise",
    "cooling_failure": "Cooling failure in zone",
    "sensor_dropout": "Sensor dropout",
    "power_spike": "Power/UPS spike",
}

PUBLISH_ARGS: Dict[str, object] = {"hostname": MQTT_HOST, "port": MQTT_PORT}
if MQTT_USER:
    PUBLISH_ARGS["auth"] = {"username": MQTT_USER, "password": MQTT_PASS}


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
        self.control_targets: Dict[str, Dict[str, float]] = {}

    def set_scenario(self, name: str, enabled: bool) -> None:
        if name in self.active:
            self.active[name] = enabled

    def device_id(self, rack: str) -> str:
        return f"sim_{rack.lower()}"

    def rack_from_device(self, device_id: str) -> Optional[str]:
        for rack in RACKS:
            if self.device_id(rack) == device_id:
                return rack
        return None

    def apply_control(self, rack: str, setpoints: Dict[str, float]) -> Dict[str, float]:
        if rack not in self.state:
            return {}
        state = self.state[rack]
        applied: Dict[str, float] = {}
        if "fan_rpm" in setpoints:
            state["fan_rpm"] = float(setpoints["fan_rpm"])
            applied["fan_rpm"] = state["fan_rpm"]
        if "supply_temp_c" in setpoints:
            target = float(setpoints["supply_temp_c"])
            state["temp_c"] -= min(3.0, (state["temp_c"] - target) * 0.6)
            applied["supply_temp_c"] = target
        self.control_targets[rack] = applied
        return applied

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
            "device_id": self.device_id(rack),
            "metrics": {k: (None if np.isnan(v) else round(v, 2)) for k, v in self.state[rack].items()},
        }
        publish.single(
            f"site/{SITE}/rack/{rack}/telemetry",
            json.dumps(payload),
            qos=1,
            **PUBLISH_ARGS,
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


def start_control_listener() -> None:
    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_control(_client, _userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        device_id = payload.get("device_id")
        rack = SIM.rack_from_device(device_id) if device_id else None
        if not rack:
            return
        applied = SIM.apply_control(rack, payload.get("set", {}))
        receipt = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "device_id": device_id,
            "status": "applied",
            "applied": applied,
            "latency_ms": 50,
            "notes": "simulator control",
        }
        client.publish(f"ctrl/{device_id}/receipt", json.dumps(receipt), qos=1)

    client.on_message = on_control
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.subscribe("ctrl/+/set", qos=1)
    threading.Thread(target=client.loop_forever, daemon=True).start()


def start() -> None:
    threading.Thread(target=start_http, daemon=True).start()
    threading.Thread(target=control_poll_loop, daemon=True).start()
    start_control_listener()
    main_loop()


if __name__ == "__main__":
    start()
