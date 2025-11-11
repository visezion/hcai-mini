import json
import threading
from typing import Callable

from paho.mqtt import client as mqtt

from .config import get_settings


class Bus:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = mqtt.Client()
        if self.settings.mqtt_user:
            self.client.username_pw_set(self.settings.mqtt_user, self.settings.mqtt_pass)
        self.host, self.port = self._parse_url(self.settings.mqtt_url)

    @staticmethod
    def _parse_url(url: str) -> tuple[str, int]:
        host = url.split("://", 1)[1]
        if ":" in host:
            host, port = host.split(":", 1)
            return host, int(port)
        return host, 1883

    def start(self, on_message: Callable) -> None:
        self.client.on_message = on_message
        self.client.connect(self.host, self.port, 60)
        self.client.subscribe("site/+/rack/+/telemetry", qos=1)
        self.client.subscribe("device/+/status", qos=1)
        self.client.subscribe("ctrl/+/receipt", qos=1)
        self.client.subscribe("discover/#", qos=1)
        threading.Thread(target=self.client.loop_forever, daemon=True).start()

    def publish(self, topic: str, payload: dict, qos: int = 1, retain: bool = False) -> None:
        self.client.publish(topic, json.dumps(payload), qos=qos, retain=retain)

    def publish_text(self, topic: str, payload: str, qos: int = 1, retain: bool = False) -> None:
        self.client.publish(topic, payload, qos=qos, retain=retain)
