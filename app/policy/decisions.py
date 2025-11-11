import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from ..config import append_device, get_policy, get_settings
from ..features import FeatureStore
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
        self.ingest_count = 0
        self.last_ingest_ts: str | None = None
        self.started_at = datetime.now(timezone.utc)

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
        elif topic == "ctrl/discover/results":
            data = json.loads(payload)
            self.discovery_results = data.get("devices", [])
            count = len(self.discovery_results)
            self.discovery_state = {
                "status": "done",
                "message": f"Found {count} device(s)" if count else "No devices discovered",
                "started_at": self.discovery_state.get("started_at"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
            self.discovery_deadline = None
        else:
            # ignore
            pass

    def _handle_telemetry(self, data: Dict[str, Any]) -> None:
        rack = data.get("rack", "unknown")
        metrics = data.get("metrics", {})
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
        self._maybe_act(rack)
        self.ingest_count += 1
        self.last_ingest_ts = ts

    def _maybe_act(self, rack: str) -> None:
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
        if not alarm and (preds[5] if len(preds) > 5 else preds[0]) < self.policy["limits"]["temp_c"]["max"]:
            return
        current = {"supply_temp_c": 18.0, "fan_rpm": 1200}
        proposal = self.controller.propose(preds, current)
        safe = self.safety.enforce(current, proposal)
        action_payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "device_id": self.policy.get("site", "device"),
            "cmd": "setpoints",
            "set": {k: safe[k] for k in ("supply_temp_c", "fan_rpm")},
            "mode": self.mode,
            "reason": "forecast_risk_high" if alarm else "anomaly",
            "ticket": "HCAI-BOOTSTRAP",
            "constraints": self.policy.get("limits", {}),
            "safety_summary": safe["safety_summary"],
        }
        self.db.record_action(
            {
                "ts": action_payload["ts"],
                "device_id": action_payload["device_id"],
                "cmd_json": action_payload,
                "mode": self.mode,
                "status": "queued",
                "reason": action_payload["reason"],
                "model_version": "bootstrap",
                "safety_summary": safe["safety_summary"],
            }
        )
        topic = "ctrl/proposals" if self.mode == "propose" else f"ctrl/{action_payload['device_id']}/set"
        self.bus.publish(topic, action_payload)

    def start_discovery(self, subnet: str) -> None:
        now = datetime.now(timezone.utc)
        payload = {"subnet": subnet, "ts": now.isoformat()}
        self.bus.publish("ctrl/discover/start", payload)
        record_audit(self.db, "system", "discover_start", payload)
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
        return {"devices": self.discovery_results, "state": self.discovery_state}

    def approve_device(self, device: Dict[str, Any]) -> None:
        append_device(device)
        record_audit(self.db, "system", "discover_approve", device)

    def get_recent_actions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.latest("actions", limit)

    def get_recent_anomalies(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.latest("anomalies", limit)

    def get_status(self) -> Dict[str, Any]:
        uptime = datetime.now(timezone.utc) - self.started_at
        return {
            "mode": self.mode,
            "site": self.policy.get("site", "unknown"),
            "ingest_count": self.ingest_count,
            "last_ingest_ts": self.last_ingest_ts,
            "tracked_racks": len(self.latest_tiles),
            "uptime_s": int(uptime.total_seconds()),
            "discovery": self.discovery_state,
        }
