import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

import yaml
from paho.mqtt import client as mqtt
from pymodbus.client import ModbusTcpClient

from .discover import DiscoveryService

MQTT_URL = os.environ.get("MQTT_URL", "mqtt://localhost:1883")
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
DEVICES_PATH = Path(os.environ.get("DEVICES_PATH", "./config/devices.yaml"))
MAP_FILE = Path(os.environ.get("MAP_FILE", "./edge/modbus_map.yaml"))
DISCOVERY_ENABLED = os.environ.get("DISCOVERY_ENABLED", "true").lower() == "true"


def parse_url(url: str) -> tuple[str, int]:
    host = url.split("://", 1)[1]
    if ":" in host:
        host, port = host.split(":", 1)
        return host, int(port)
    return host, 1883


class DeviceRegistry:
    def __init__(self, devices_path: Path, map_file: Path) -> None:
        self.devices_path = devices_path
        self.map_file = map_file
        self.devices: Dict[str, Dict] = {}
        self.maps: Dict[str, Dict] = {}
        self.reload()

    def reload(self) -> None:
        if self.devices_path.exists():
            with self.devices_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            self.devices = {item["id"]: item for item in data.get("devices", [])}
            self.maps = data.get("maps", {})
        else:
            self.devices = {}
            self.maps = {}
        if self.map_file.exists():
            with self.map_file.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            self.maps.update(data.get("maps", {}))

    def update_from_payload(self, payload: Dict[str, Any]) -> None:
        device_id = payload.get("id")
        if not device_id:
            return
        self.devices[device_id] = payload

    def get_device(self, device_id: str) -> Dict[str, Any]:
        return self.devices.get(device_id, {})

    def get_map(self, map_name: str) -> Dict[str, any]:
        return self.maps.get(map_name, {})


registry = DeviceRegistry(DEVICES_PATH, MAP_FILE)
discovery_service = DiscoveryService()

HOST, PORT = parse_url(MQTT_URL)
client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)


def write_modbus(device_id: str, setpoints: Dict[str, float]) -> None:
    device = registry.get_device(device_id)
    if not device:
        return
    register_map = registry.get_map(device.get("map"))
    if not register_map:
        return
    client_mb = ModbusTcpClient(device["host"], port=device.get("port", 502))
    if not client_mb.connect():
        return
    try:
        for key, value in setpoints.items():
            entry = register_map.get("registers", {}).get(key)
            if not entry:
                continue
            scale = entry.get("scale", 1)
            reg_value = int(round(value * scale))
            address = entry.get("address") - 40001
            client_mb.write_register(address, reg_value)
    finally:
        client_mb.close()


def publish_discovery(subnet: str, actor: str = "system") -> None:
    if not DISCOVERY_ENABLED:
        return
    result = discovery_service.scan(subnet)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw_payload = {
        "ts": ts,
        "subnet": subnet,
        "duration_s": result["duration"],
        "raw": result["raw"],
        "actor": actor,
    }
    devices_payload = {
        "ts": ts,
        "subnet": subnet,
        "duration_s": result["duration"],
        "devices": result["devices"],
        "actor": actor,
    }
    client.publish("discover/raw", json.dumps(raw_payload), qos=1, retain=False)
    client.publish("discover/results", json.dumps(devices_payload), qos=1, retain=False)


def on_command(_client, _userdata, msg) -> None:
    payload = json.loads(msg.payload.decode())
    device_id = payload.get("device_id")
    if not device_id:
        return
    setpoints = payload.get("set", {})
    write_modbus(device_id, setpoints)
    receipt = {
        "ts": payload.get("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        "device_id": device_id,
        "status": "applied",
        "applied": setpoints,
        "latency_ms": 100,
        "notes": "edge write",
    }
    client.publish(f"ctrl/{device_id}/receipt", json.dumps(receipt), qos=1)


def on_discover(_client, _userdata, msg) -> None:
    payload = json.loads(msg.payload.decode())
    subnet = payload.get("subnet", "10.0.0.0/24")
    actor = payload.get("actor", "system")
    threading.Thread(target=publish_discovery, args=(subnet, actor), daemon=True).start()


def on_discover_approved(_client, _userdata, msg) -> None:
    payload = json.loads(msg.payload.decode())
    registry.update_from_payload(payload.get("device", {}))
    registry.reload()
    device = registry.get_device(payload.get("device", {}).get("id", ""))
    if device:
        self_test_device(device)


def self_test_device(device: Dict[str, Any]) -> None:
    if device.get("proto") != "modbus":
        return
    client_mb = ModbusTcpClient(device["host"], port=device.get("port", 502), timeout=1)
    try:
        if client_mb.connect():
            client_mb.read_device_info()
    finally:
        client_mb.close()


client.on_message = lambda *_: None
client.message_callback_add("ctrl/+/set", on_command)
client.message_callback_add("ctrl/discover/start", on_discover)
client.message_callback_add("discover/approved", on_discover_approved)
client.connect(HOST, PORT, 60)
client.subscribe("ctrl/+/set", qos=1)
client.subscribe("ctrl/discover/start", qos=1)
client.subscribe("discover/approved", qos=1)
client.loop_forever()
