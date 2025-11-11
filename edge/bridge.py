import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from paho.mqtt import client as mqtt
from pymodbus.client import ModbusTcpClient

from .discover import DiscoveryService

try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
    )

    HAS_SNMP = True
except ImportError:  # pragma: no cover
    HAS_SNMP = False

MQTT_URL = os.environ.get("MQTT_URL", "mqtt://localhost:1883")
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
DEVICES_PATH = Path(os.environ.get("DEVICES_PATH", "./config/devices.yaml"))
MAP_FILE = Path(os.environ.get("MAP_FILE", "./edge/modbus_map.yaml"))
DISCOVERY_ENABLED = os.environ.get("DISCOVERY_ENABLED", "true").lower() == "true"
DEFAULT_SITE = os.environ.get("SITE_ID", "dc1")
DEFAULT_POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "10"))
SNMP_COMMUNITY = os.environ.get("DISCOVERY_SNMP_COMMUNITY", "public")


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
        combined_maps: Dict[str, Dict] = {}
        if self.devices_path.exists():
            with self.devices_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            self.devices = {item["id"]: item for item in data.get("devices", [])}
            combined_maps.update(data.get("maps", {}))
        else:
            self.devices = {}
        if self.map_file.exists():
            with self.map_file.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            combined_maps.update(data.get("maps", {}))
        self.maps = combined_maps

    def update_from_payload(self, payload: Dict[str, Any]) -> None:
        device_id = payload.get("id")
        if not device_id:
            return
        self.devices[device_id] = payload

    def get_device(self, device_id: str) -> Dict[str, Any]:
        return self.devices.get(device_id, {})

    def get_control_map(self, map_name: str) -> Dict[str, Any]:
        mapping = self.maps.get(map_name, {})
        if "control" in mapping:
            return mapping["control"]
        return mapping

    def get_telemetry_map(self, map_name: str) -> Dict[str, Any]:
        mapping = self.maps.get(map_name, {})
        return mapping.get("telemetry", {})

    def device_site(self, device: Dict[str, Any]) -> str:
        return device.get("site") or DEFAULT_SITE

    def device_rack(self, device: Dict[str, Any]) -> str:
        return device.get("rack") or device.get("id", "rack")

    def device_interval(self, device: Dict[str, Any]) -> float:
        return float(device.get("poll_interval", DEFAULT_POLL_INTERVAL))


registry = DeviceRegistry(DEVICES_PATH, MAP_FILE)
discovery_service = DiscoveryService()

HOST, PORT = parse_url(MQTT_URL)
client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
pollers_lock = threading.Lock()
pollers: Dict[str, "TelemetryPoller"] = {}


class TelemetryPoller(threading.Thread):
    def __init__(self, device_id: str) -> None:
        super().__init__(daemon=True)
        self.device_id = device_id
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        while not self.stop_event.is_set():
            device = registry.get_device(self.device_id)
            if not device:
                return
            metrics = self.collect_metrics(device)
            if metrics:
                payload = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "site": registry.device_site(device),
                    "rack": registry.device_rack(device),
                    "device_id": self.device_id,
                    "metrics": metrics,
                }
                topic = f"site/{payload['site']}/rack/{payload['rack']}/telemetry"
                client.publish(topic, json.dumps(payload), qos=1)
            interval = max(1.0, registry.device_interval(device))
            if self.stop_event.wait(interval):
                return

    def collect_metrics(self, device: Dict[str, Any]) -> Optional[Dict[str, float]]:
        proto = device.get("proto")
        if proto == "modbus":
            return self.collect_modbus(device)
        if proto == "snmp" and HAS_SNMP:
            return self.collect_snmp(device)
        return None

    def collect_modbus(self, device: Dict[str, Any]) -> Optional[Dict[str, float]]:
        telemetry_map = registry.get_telemetry_map(device.get("map"))
        if not telemetry_map:
            return None
        client_mb = ModbusTcpClient(device["host"], port=device.get("port", 502), timeout=1)
        metrics: Dict[str, float] = {}
        try:
            if not client_mb.connect():
                return None
            unit_id = device.get("unit_id", 1)
            for name, meta in telemetry_map.items():
                address = meta.get("address")
                if address is None:
                    continue
                reg_type = meta.get("register_type", "holding")
                scale = meta.get("scale", 1)
                try:
                    if reg_type == "input":
                        result = client_mb.read_input_registers(address - 30001, 1, unit=unit_id)
                    else:
                        result = client_mb.read_holding_registers(address - 40001, 1, unit=unit_id)
                    if result.isError():
                        continue
                    value = result.registers[0]
                    metrics[name] = value / scale
                except Exception:
                    continue
            return metrics or None
        finally:
            client_mb.close()

    def collect_snmp(self, device: Dict[str, Any]) -> Optional[Dict[str, float]]:
        telemetry_map = registry.get_telemetry_map(device.get("map"))
        if not telemetry_map:
            return None
        metrics: Dict[str, float] = {}
        for name, meta in telemetry_map.items():
            oid = meta.get("oid")
            if not oid:
                continue
            scale = meta.get("scale", 1)
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(device.get("community", SNMP_COMMUNITY), mpModel=0),
                UdpTransportTarget((device["host"], device.get("port", 161)), timeout=1, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            try:
                errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
            except StopIteration:
                continue
            if errorIndication or errorStatus:
                continue
            try:
                value = float(varBinds[0][1])
                metrics[name] = value / scale
            except Exception:
                continue
        return metrics or None


def sync_pollers() -> None:
    with pollers_lock:
        for device_id in list(pollers.keys()):
            if device_id not in registry.devices:
                pollers[device_id].stop()
                del pollers[device_id]
        for device_id, device in registry.devices.items():
            if device_id in pollers:
                continue
            if device.get("proto") == "snmp" and not HAS_SNMP:
                continue
            if device.get("proto") not in ("modbus", "snmp"):
                continue
            poller = TelemetryPoller(device_id)
            pollers[device_id] = poller
            poller.start()


def write_modbus(device_id: str, setpoints: Dict[str, float]) -> None:
    device = registry.get_device(device_id)
    if not device:
        return
    register_map = registry.get_control_map(device.get("map"))
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
    sync_pollers()


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
sync_pollers()
client.loop_forever()
