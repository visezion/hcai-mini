import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..config import append_device, get_devices, get_policy, get_settings, remove_device
from ..features import FeatureStore
from ..metrics import (
    DISCOVER_DEVICES_APPROVED_TOTAL,
    DISCOVER_DEVICES_FOUND_TOTAL,
    DISCOVER_DURATION_SECONDS,
    DISCOVER_SCANS_TOTAL,
)
from ..models.anomaly_vae import VAEAnomaly
from ..models.forecaster import Forecaster
from ..models.mpc import MPCController
from ..policy.safety import Safety
from ..storage.db import DB
from ..storage.audit import record_audit


class DecisionEngine:
    def __init__(
        self,
        db: DB,
        bus,
        feature_store: FeatureStore,
        forecaster: Forecaster,
        anomaly: VAEAnomaly,
        controller: MPCController,
        safety: Safety,
    ) -> None:
        self.db = db
        self.bus = bus
        self.feature_store = feature_store
        self.forecaster = forecaster
        self.anomaly = anomaly
        self.controller = controller
        self.safety = safety
        self.policy = get_policy()
        self.settings = get_settings()
        self.mode = self.settings.mode
        self.latest_tiles: Dict[str, Dict[str, Any]] = {}
        self.discovery_results: List[Dict[str, Any]] = []
        self.discovery_state: Dict[str, Any] = {
            "status": "idle",
            "message": "Idle",
            "started_at": None,
            "error": None,
        }
        self.discovery_deadline: datetime | None = None
        self.discovery_timeout = self.settings.discovery_timeout_s
        self.discovery_history: List[Dict[str, Any]] = []
        self.ingest_count = 0
        self.last_ingest_ts: str | None = None
        self.started_at = datetime.now(timezone.utc)
        self.auto_enabled = True
        self.dynamic_devices: Dict[str, str] = {}
        self.devices_path = Path(self.settings.devices_path)
        self.devices_mtime = 0.0
        self.rack_device_map: Dict[str, str] = {}
        self.device_site_map: Dict[str, str] = {}
        self._reload_devices()

    def handle_message(self, _client, _userdata, msg) -> None:
        topic = msg.topic
        payload = msg.payload.decode()
        if topic.startswith("site/"):
            data = json.loads(payload)
            self._handle_telemetry(data)
        elif topic.startswith("ctrl/") and topic.endswith("/receipt"):
            data = json.loads(payload)
            self.db.record_receipt({
                "ts": data.get("ts"),
                "device_id": data.get("device_id"),
                "status": data.get("status"),
                "applied_json": json.dumps(data.get("applied", {})),
                "latency_ms": data.get("latency_ms"),
                "notes": data.get("notes"),
            })
        elif topic == "discover/raw":
            data = json.loads(payload)
            raw_entries = data.get("raw", [])
            self.discovery_history.append({"ts": data.get("ts"), "raw_count": len(raw_entries)})
            self.discovery_history = self.discovery_history[-50:]
        elif topic == "discover/results":
            data = json.loads(payload)
            self.discovery_results = data.get("devices", [])
            count = len(self.discovery_results)
            duration = data.get("duration_s")
            DISCOVER_DEVICES_FOUND_TOTAL.inc(count)
            if duration:
                DISCOVER_DURATION_SECONDS.observe(duration)
            self.discovery_state = {
                "status": "done",
                "message": f"Found {count} device(s)" if count else "No devices discovered",
                "started_at": self.discovery_state.get("started_at"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
            record_audit(self.db, "system", "discover_results", data)
            self.discovery_deadline = None
        elif topic in {"discover/approved", "discover/removed"}:
            self._reload_devices()
        else:
            # ignore
            pass

    def _handle_telemetry(self, data: Dict[str, Any]) -> None:
        rack = data.get("rack", "unknown")
        metrics = data.get("metrics", {})
        device_id = data.get("device_id")
        if device_id and rack:
            self.dynamic_devices[rack] = device_id
        temp = metrics.get("temp_c")
        if temp is not None:
            self.feature_store.push(rack, "temp_c", temp)
        self.db.insert(
            "telemetry",
            {
                "ts": data.get("ts"),
                "site": data.get("site"),
                "rack": rack,
                "temp_c": temp,
                "hum_pct": metrics.get("hum_pct"),
                "power_kw": metrics.get("power_kw"),
                "airflow_cfm": metrics.get("airflow_cfm"),
                "raw_json": json.dumps(data),
            },
        )
        ts = data.get("ts")
        self.latest_tiles[rack] = {
            "ts": ts,
            "metrics": metrics,
        }
        self._maybe_act(rack, metrics)
        self.ingest_count += 1
        self.last_ingest_ts = ts

    def _maybe_act(self, rack: str, metrics: Dict[str, Any]) -> None:
        window = self.feature_store.get_window(rack, "temp_c")
        preds, lo, hi = self.forecaster.predict(window)
        score, alarm = self.anomaly.score(window)
        self.db.insert(
            "forecasts",
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "horizon_s": 60,
                "rack": rack,
                "temp_pred": preds[0] if preds else None,
                "temp_lo": lo[0] if lo else None,
                "temp_hi": hi[0] if hi else None,
                "power_pred": None,
            },
        )
        self.db.insert(
            "anomalies",
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "rack": rack,
                "score": score,
                "threshold": self.anomaly.threshold,
                "is_alarm": 1 if alarm else 0,
            },
        )
        triggers: List[str] = []
        temp_limit = self.policy["limits"]["temp_c"]["max"]
        forecast_target = None
        if preds:
            idx = 5 if len(preds) > 5 else 0
            forecast_target = preds[idx]
        if alarm:
            triggers.append("vae")
        current_temp = metrics.get("temp_c")
        if current_temp is not None and current_temp >= temp_limit:
            triggers.append("temp_limit")
        if forecast_target is not None and forecast_target >= temp_limit:
            triggers.append("forecast")
        if len(window) >= 6:
            delta = window[-1] - window[-6]
            if delta >= 0.8:
                triggers.append("temp_trend")
        power_kw = metrics.get("power_kw")
        if power_kw is not None and power_kw >= self.policy.get("power_alarm_kw", 5.5):
            triggers.append("power_spike")
        hum = metrics.get("hum_pct")
        humidity_limits = self.policy.get("humidity", {})
        if hum is not None and humidity_limits:
            if hum < humidity_limits.get("min", -999) or hum > humidity_limits.get("max", 999):
                triggers.append("humidity")
        if not triggers:
            return
        current = {"supply_temp_c": 18.0, "fan_rpm": 1200}
        proposal = self.controller.propose(preds, current)
        safe = self.safety.enforce(current, proposal)
        explanation = self._explain_action(rack, preds, score, triggers)
        device_id = self._device_for_rack(rack) or self.policy.get("site", "device")
        reason = "forecast_risk_high"
        if "temp_limit" in triggers:
            reason = "temperature_limit"
        elif "temp_trend" in triggers:
            reason = "temperature_trend"
        elif "power_spike" in triggers:
            reason = "power_spike"
        elif "humidity" in triggers:
            reason = "humidity_out_of_range"
        elif "vae" in triggers:
            reason = "anomaly"
        action_payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "device_id": device_id,
            "cmd": "setpoints",
            "set": {k: safe[k] for k in ("supply_temp_c", "fan_rpm")},
            "mode": self.mode,
            "reason": reason,
            "ticket": "HCAI-BOOTSTRAP",
            "constraints": self.policy.get("limits", {}),
            "safety_summary": safe["safety_summary"],
            "explain": explanation,
        }
        status = "pending_manual" if not self.auto_enabled else "queued"
        action_id = self.db.record_action(
            {
                "ts": action_payload["ts"],
                "device_id": action_payload["device_id"],
                "cmd_json": action_payload,
                "mode": self.mode,
                "status": status,
                "reason": action_payload["reason"],
                "model_version": "bootstrap",
                "safety_summary": safe["safety_summary"],
            }
        )
        if self.auto_enabled and self.mode.startswith("auto"):
            topic = f"ctrl/{action_payload['device_id']}/set"
            self.bus.publish(topic, action_payload)
            self.db.update_action_status(action_id, "sent")
        else:
            topic = "ctrl/proposals"
            self.bus.publish(topic, action_payload)
            self.db.update_action_status(action_id, "pending_manual")

    def start_discovery(self, subnet: str, actor: str = "system") -> None:
        now = datetime.now(timezone.utc)
        payload = {"subnet": subnet, "ts": now.isoformat(), "actor": actor}
        self.bus.publish("ctrl/discover/start", payload)
        record_audit(self.db, actor, "discover_start", payload)
        DISCOVER_SCANS_TOTAL.inc()
        self.discovery_results = []
        self.discovery_state = {
            "status": "running",
            "message": f"Scanning {subnet}",
            "started_at": now.isoformat(),
            "error": None,
        }
        self.discovery_deadline = now + timedelta(seconds=self.discovery_timeout)

    def list_discoveries(self) -> Dict[str, Any]:
        if (
            self.discovery_state.get("status") == "running"
            and self.discovery_deadline
            and datetime.now(timezone.utc) > self.discovery_deadline
        ):
            self.discovery_state = {
                "status": "error",
                "message": "Edge bridge did not respond",
                "started_at": self.discovery_state.get("started_at"),
                "error": f"timeout>{self.discovery_timeout}s",
            }
            self.discovery_deadline = None
        return {
            "devices": self.discovery_results,
            "state": self.discovery_state,
            "history": self.discovery_history[-10:],
        }

    def approve_device(self, device: Dict[str, Any]) -> str:
        action = append_device(device)
        self._reload_devices()
        DISCOVER_DEVICES_APPROVED_TOTAL.inc()
        record_audit(self.db, "system", "discover_approve", {**device, "action": action})
        return action

    def remove_device_entry(self, device_id: str) -> bool:
        removed = remove_device(device_id)
        if removed:
            self._reload_devices()
            record_audit(self.db, "system", "device_remove", {"device_id": device_id})
        return removed

    def get_recent_actions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.latest("actions", limit)

    def get_recent_anomalies(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.latest("anomalies", limit)

    def get_status(self) -> Dict[str, Any]:
        uptime = datetime.now(timezone.utc) - self.started_at
        return {
            "mode": self.mode,
            "auto_enabled": self.auto_enabled,
            "site": self.policy.get("site", "unknown"),
            "ingest_count": self.ingest_count,
            "last_ingest_ts": self.last_ingest_ts,
            "tracked_racks": len(self.latest_tiles),
            "uptime_s": int(uptime.total_seconds()),
            "discovery": self.discovery_state,
        }

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        record_audit(self.db, "system", "mode_change", {"mode": mode})

    def set_auto(self, enabled: bool) -> None:
        self.auto_enabled = enabled
        record_audit(self.db, "system", "auto_toggle", {"auto_enabled": enabled})

    def approve_action(self, action_id: int) -> bool:
        action = self.db.get("actions", action_id)
        if not action:
            return False
        cmd_json = json.loads(action["cmd_json"]) if isinstance(action["cmd_json"], str) else action["cmd_json"]
        topic = f"ctrl/{cmd_json['device_id']}/set"
        self.bus.publish(topic, cmd_json)
        self.db.update_action_status(action_id, "sent")
        return True

    def _explain_action(
        self, rack: str, forecast: List[float], anomaly_score: float, triggers: List[str]
    ) -> Dict[str, Any]:
        next_temp = forecast[0] if forecast else None
        trigger_msg = ", ".join(triggers) if triggers else "policy"
        if next_temp is not None:
            temp_text = f"{next_temp:.1f}C"
        else:
            temp_text = "n/a"
        message = f"Triggers: {trigger_msg}. Forecast {temp_text}, risk {anomaly_score:.3f}."
        return {
            "rack": rack,
            "forecast_temp": next_temp,
            "risk_score": anomaly_score,
            "triggers": triggers,
            "message": message,
        }

    def _reload_devices(self) -> None:
        data = get_devices()
        rack_map: Dict[str, str] = {}
        site_map: Dict[str, str] = {}
        for entry in data.get("devices", []):
            device_id = entry.get("id")
            rack = entry.get("rack")
            if device_id and rack:
                rack_map[rack] = device_id
                site_map[device_id] = entry.get("site")
        self.rack_device_map = rack_map
        self.device_site_map = site_map
        try:
            self.devices_mtime = self.devices_path.stat().st_mtime
        except FileNotFoundError:
            self.devices_mtime = 0.0

    def _device_for_rack(self, rack: str) -> str | None:
        if rack in self.dynamic_devices:
            return self.dynamic_devices[rack]
        try:
            current_mtime = self.devices_path.stat().st_mtime
        except FileNotFoundError:
            current_mtime = 0.0
        if current_mtime != self.devices_mtime:
            self._reload_devices()
        return self.rack_device_map.get(rack)
