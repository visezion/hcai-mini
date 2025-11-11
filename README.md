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

## Simulator + GUI-only demo

Need to showcase hcai-mini without touching live hardware? Start the simulator container and open the dedicated React dashboard.

1. Launch the simulator alongside the main stack:
   ```bash
   docker compose up -d hcai-mini hcai-edge hcai-sim
   ```
2. Browse to `http://<server>:8080/ui/simulator.html`.
3. (Optional) Point the page at another controller by pasting its base URL in the top-right field and clicking **Apply**.
4. Use the four scenario tiles (temp spike, cooling failure, sensor dropout, power spike) to drive hcai-sim via `/simulator/scenarios`. The page streams stats, rack tiles, and device inventory via `/tiles`, `/telemetry/history`, and `/devices/summary`.
5. Flip scenarios off to return to steady state, or clear the input to preview the built-in mock data with no backend at all.

The simulator dashboard is built with plain React (ES modules) so you do not need a separate build step; the static assets live under `app/ui/simulator.*`. It is a safe way to demo the ingest → forecast → control loop with live charts, rack tiles, and scenario toggles driven entirely from the browser.

Need real devices for actions? Use the **Import simulator** button on the Setup tab (or call `POST /simulator/devices/import`) to pull the simulated CRACs into `config/devices.yaml`. Approved devices show up in the inventory grid, the controller maps each rack to its simulated device ID, and AI actions you approve will now drive the simulator (which publishes receipts back on `ctrl/<device_id>/receipt`).

### React “Simulator Pro” dashboard

For a richer showcase experience we ship a standalone React + Tailwind dashboard under `simulator-ui/`.

Build and publish it into the FastAPI static directory:

```bash
cd simulator-ui
npm install
npm run build    # outputs to ../app/ui/sim-react
```

Browse to `http://<host>:8080/sim-pro` for the compiled experience (light/dark aware, capacity widgets, diagnostics, etc.). During development run `npm run dev` and point your browser to the indicated Vite dev server; the API base URL is still configured inside the page via the “Controller URL” input (stored in `localStorage` as `dc_api_base`).

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

1. **Open the dashboard + stream telemetry.** Browse to `http://<host>:8080/ui`, pick Light/Dark from the toggle (light is default), then publish sample telemetry if needed:
   ```bash
   mosquitto_pub -h localhost -t site/dc1/rack/R12/telemetry -m '{
     "ts":"2025-11-11T06:00:00Z","site":"dc1","rack":"R12",
     "metrics":{"temp_c":29.3,"hum_pct":42.1,"power_kw":3.8,"airflow_cfm":165}
   }'
   ```
   Tiles and the ingest summary card update instantly; data is persisted in SQLite (`data/hcai.sqlite`).

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
   - Prometheus metrics live at `/metrics` (discover counters, duration histogram, etc.).

5. **Review device inventory.**
   - The **Device inventory** panel in the UI lists every entry from `config/devices.yaml` (including items approved via auto-discovery) so you always know what the AI can control.
   - After approving a discovered device, the list refreshes automatically—no need to restart the stack.
   - The new **Setup** tab lets operators import discovered devices, validate connectivity, and inspect templates before approving.
   - You can also remove a device via the **Remove** button; hcai-edge drops the poller immediately so you can re-approve it for testing.

6. **Operate the AI controller.**
   - The **Monitor** tab shows live rack telemetry plus historical trends and forecast context.
   - The **Devices** tab (new) lists every device with its latest measured values, even if it doesn’t map neatly to a rack, so you can monitor gateways or sensors directly.
   - The **Actions** tab exposes every MPC proposal with inline explanations; switch the global toggle to require manual approval or let hcai-mini run autonomously.

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

Discovery scans can take up to several minutes on large subnets. Adjust `DISCOVERY_TIMEOUT_S` (default 180 seconds) in the hcai-mini container to control how long the UI waits before flagging a timeout.

## Network discovery guardrails

- Discovery never edits `devices.yaml` without operator approval.
- Limits, rate-of-change, and watchdogs are enforced before any command is sent.
- All control events write to SQLite (`/data/hcai.sqlite`) for audits and receipts.

## Auto network discovery (“auto-can”)

hcai-mini now includes an end-to-end automatic onboarding workflow:

1. **Automatic subnet scanning** – hcai-edge probes every host in `DISCOVERY_SUBNET`, rate-limited by `DISCOVERY_IPS_PER_MIN`, and reports raw hits to `discover/raw`.
2. **Protocol fingerprinting** – Modbus device IDs, SNMP `sysObjectID`, BACnet Who-Is, and MQTT handshake detection classify each IP.
3. **Template matching** – fingerprints are matched against `/config/templates/*.yaml`; the resulting template provides the correct map/write policy.
4. **Structured MQTT results** – summarized devices are published to `discover/results` for FastAPI + UI consumption.
5. **Operator approvals** – `/discover/approve` persists a device, emits `discover/approved`, updates audits, and updates the Device Inventory instantly.
6. **Dynamic runtime registration** – hcai-edge reloads devices on the fly (no restart) and runs a read-only self-check before allowing writes.
7. **Continuous background scans** – scheduler triggers discovery every `DISCOVERY_INTERVAL_HOURS` (default 6h) so new hardware is never missed.
8. **Safety controls** – read-only probes, rate limiting, `DISCOVERY_ENABLED` master toggle, and `/data/discovery.log` keep scans safe and traceable.
9. **UI integration** – the Network Discovery panel shows status chips, subnet picker, history log, candidate list, and Approve buttons with instant feedback.
10. **Audit + metrics** – every scan/approval is stored in the `audits` table; Prometheus counters (`discover_*`) expose performance in `/metrics`.
11. **Template registry** – drop new YAML templates under `config/templates/` to teach hcai-mini about additional vendors/models.
12. **Device inventory & telemetry** – approved devices appear immediately in the dashboard, `/devices` API, and the edge bridge’s runtime registry.
13. **Automatic polling** – hcai-edge polls Modbus registers or SNMP OIDs defined in each template (default every 10 seconds) and publishes the readings to `site/<site>/rack/<rack>/telemetry`, keeping the Monitor page and AI models up to date without extra agents.

Key environment toggles: `DISCOVERY_SUBNET`, `DISCOVERY_IPS_PER_MIN`, `DISCOVERY_SNMP_COMMUNITY`, `DISCOVERY_TEMPLATE_DIR`, `DISCOVERY_INTERVAL_HOURS`, and `DISCOVERY_ENABLED`.

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
