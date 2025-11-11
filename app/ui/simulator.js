const { useEffect, useMemo, useRef, useState } = React;
const { createRoot } = ReactDOM;

const DEFAULT_BASE =
  (window.localStorage.getItem("hcai-sim-base") || window.location.origin || "").trim();
const SCENARIOS = [
  {
    key: "temp_spike",
    title: "Rapid temperature rise",
    description: "Pushes rack inlet temps upward to stress the forecasts.",
  },
  {
    key: "cooling_failure",
    title: "Cooling failure",
    description: "Simulates a CRAC offline event with sluggish recovery.",
  },
  {
    key: "sensor_dropout",
    title: "Sensor dropout",
    description: "Random racks stop reporting to test anomaly handling.",
  },
  {
    key: "power_spike",
    title: "Power spike",
    description: "Injects short bursts in kW draw to test controller limits.",
  },
];

const COLORS = ["#2563eb", "#14b8a6", "#f97316", "#ec4899", "#a855f7"];

function normalizeBase(value) {
  if (!value) return "";
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

async function fetchJSON(base, path) {
  const url = `${normalizeBase(base)}${path}`;
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `GET ${path} failed (${res.status})`);
  }
  return res.json();
}

async function postJSON(base, path, body) {
  const url = `${normalizeBase(base)}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `POST ${path} failed (${res.status})`);
  }
  return res.json();
}

function useInterval(callback, delay) {
  const savedRef = useRef();
  useEffect(() => {
    savedRef.current = callback;
  }, [callback]);
  useEffect(() => {
    if (delay == null) return;
    const id = setInterval(() => {
      if (savedRef.current) savedRef.current();
    }, delay);
    return () => clearInterval(id);
  }, [delay]);
}

function useMockSim(scenarios = {}) {
  const [room, setRoom] = useState({ temp_c: 26.5, humidity: 44, fan_rpm: 1850 });
  const [racks, setRacks] = useState([
    { rack: "R1", power_kw: 2.9, avg_temp: 33.4 },
    { rack: "R2", power_kw: 3.2, avg_temp: 34.1 },
    { rack: "R3", power_kw: 2.4, avg_temp: 31.7 },
  ]);
  const [series, setSeries] = useState([]);

  useInterval(() => {
    const tempBias = scenarios.temp_spike ? 0.4 : 0;
    const coolingPenalty = scenarios.cooling_failure ? 0.25 : -0.05;
    const humidityDrift = (Math.random() - 0.5) * 1.5;
    const noise = (Math.random() - 0.5) * 0.3;
    const newTemp = room.temp_c + noise + tempBias + coolingPenalty;
    const newFan = Math.max(
      1500,
      Math.min(2600, room.fan_rpm + (scenarios.cooling_failure ? 80 : -40))
    );
    const newHumidity = Math.max(30, Math.min(65, room.humidity + humidityDrift));

    const dropout = scenarios.sensor_dropout && Math.random() < 0.2;
    const updatedRacks = racks.map((rack) => {
      if (dropout) {
        return {
          ...rack,
          power_kw: rack.power_kw,
          avg_temp: rack.avg_temp,
          offline: true,
        };
      }
      const rackDrift = (Math.random() - 0.5) * 0.2;
      const powerShock = scenarios.power_spike ? Math.random() * 0.4 : 0;
      return {
        rack: rack.rack,
        power_kw: Math.max(1.5, Number((rack.power_kw + rackDrift + powerShock).toFixed(2))),
        avg_temp: Number((rack.avg_temp + rackDrift + tempBias * 1.5).toFixed(1)),
        offline: false,
      };
    });

    const point = {
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      room: Number(newTemp.toFixed(2)),
      r1: updatedRacks[0]?.avg_temp ?? null,
      r2: updatedRacks[1]?.avg_temp ?? null,
      r3: updatedRacks[2]?.avg_temp ?? null,
    };

    setRoom({ temp_c: Number(newTemp.toFixed(2)), humidity: Number(newHumidity.toFixed(1)), fan_rpm: newFan });
    setRacks(updatedRacks);
    setSeries((prev) => [...prev.slice(-119), point]);
  }, 2000);

  return { room, racks, series };
}

function StatCard({ label, value, suffix = "", meta, intent = "neutral" }) {
  const className = `stat-card${intent === "warn" ? " warn" : ""}`;
  return (
    <div className={className}>
      <h3>{label}</h3>
      <strong>
        {value}
        {suffix}
      </strong>
      {meta ? <div className="stat-meta">{meta}</div> : null}
    </div>
  );
}

function RackCard({ rack, power, temp, ts, offline }) {
  const hot = typeof temp === "number" && temp >= 37;
  return (
    <div className={`rack-card${hot ? " hot" : ""}`}>
      <div className="panel-header">
        <h3>{rack}</h3>
        {offline ? (
          <span className="badge warn">Offline</span>
        ) : (
          <span className="badge ok">Live</span>
        )}
      </div>
      <div>
        <div className="stat-meta">Updated {ts ? ts : "-"}</div>
        <div className="stat-meta">Power: {power ?? "-"} kW</div>
        <div className="stat-meta">Temp: {temp ?? "-"} C</div>
      </div>
    </div>
  );
}

function DeviceCard({ device }) {
  const latest = device.latest || {};
  return (
    <div className="device-card">
      <header>
        <div>
          <strong>{device.id || device.host}</strong>
          <div className="meta">
            {device.type} | {device.proto?.toUpperCase?.() || device.proto}
          </div>
        </div>
        <span className={`badge ${latest.ts ? "ok" : "warn"}`}>
          {latest.ts ? "Telemetry" : "Pending"}
        </span>
      </header>
      <div className="meta">Host {device.host}:{device.port || "-"}</div>
      {latest.ts ? (
        <div className="meta">
          Temp {latest.temp_c ?? "--"} C | Hum {latest.hum_pct ?? "--"} % | Power {latest.power_kw ?? "--"} kW
        </div>
      ) : (
        <div className="meta">No recent samples</div>
      )}
    </div>
  );
}

function ScenarioCard({ scenario, active, onToggle, disabled }) {
  return (
    <div className="scenario-card">
      <div>
        <h3>{scenario.title}</h3>
        <p>{scenario.description}</p>
      </div>
      <div className="scenario-toggle">
        <span>{active ? "Enabled" : "Disabled"}</span>
        <button
          className={active ? "on" : "off"}
          disabled={disabled}
          onClick={() => onToggle(!active)}
        >
          {active ? "Stop" : "Trigger"}
        </button>
      </div>
    </div>
  );
}

function TrendChart({ dataset }) {
  if (!dataset.points.length) {
    return <div className="trend-placeholder">Waiting for samples...</div>;
  }
  const width = 600;
  const height = 220;
  const padding = 18;
  const values = [];
  dataset.points.forEach((pt) => {
    dataset.keys.forEach((key) => {
      if (typeof pt[key] === "number") values.push(pt[key]);
    });
  });
  const min = Math.min(...values, 15);
  const max = Math.max(...values, 40);
  const scaleX = (idx) =>
    padding + ((width - padding * 2) * idx) / Math.max(dataset.points.length - 1, 1);
  const scaleY = (val) =>
    height - padding - ((height - padding * 2) * (val - min)) / Math.max(max - min, 1);

  const paths = dataset.keys.map((key, idx) => {
    const points = dataset.points
      .map((pt, index) => {
        if (typeof pt[key] !== "number") return null;
        return `${scaleX(index)},${scaleY(pt[key])}`;
      })
      .filter(Boolean);
    const d = points.length ? `M${points.join(" L")}` : "";
    return { key, color: COLORS[idx % COLORS.length], d };
  });

  return (
    <div>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} className="trend-chart">
        <polyline
          fill="none"
          stroke="#e2e8f0"
          strokeWidth="1"
          points={`${padding},${padding} ${padding},${height - padding} ${width - padding},${
            height - padding
          }`}
        />
        {paths.map((path) =>
          path.d ? (
            <path key={path.key} d={path.d} fill="none" stroke={path.color} strokeWidth="2" />
          ) : null
        )}
      </svg>
      <div className="stat-meta">
        {dataset.keys.map((key, idx) => (
          <span key={key} style={{ color: COLORS[idx % COLORS.length], marginRight: "1rem" }}>
            [{key}]
          </span>
        ))}
      </div>
    </div>
  );
}

function SimulatorApp() {
  const [apiBase, setApiBase] = useState(() => normalizeBase(DEFAULT_BASE));
  const [baseField, setBaseField] = useState(() => normalizeBase(DEFAULT_BASE));
  const [tiles, setTiles] = useState({});
  const [summary, setSummary] = useState({ devices: [] });
  const [history, setHistory] = useState([]);
  const [historyRack, setHistoryRack] = useState("");
  const [controllerOnline, setControllerOnline] = useState(false);
  const [error, setError] = useState("");
  const [scenarios, setScenarios] = useState({});
  const [scenarioMsg, setScenarioMsg] = useState("");
  const [scenarioBusy, setScenarioBusy] = useState(false);

  const mock = useMockSim(scenarios);

  const applyBase = () => {
    const normalized = normalizeBase(baseField.trim());
    setApiBase(normalized);
    window.localStorage.setItem("hcai-sim-base", normalized);
  };

  useEffect(() => {
    if (!apiBase) {
      setControllerOnline(false);
      setError("");
      return;
    }
    let cancelled = false;
    const pull = async () => {
      try {
        const [tileData, summaryData] = await Promise.all([
          fetchJSON(apiBase, "/tiles"),
          fetchJSON(apiBase, "/devices/summary"),
        ]);
        if (cancelled) return;
        setTiles(tileData || {});
        setSummary(summaryData || { devices: [] });
        setControllerOnline(true);
        setError("");
      } catch (err) {
        if (cancelled) return;
        setControllerOnline(false);
        setError(err.message || "Controller unreachable");
      }
    };
    pull();
    const interval = setInterval(pull, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [apiBase]);

  useEffect(() => {
    if (!apiBase) {
      setScenarios({});
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchJSON(apiBase, "/simulator/scenarios");
        if (!cancelled) setScenarios(data.scenarios || {});
      } catch {
        if (!cancelled) setScenarioMsg("Simulator API unavailable");
      }
    };
    load();
    const interval = setInterval(load, 8000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [apiBase]);

  useEffect(() => {
    if (!controllerOnline) return;
    const racks = Object.keys(tiles || {});
    if (racks.length && !racks.includes(historyRack)) {
      setHistoryRack(racks[0]);
    }
  }, [controllerOnline, tiles, historyRack]);

  useEffect(() => {
    if (controllerOnline) {
      return;
    }
    if (!historyRack && mock.racks.length) {
      setHistoryRack(mock.racks[0].rack);
    }
  }, [controllerOnline, historyRack, mock.racks.length]);

  useEffect(() => {
    if (!controllerOnline || !apiBase || !historyRack) {
      setHistory([]);
      return;
    }
    let cancelled = false;
    const pull = async () => {
      try {
        const data = await fetchJSON(
          apiBase,
          `/telemetry/history?rack=${encodeURIComponent(historyRack)}&limit=60`
        );
        if (!cancelled) setHistory((data && data.points) || []);
      } catch (err) {
        if (!cancelled) setScenarioMsg(err.message || "History fetch failed");
      }
    };
    pull();
    const interval = setInterval(pull, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [controllerOnline, apiBase, historyRack]);

  const rackTiles = useMemo(() => {
    return Object.entries(tiles || {}).map(([rack, info]) => ({
      rack,
      temp: info?.metrics?.temp_c ?? null,
      power: info?.metrics?.power_kw ?? null,
      ts: info?.ts ? new Date(info.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "",
    }));
  }, [tiles]);

  const controllerRoom = useMemo(() => {
    if (!rackTiles.length) return null;
    const totals = rackTiles.reduce(
      (acc, rack) => {
        if (typeof rack.temp === "number") {
          acc.temp += rack.temp;
          acc.count += 1;
        }
        if (typeof rack.power === "number") acc.power += rack.power;
        return acc;
      },
      { temp: 0, count: 0, power: 0 }
    );
    return {
      temp_c: totals.count ? Number((totals.temp / totals.count).toFixed(1)) : null,
      fan_rpm: 0,
      humidity: null,
      power_kw: Number(totals.power.toFixed(2)),
    };
  }, [rackTiles]);

  const trendDataset = useMemo(() => {
    if (controllerOnline && history.length) {
      return {
        keys: ["rack"],
        points: history
          .slice()
          .reverse()
          .map((row) => ({
            rack: typeof row.temp_c === "number" ? row.temp_c : null,
            label: row.ts,
          })),
      };
    }
    return {
      keys: ["room", "r1", "r2", "r3"],
      points: mock.series,
    };
  }, [controllerOnline, history, mock.series]);

  const rackCards = controllerOnline && rackTiles.length ? rackTiles : mock.racks;
  const roomView = controllerOnline && controllerRoom ? controllerRoom : mock.room;
  const totalPower = controllerOnline && controllerRoom ? controllerRoom.power_kw : rackCards.reduce((acc, rack) => acc + (rack.power || 0), 0);

  const onScenarioToggle = async (key, value) => {
    const nextState = { ...scenarios, [key]: value };
    setScenarios(nextState);
    if (!apiBase) return;
    try {
      setScenarioBusy(true);
      await postJSON(apiBase, "/simulator/scenarios", { [key]: value });
      setScenarioMsg("Scenario updated");
    } catch (err) {
      setScenarioMsg(err.message || "Failed to update scenario");
    } finally {
      setScenarioBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="page-header">
        <div>
          <h1>hcai-mini simulator</h1>
          <p className="page-subtitle">
            Showcase the ingest -> forecast -> control loop, trigger scenarios, and stream synthetic telemetry.
          </p>
        </div>
        <div className="connection">
          <input
            type="text"
            value={baseField}
            placeholder="http://localhost:8080"
            onChange={(e) => setBaseField(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applyBase()}
          />
          <button onClick={applyBase} disabled={baseField === apiBase}>
            Apply
          </button>
          <span className={`badge ${controllerOnline ? "ok" : apiBase ? "warn" : "offline"}`}>
            {controllerOnline ? "Controller linked" : apiBase ? "Retrying..." : "Mock only"}
          </span>
        </div>
      </header>

      {error ? <div className="badge warn">{error}</div> : null}

      <section className="stats">
        <StatCard
          label="Room temp"
          value={roomView.temp_c ?? "--"}
          suffix=" C"
          intent={roomView.temp_c >= 37 ? "warn" : "neutral"}
          meta="Live inlet reading"
        />
        <StatCard
          label="CRAC fan"
          value={roomView.fan_rpm || 1800}
          suffix=" rpm"
          meta="Commanded speed"
        />
        <StatCard
          label="Total power"
          value={typeof totalPower === "number" ? totalPower.toFixed(2) : totalPower}
          suffix=" kW"
          meta="Summed rack draw"
        />
        <StatCard
          label="Humidity"
          value={roomView.humidity ?? mock.room.humidity ?? "--"}
          suffix=" %"
          meta="Room average"
        />
      </section>

      <section className="panels">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Thermal trend</h2>
              <small>{controllerOnline ? `Rack ${historyRack || "-"}` : "Mock stream"}</small>
            </div>
            <select
              className="history-selector"
              value={historyRack}
              onChange={(e) => setHistoryRack(e.target.value)}
              disabled={!controllerOnline}
            >
              {(controllerOnline ? Object.keys(tiles || {}) : rackCards.map((r) => r.rack)).map((rack) => (
                <option key={rack} value={rack}>
                  {rack}
                </option>
              ))}
            </select>
          </div>
          <TrendChart dataset={trendDataset} />
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Scenario controls</h2>
              <small>Drive hcai-sim or stay local</small>
            </div>
            {scenarioMsg ? <small>{scenarioMsg}</small> : null}
          </div>
          <div className="scenario-grid">
            {SCENARIOS.map((sc) => (
              <ScenarioCard
                key={sc.key}
                scenario={sc}
                active={Boolean(scenarios[sc.key])}
                onToggle={(value) => onScenarioToggle(sc.key, value)}
                disabled={scenarioBusy}
              />
            ))}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Rack view</h2>
            <small>{controllerOnline ? "Live racks" : "Mock racks"}</small>
          </div>
        </div>
        <div className="rack-grid">
          {rackCards.map((rack) => (
            <RackCard
              key={rack.rack}
              rack={rack.rack}
              power={rack.power ?? rack.power_kw}
              temp={rack.temp ?? rack.avg_temp}
              ts={rack.ts}
              offline={rack.offline}
            />
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Device inventory</h2>
            <small>Data sourced from /devices/summary</small>
          </div>
        </div>
        {summary.devices?.length ? (
          <div className="device-grid">
            {summary.devices.map((device) => (
              <DeviceCard key={device.id || device.host} device={device} />
            ))}
          </div>
        ) : (
          <div className="trend-placeholder">No approved devices yet. Import from discovery.</div>
        )}
      </section>

      <footer className="footer">
        Simulator feeds the same MQTT topics as production: telemetry -> forecasts -> actions. Use it to
        demo hcai-mini without touching physical hardware.
      </footer>
    </div>
  );
}

const container = document.getElementById("sim-root");
if (container) {
  const root = createRoot(container);
  root.render(<SimulatorApp />);
}
