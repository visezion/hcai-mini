import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class Settings:
    mqtt_url: str = os.environ.get("MQTT_URL", "mqtt://localhost:1883")
    mqtt_user: str = os.environ.get("MQTT_USER", "")
    mqtt_pass: str = os.environ.get("MQTT_PASS", "")
    db_path: str = os.environ.get("DB_PATH", "./data/hcai.sqlite")
    policy_path: str = os.environ.get("POLICY_PATH", "./config/policy.yaml")
    devices_path: str = os.environ.get("DEVICES_PATH", "./config/devices.yaml")
    mode: str = os.environ.get("MODE", "propose")
    ui_enable: bool = os.environ.get("UI_ENABLE", "true").lower() == "true"
    discovery_subnet: str = os.environ.get("DISCOVERY_SUBNET", "10.0.0.0/24")
    discovery_topic: str = os.environ.get("DISCOVERY_TOPIC", "ctrl/discover")
    discovery_timeout_s: int = int(os.environ.get("DISCOVERY_TIMEOUT_S", "180"))
    discovery_interval_hours: int = int(os.environ.get("DISCOVERY_INTERVAL_HOURS", "6"))
    template_dir: str = os.environ.get("DISCOVERY_TEMPLATE_DIR", "./config/templates")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _load_yaml(path: str) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_policy() -> Dict[str, Any]:
    return _load_yaml(get_settings().policy_path)


def get_devices() -> Dict[str, Any]:
    return _load_yaml(get_settings().devices_path)


def append_device(entry: Dict[str, Any]) -> str:
    settings = get_settings()
    devices = get_devices()
    devices_list = devices.get("devices", [])

    entry = entry.copy()
    if not entry.get("id"):
        entry["id"] = f"{entry.get('proto', 'dev')}_{entry.get('host', 'device')}"

    action = "added"
    replaced = False
    for idx, existing in enumerate(devices_list):
        if existing.get("id") == entry["id"]:
            devices_list[idx] = entry
            action = "updated"
            replaced = True
            break
        if (
            entry.get("host") == existing.get("host")
            and entry.get("proto") == existing.get("proto")
            and entry.get("port") == existing.get("port")
        ):
            devices_list[idx] = entry
            action = "updated"
            replaced = True
            break

    if not replaced:
        devices_list.append(entry)

    # Ensure there are no duplicate IDs after update
    deduped = {}
    for item in devices_list:
        deduped[item.get("id")] = item
    devices["devices"] = list(deduped.values())
    devices.setdefault("maps", {})
    path = Path(settings.devices_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(devices, handle, sort_keys=False)
    return action
