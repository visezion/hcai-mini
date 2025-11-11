# hcai-mini

hcai-mini is a compact edge-ready control plane for smart data centers. It ingests telemetry, forecasts thermal/power states, detects anomalies, and issues safe control actions to CRACs, PDUs, and gateways. The footprint fits into two containers (`hcai-mini` for AI + UI, `hcai-edge` for field I/O) and deploys with `make up`.

## Capabilities

- MQTT ingestion for racks, sensors, and device status topics.
- Forecasting (placeholder baseline) and VAE-style anomaly scoring on rolling windows.
- MPC-inspired controller with policy-based safety clamps and audit trail.
- FastAPI + WebSocket dashboard for telemetry tiles, actions, and device discovery.
- Edge bridge for Modbus/BACnet/SNMP writes plus automatic network discovery workflow.

## Repo layout

```
app/            FastAPI service, models, policy, storage, UI assets
edge/           Field bridge with Modbus writers and discovery helpers
config/         Policy and device inventory
docker/         Dockerfiles for both services
docker-compose.yml  One-command deployment
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.api:app --reload --port 8080
```

In another shell, run the edge bridge (requires network access to devices):

```bash
pip install -r requirements-edge.txt
python -m edge.bridge
```

Then open `http://localhost:8080/ui` to view telemetry tiles and launch discovery scans.

## Docker deployment

```bash
make up      # build + start hcai-mini and hcai-edge
make logs    # follow service logs
make down    # stop services
```

Set environment variables (MQTT_URL, credentials, MODE, etc.) in the `docker-compose.yml` or via an `.env` file to point at your site broker/devices.

## Network discovery workflow

1. Navigate to the **Network Discovery** tab in the UI.
2. Enter the management subnet (default `10.0.0.0/24`) and click **Discover Devices**.
3. hcai-mini publishes a discovery request; hcai-edge scans for Modbus/BACnet/SNMP endpoints and fingerprints capabilities.
4. Results stream back over WebSocket. Approve a device to append it to `config/devices.yaml`.
5. Re-deploy (or trigger hot reload) to start controlling the newly approved device.

Safety guardrails:

- Discovery never edits `devices.yaml` without operator approval.
- Limits, rate-of-change, and watchdogs are enforced before any command is sent.
- All control events write to SQLite (`/data/hcai.sqlite`) for audits and receipts.

## Next steps

- Replace placeholder models with trained TFT + ConvVAE exports stored under `/data/models`.
- Extend `edge/discover.py` to include BACnet Who-Is and SNMP sysObjectID fingerprinting.
- Integrate HMAC signing between hcai-mini and hcai-edge for command authenticity.
- Add Grafana/Influx or Prometheus scraping for long-term observability.
