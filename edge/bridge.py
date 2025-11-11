import json
import os
import time
from pathlib import Path
from typing import Dict

import yaml
from paho.mqtt import client as mqtt
from pymodbus.client import ModbusTcpClient

from .discover import discover

MQTT_URL = os.environ.get("MQTT_URL", "mqtt://localhost:1883")
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
DEVICES_PATH = Path(os.environ.get("DEVICES_PATH", "./config/devices.yaml"))
MAP_FILE = Path(os.environ.get("MAP_FILE", "./edge/modbus_map.yaml"))


def parse_url(url: str) -> tuple[str, int]:
    host = url.split("://", 1)[1]
    if ":" in host:
        host, port = host.split(":", 1)
        return host, int(port)
    return host, 1883


def load_devices() -> Dict[str, Dict]:
    if not DEVICES_PATH.exists():
        return {}
    with DEVICES_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    devices = {item["id"]: item for item in data.get("devices", [])}
    return devices


def load_maps() -> Dict[str, Dict]:
    if MAP_FILE.exists():
        with MAP_FILE.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data.get("maps", {})
    return {}


DEVICES = load_devices()
MAPS = load_maps()


def write_modbus(device_id: str, setpoints: Dict[str, float]) -> None:
    device = DEVICES.get(device_id)
    if not device:
        return
    register_map = MAPS.get(device.get("map")) or {}
    client = ModbusTcpClient(device["host"], port=device.get("port", 502))
    if not client.connect():
        return
    try:
        for key, value in setpoints.items():
            entry = register_map.get("registers", {}).get(key)
            if not entry:
                continue
            scale = entry.get("scale", 1)
            reg_value = int(round(value * scale))
            address = entry.get("address") - 40001
            client.write_register(address, reg_value)
    finally:
        client.close()


HOST, PORT = parse_url(MQTT_URL)
client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)


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
        "notes": "edge mock write",
    }
    client.publish(f"ctrl/{device_id}/receipt", json.dumps(receipt), qos=1)


def on_discover(_client, _userdata, msg) -> None:
    payload = json.loads(msg.payload.decode())
    subnet = payload.get("subnet", "10.0.0.0/24")
    devices = discover(subnet)
    message = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "devices": devices}
    client.publish("ctrl/discover/results", json.dumps(message), qos=1, retain=False)


client.on_message = lambda *_: None
client.message_callback_add("ctrl/+/set", on_command)
client.message_callback_add("ctrl/discover/start", on_discover)
client.connect(HOST, PORT, 60)
client.subscribe("ctrl/+/set", qos=1)
client.subscribe("ctrl/discover/start", qos=1)
client.loop_forever()
