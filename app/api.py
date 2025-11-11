import asyncio
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests
import yaml
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import get_devices, get_settings
from .features import FeatureStore
from .mqtt_bus import Bus
from .models.anomaly_vae import VAEAnomaly
from .models.forecaster import Forecaster
from .models.mpc import MPCController
from .models.explainer import Explainer
from .policy.decisions import DecisionEngine
from .policy.safety import Safety
from .storage.db import DB

app = FastAPI(title="hcai-mini")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
db = DB(settings.db_path)
feature_store = FeatureStore(window=120)
forecaster = Forecaster(horizon=30)
anomaly = VAEAnomaly(threshold=0.97)
limits = {
    "temp_c": {"min": 16, "max": 27, "max_delta_per_min": 1.0},
    "fan_rpm": {"min": 800, "max": 2200, "max_delta_per_min": 200},
}
weights = {"thermal_risk": 1.0, "energy": 0.35, "wear": 0.15}
controller = MPCController(limits, weights)
safety = Safety(limits)
explainer = Explainer()
bus = Bus()
engine = DecisionEngine(db, bus, feature_store, forecaster, anomaly, controller, safety)
scheduler_task = None

if settings.ui_enable:
    app.mount("/ui", StaticFiles(directory="app/ui", html=True), name="ui")

SIMULATOR_URL = os.environ.get("SIMULATOR_URL", "http://localhost:9100")

@app.on_event("startup")
async def startup() -> None:
    bus.start(engine.handle_message)
    async def discovery_scheduler():
        interval = max(1, settings.discovery_interval_hours) * 3600
        while True:
            await asyncio.sleep(interval)
            engine.start_discovery(settings.discovery_subnet, actor="scheduler")
    global scheduler_task
    scheduler_task = asyncio.create_task(discovery_scheduler())


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/tiles")
def tiles() -> Dict[str, Any]:
    return engine.latest_tiles


@app.post("/discover/start")
def discover_start(payload: Dict[str, Any] = Body(default=None)) -> Dict[str, Any]:
    subnet = payload.get("subnet") if payload else settings.discovery_subnet
    actor = payload.get("actor", "operator") if payload else "operator"
    engine.start_discovery(subnet, actor)
    return {"status": "started", "subnet": subnet, "actor": actor}


@app.get("/discover")
def list_discoveries() -> Dict[str, Any]:
    return engine.list_discoveries()


@app.post("/discover/approve")
def approve_device(device: Dict[str, Any]) -> Dict[str, Any]:
    result = engine.approve_device(device)
    payload = {"device": device, "action": result, "ts": datetime.now(timezone.utc).isoformat()}
    bus.publish("discover/approved", payload)
    return {"status": "approved", "device": device, "action": result}


@app.get("/devices")
def devices() -> Dict[str, Any]:
    return get_devices()


@app.get("/devices/summary")
def devices_summary() -> Dict[str, Any]:
    data = get_devices()
    devices = data.get("devices", [])
    enriched = []
    for device in devices:
        rack = device.get("rack")
        latest = db.latest_point(rack) if rack else None
        enriched.append({**device, "latest": latest})
    return {"devices": enriched}

@app.delete("/devices/{device_id}")
def delete_device(device_id: str) -> Dict[str, Any]:
    removed = engine.remove_device_entry(device_id)
    if not removed:
        raise HTTPException(status_code=404, detail="device not found")
    payload = {"device_id": device_id, "ts": datetime.now(timezone.utc).isoformat()}
    bus.publish("discover/removed", payload)
    return {"status": "removed", "device_id": device_id}


def load_templates() -> List[Dict[str, Any]]:
    path = Path(settings.template_dir)
    templates: List[Dict[str, Any]] = []
    if not path.exists():
        return templates
    for file in path.glob("*.yaml"):
        with file.open("r", encoding="utf-8") as handle:
            item = yaml.safe_load(handle) or {}
            if item:
                item["file"] = file.name
                templates.append(item)
    return templates


@app.get("/templates")
def list_templates() -> Dict[str, Any]:
    return {"templates": load_templates()}


@app.post("/devices/validate")
def validate_device(device: Dict[str, Any]) -> Dict[str, Any]:
    host = device.get("host")
    port = int(device.get("port", 0))
    if not host or not port:
        raise HTTPException(status_code=400, detail="host and port required")
    try:
        with socket.create_connection((host, port), timeout=1):
            return {"ok": True, "message": f"Connection to {host}:{port} succeeded"}
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Connection failed: {exc}") from exc


@app.get("/actions")
def actions(limit: int = 20) -> Dict[str, Any]:
    rows = engine.get_recent_actions(limit)
    for row in rows:
        cmd = row.get("cmd_json")
        if isinstance(cmd, str):
            try:
                row["cmd"] = json.loads(cmd)
            except json.JSONDecodeError:
                row["cmd"] = {}
        else:
            row["cmd"] = cmd or {}
    return {"actions": rows}


@app.get("/anomalies")
def anomalies(limit: int = 20) -> Dict[str, Any]:
    return {"anomalies": engine.get_recent_anomalies(limit)}


@app.get("/status")
def status() -> Dict[str, Any]:
    return engine.get_status()


@app.get("/mode")
def get_mode() -> Dict[str, Any]:
    state = engine.get_status()
    return {"mode": state["mode"], "auto_enabled": state["auto_enabled"]}


@app.post("/mode")
def set_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = payload.get("mode")
    auto = payload.get("auto_enabled")
    if mode:
        engine.set_mode(mode)
    if auto is not None:
        engine.set_auto(bool(auto))
    return {"mode": engine.mode, "auto_enabled": engine.auto_enabled}


@app.post("/actions/approve")
def approve_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    action_id = payload.get("id")
    if not action_id:
        raise HTTPException(status_code=400, detail="id required")
    ok = engine.approve_action(action_id)
    if not ok:
        raise HTTPException(status_code=404, detail="action not found")
    return {"status": "sent", "id": action_id}


@app.get("/telemetry/history")
def telemetry_history(rack: str, limit: int = 120) -> Dict[str, Any]:
    return {"rack": rack, "points": db.telemetry_history(rack, limit)}


def _simulator_request(method: str, path: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{SIMULATOR_URL}{path}"
    try:
        if method == "get":
            resp = requests.get(url, timeout=2)
        else:
            resp = requests.post(url, json=data, timeout=2)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Simulator unavailable: {exc}") from exc


@app.get("/simulator/scenarios")
def simulator_scenarios() -> Dict[str, Any]:
    return _simulator_request("get", "/scenarios")


@app.post("/simulator/scenarios")
def simulator_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _simulator_request("post", "/scenarios", payload)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = {
                "tiles": engine.latest_tiles,
                "discover": engine.list_discoveries(),
                "actions": engine.get_recent_actions(5),
                "anomalies": engine.get_recent_anomalies(5),
                "status": engine.get_status(),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
