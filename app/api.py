import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
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

if settings.ui_enable:
    app.mount("/ui", StaticFiles(directory="app/ui", html=True), name="ui")


@app.on_event("startup")
async def startup() -> None:
    bus.start(engine.handle_message)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/tiles")
def tiles() -> Dict[str, Any]:
    return engine.latest_tiles


@app.post("/discover/start")
def discover_start(payload: Dict[str, Any] = Body(default=None)) -> Dict[str, Any]:
    subnet = payload.get("subnet") if payload else settings.discovery_subnet
    engine.start_discovery(subnet)
    return {"status": "started", "subnet": subnet}


@app.get("/discover")
def list_discoveries() -> Dict[str, Any]:
    return {"devices": engine.list_discoveries()}


@app.post("/discover/approve")
def approve_device(device: Dict[str, Any]) -> Dict[str, Any]:
    engine.approve_device(device)
    return {"status": "approved", "device": device}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = {"tiles": engine.latest_tiles, "discover": engine.list_discoveries()}
            await websocket.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
