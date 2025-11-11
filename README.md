# hcai-mini

hcai-mini is a compact edge-ready control plane for smart data centers. It ingests telemetry, forecasts thermal/power states, detects anomalies, and issues safe control actions to CRACs, PDUs, and gateways. Everything runs in two lightweight containers (`hcai-mini` for AI+UI, `hcai-edge` for field I/O) so you can deploy with a single command on an edge server.

## Where hcai-mini works best

- Smart data centers or edge POPs with a management VLAN that reaches CRACs/CRAHs, PDUs, rack sensors, and gateways.
- Sites that already expose MQTT/Modbus/BACnet/SNMP and want an autonomous controller with audit + operator approvals.
- Edge servers (Ubuntu 22.04/24.04, 4+ cores, 16 GB RAM, 50 GB SSD) where you can run Docker containers close to the hardware.

## What the platform does

- **Ingest**: Subscribes to MQTT telemetry streams (`site/<site>/rack/<rack>/telemetry`) plus device status topics.
- **Forecast**: Runs a baseline forecaster (swap in TFT/N-BEATS later) for near-term thermal and power predictions with confidence bands.
- **Detect anomalies**: Uses a rolling-window VAE-style scorer to tag abnormal behavior.
- **Act safely**: MPC-inspired controller proposes setpoints, clamps them with policy limits, publishes to control topics, and records audits.
- **Visualize + approve**: FastAPI UI with live tiles, actions, audit trail, and the network discovery workflow with approval gates.

## Architecture at a glance

```
┌──────────────┐      MQTT topics      ┌──────────────┐
│  Sensors &   │  ───────────────────▶ │  hcai-mini   │
│  Controllers │ ⟵ proposals / cmds ───│  (FastAPI)   │
└──────────────┘      receipts         │- ingest/AI/UI│
           ▲                            └─────┬────────┘
           │ discovery results                │
           │                                   ▼
      ┌────┴──────────┐  device writes   ┌──────────────┐
      │  hcai-edge    │ ───────────────▶ │  CRAC / PDU  │
      │ MQTT bridge + │ ◀─────────────── │  gateways    │
      │ Modbus/BACnet │   receipts       └──────────────┘
      └───────────────┘
```

## Step-by-step deployment (clean Ubuntu 22.04/24.04)

1. **Clone the repo.**
   ```bash
   git clone https://github.com/visezion/hcai-mini.git /opt/hcai-mini
   cd /opt/hcai-mini
   ```
2. **Run the automated setup (installs Docker Engine, Compose, Mosquitto, make, nmap, etc.).**
   ```bash
   sudo ./scripts/setup.sh
   ```
3. **Reload your shell so the docker group membership applies.**
   ```bash
   newgrp docker
   ```
4. **Start the stack.**
   ```bash
   make up
   ```
5. **Verify.**
   ```bash
   docker compose ps
   curl http://localhost:8080/health
   ```
6. **Browse the UI.** Visit `http://<server>:8080/ui` from a workstation on the management network.

The `scripts/setup.sh` installer is idempotent; rerun it whenever you build a new node and it will ensure every dependency (Docker Engine, Compose plugin, Mosquitto broker, system packages) is present and enabled as a service.

## Keeping your deployment up to date

1. Pull the latest code:
   ```bash
   cd /opt/hcai-mini
   git fetch origin
   git checkout main
   git pull origin main
   ```
2. Rebuild and restart the containers so changes take effect:
   ```bash
   make down
   docker compose build hcai-mini hcai-edge
   make up
   ```
3. Validate:
   ```bash
   docker compose ps
   curl http://localhost:8080/health
   ```
4. Review release notes/commits for config changes; if new fields were added to `config/policy.yaml` or `config/devices.yaml`, merge them into your site-specific copies before restarting.

For fully automated updates, wrap the commands above in a cron job or CI workflow and run them during a maintenance window.

## Step-by-step (local development)

1. Launch the API service:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.api:app --reload --port 8080
   ```
2. In another terminal, run the edge bridge against your dev broker:
   ```bash
   pip install -r requirements-edge.txt
   python -m edge.bridge
   ```
3. Open `http://localhost:8080/ui` to see telemetry tiles update in real time.

## Using the platform

1. **Feed telemetry** (simulate if needed):
   ```bash
   mosquitto_pub -h localhost -t site/dc1/rack/R12/telemetry -m '{
     "ts":"2025-11-11T06:00:00Z","site":"dc1","rack":"R12",
     "metrics":{"temp_c":29.3,"hum_pct":42.1,"power_kw":3.8,"airflow_cfm":165}
   }'
   ```
   Tiles update immediately; forecasts/anomaly rows go into SQLite (`data/hcai.sqlite`).

2. **Discover new devices.**
   - Go to **Network Discovery** in the UI, enter a subnet (e.g., `10.0.0.0/24`), click **Discover Devices**.
   - The status chip shows *Scanning...* while hcai-edge probes for Modbus/BACnet/SNMP listeners and times out if the bridge is unreachable.
   - Approve any found devices; hcai-mini appends them to `config/devices.yaml` (never automatic).

3. **Approve or observe control actions.**
   - In *propose* mode, the controller writes to `ctrl/proposals`; operators can inspect payloads and decide when to switch to `auto_safe`.
   - Receipts from hcai-edge are stored under the **Actions** view and in the `receipts` table for audit.

4. **Monitor health.**
   - `/health` reports service status.
   - `make logs` tails both containers.
   - Prometheus-style metrics live at `/metrics` (stubbed in this skeleton; extend as needed).

## Repo layout

```
app/            FastAPI service, models, policy, storage, UI assets
edge/           Field bridge with Modbus writers and discovery helpers
config/         Policy and device inventory
docker/         Dockerfiles for both services
docker-compose.yml  One-command deployment
scripts/setup.sh     Zero-touch dependency installer
```

## Docker deployment cheatsheet

```bash
make up      # build + start hcai-mini and hcai-edge
make logs    # follow service logs
make down    # stop services
```

Set environment variables (MQTT_URL, credentials, MODE, etc.) in `docker-compose.yml` or via an `.env` file to point at your site broker/devices.

## Network discovery guardrails

- Discovery never edits `devices.yaml` without operator approval.
- Limits, rate-of-change, and watchdogs are enforced before any command is sent.
- All control events write to SQLite (`/data/hcai.sqlite`) for audits and receipts.

## Next steps

- Replace placeholder models with trained TFT + ConvVAE exports stored under `/data/models`.
- Extend `edge/discover.py` to include BACnet Who-Is and SNMP sysObjectID fingerprinting.
- Integrate HMAC signing between hcai-mini and hcai-edge for command authenticity.
- Add Grafana/Influx or Prometheus scraping for long-term observability.
- **Contribute changes**:
  ```bash
  git checkout -b feature/<short-name>
  # edit files, run tests
  git status
  git commit -am "feat: short description"
  git push origin feature/<short-name>
  ```
  Then open a pull request in [github.com/visezion/hcai-mini](https://github.com/visezion/hcai-mini) so the new functionality can be reviewed and merged.
