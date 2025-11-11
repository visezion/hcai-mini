import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart,
  CheckCircle2,
  Fan,
  Gauge,
  Info,
  Power,
  Server,
  Settings,
  ShieldCheck,
  Thermometer,
  XCircle,
  Zap,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

const API_KEY = "dc_api_base";

const getApiBase = () => (window.localStorage.getItem(API_KEY) || "").trim();

const isHttpUrl = (value: string) => {
  try {
    const candidate = new URL(value);
    return candidate.protocol === "http:" || candidate.protocol === "https:";
  } catch {
    return false;
  }
};

const joinUrl = (base: string, path: string) => {
  if (!base) return path;
  const trimmed = base.endsWith("/") ? base.slice(0, -1) : base;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return trimmed + normalized;
};

function withTimeout(ms: number, message = "Request timeout") {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(message), ms);
  return {
    exec: async (input: RequestInfo, init: RequestInit = {}) => {
      try {
        return await fetch(input, { ...init, signal: controller.signal });
      } finally {
        clearTimeout(timer);
      }
    },
  };
}

function useInterval(callback: () => void, delay: number | null) {
  const savedCallback = useRef<(() => void) | null>(null);
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (delay == null) return;
    const id = setInterval(() => savedCallback.current?.(), delay);
    return () => clearInterval(id);
  }, [delay]);
}

type Rack = {
  rack: string;
  power_kw: number;
  avg_temp: number;
};

type RoomState = {
  temp_c: number;
  humidity: number;
  fan_rpm?: number;
};

type GensetState = {
  available_kw: number;
  fuel_pct: number;
  running: boolean;
};

type UpsState = {
  capacity_kw: number;
  load_kw: number;
  soc_pct: number;
  autonomy_min: number;
  healthy: boolean;
};

type GridState = {
  healthy: boolean;
  pue: number;
  cooling_kw: number;
};

type RedundancyState = {
  power: string;
  cooling: string;
  network: string;
};

type TrendPoint = {
  time: string;
  room: number;
  r1?: number;
  r2?: number;
  r3?: number;
};

function useMockSim(enabled = true) {
  const [room, setRoom] = useState<RoomState>({ temp_c: 26.3, humidity: 44, fan_rpm: 1800 });
  const [racks, setRacks] = useState<Rack[]>([
    { rack: "R1", power_kw: 2.8, avg_temp: 34.2 },
    { rack: "R2", power_kw: 3.1, avg_temp: 35.4 },
    { rack: "R3", power_kw: 2.2, avg_temp: 33.1 },
  ]);
  const [series, setSeries] = useState<TrendPoint[]>([]);
  const [genset, setGenset] = useState<GensetState>({ available_kw: 40, fuel_pct: 72, running: false });
  const [ups, setUps] = useState<UpsState>({
    capacity_kw: 30,
    load_kw: 8.5,
    soc_pct: 91,
    autonomy_min: 18,
    healthy: true,
  });
  const [grid, setGrid] = useState<GridState>({ healthy: true, pue: 1.52, cooling_kw: 6.0 });
  const [redundancy, setRedundancy] = useState<RedundancyState>({ power: "N+1", cooling: "N+1", network: "2N" });

  useInterval(() => {
    if (!enabled) return;
    const tempDrift = (Math.random() - 0.5) * 0.2 + (room.fan_rpm && room.fan_rpm > 2000 ? -0.05 : 0.05);
    const humidityDrift = Math.max(35, Math.min(60, room.humidity + (Math.random() - 0.5) * 0.8));
    const nextRoom = {
      ...room,
      temp_c: Number((room.temp_c + tempDrift).toFixed(2)),
      humidity: Number(humidityDrift.toFixed(1)),
    };

    const nextRacks = racks.map((rack) => {
      const drift = (Math.random() - 0.5) * 0.06;
      const nextPower = Math.max(1.4, rack.power_kw + drift);
      const temp = rack.avg_temp + (Math.random() - 0.5) * 0.2 + (nextRoom.temp_c - 26) * 0.05;
      return {
        ...rack,
        power_kw: Number(nextPower.toFixed(2)),
        avg_temp: Number(temp.toFixed(1)),
      };
    });

    const itKw = nextRacks.reduce((total, rack) => total + (rack.power_kw || 0), 0);
    const coolingKw = Math.max(4, 5.5 + (nextRoom.temp_c - 25) * 0.4 + (itKw - 6) * 0.25);
    const totalKw = itKw + coolingKw;
    const pue = Number((totalKw / Math.max(0.1, itKw)).toFixed(2));
    const upsLoad = Math.min(ups.capacity_kw, Number((itKw * 0.85).toFixed(2)));
    const nextSoc = Math.max(10, Math.min(100, ups.soc_pct + (grid.healthy ? 0.05 : -0.2)));

    setRoom(nextRoom);
    setRacks(nextRacks);
    setGrid({ healthy: grid.healthy, pue, cooling_kw: Number(coolingKw.toFixed(2)) });
    setUps((current) => ({
      ...current,
      load_kw: upsLoad,
      soc_pct: nextSoc,
      autonomy_min: Math.max(6, Math.round(nextSoc / 5)),
    }));

    const now = new Date();
    setSeries((prev: TrendPoint[]) => [
      ...prev.slice(-119),
      {
        time: now.toLocaleTimeString(),
        room: nextRoom.temp_c,
        r1: nextRacks[0]?.avg_temp,
        r2: nextRacks[1]?.avg_temp,
        r3: nextRacks[2]?.avg_temp,
      },
    ]);
  }, 2000);

  return {
    room,
    setRoom,
    racks,
    setRacks,
    series,
    genset,
    setGenset,
    ups,
    setUps,
    grid,
    setGrid,
    redundancy,
    setRedundancy,
  };
}

async function httpGet(path: string) {
  const base = getApiBase();
  if (!base || !isHttpUrl(base)) {
    throw new Error("API disabled or invalid URL");
  }
  const fetcher = withTimeout(5000);
  const response = await fetcher.exec(joinUrl(base, path), { method: "GET" });
  if (!response.ok) {
    throw new Error(`GET ${path} ${response.status}`);
  }
  return response.json();
}

async function httpPost(path: string, body?: Record<string, unknown>) {
  const base = getApiBase();
  if (!base || !isHttpUrl(base)) {
    throw new Error("API disabled or invalid URL");
  }
  const fetcher = withTimeout(6000);
  const response = await fetcher.exec(joinUrl(base, path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) {
    throw new Error(`POST ${path} ${response.status}`);
  }
  return response.json();
}

function useControllerData(enabled: boolean) {
  const [devices, setDevices] = useState<any[]>([]);
  const [summary, setSummary] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [failCount, setFailCount] = useState(0);

  const pull = useCallback(async () => {
    if (!enabled) return;
    if (!navigator.onLine) {
      setError("Offline. Check network");
      return;
    }
    try {
      const inventory = await httpGet("/inventory/devices");
      const entries = inventory.results || inventory.devices || [];
      setDevices(entries);
      const sum = await httpGet("/ui/summary");
      setSummary(sum);
      setError("");
      setFailCount(0);
    } catch (err) {
      setFailCount((value) => value + 1);
      const message = err instanceof Error ? err.message : String(err);
      setError(message.includes("Failed to fetch") ? "Failed to fetch. Check API/CORS/server." : message);
    }
  }, [enabled]);

  useEffect(() => {
    pull();
  }, [pull]);

  useInterval(() => {
    void pull();
  }, enabled ? 5000 : null);

  return { devices, summary, error, failCount, refresh: pull };
}

const fmt = (value: number, digits = 2) => Number(value).toFixed(digits);
const capColor = (pct: number) => (pct >= 90 ? "text-red-600" : pct >= 75 ? "text-amber-600" : "text-emerald-600");

const Stat = ({
  icon: Icon,
  label,
  value,
  suffix = "",
  intent,
}: {
  icon: typeof Thermometer;
  label: string;
  value: string | number;
  suffix?: string;
  intent?: "warn" | "ok";
}) => (
  <Card className={intent === "warn" ? "border-amber-400" : intent === "ok" ? "border-emerald-400" : ""}>
    <CardContent className="flex items-center gap-3 p-4">
      <div className="rounded-xl bg-muted p-3">
        <Icon className="h-6 w-6" />
      </div>
      <div>
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className="text-2xl font-semibold tracking-tight">
          {value}
          {suffix}
        </div>
      </div>
    </CardContent>
  </Card>
);

const TrendPanel = ({ data }: { data: any[] }) => (
  <Card>
    <CardContent className="p-4">
      <div className="mb-2 text-sm font-medium">Room and rack temperatures</div>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" hide />
            <YAxis domain={[20, 45]} />
            <RTooltip />
            <Legend />
            <Line type="monotone" dataKey="room" dot={false} strokeWidth={2} name="Room" />
            <Line type="monotone" dataKey="r1" dot={false} strokeWidth={2} name="R1" />
            <Line type="monotone" dataKey="r2" dot={false} strokeWidth={2} name="R2" />
            <Line type="monotone" dataKey="r3" dot={false} strokeWidth={2} name="R3" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </CardContent>
  </Card>
);

const CapacityPanel = ({
  racks,
  grid,
  ups,
  genset,
  redundancy,
}: {
  racks: Rack[];
  grid: any;
  ups: any;
  genset: any;
  redundancy: any;
}) => {
  const itKw = racks.reduce((total, rack) => total + (rack.power_kw || 0), 0);
  const totalKw = itKw + (grid.cooling_kw || 0);
  const upsHeadroom = Math.max(0, ups.capacity_kw - ups.load_kw);
  const gensetHeadroom = Math.max(0, genset.available_kw - totalKw);
  const upsPct = (ups.load_kw / Math.max(1, ups.capacity_kw)) * 100;

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center gap-2 font-medium">
          <BarChart className="h-5 w-5" />
          Capacity overview
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="text-muted-foreground">IT load</div>
            <div className="text-right font-medium">{fmt(itKw)} kW</div>
            <div className="text-muted-foreground">Cooling</div>
            <div className="text-right font-medium">{fmt(grid.cooling_kw)} kW</div>
            <div className="text-muted-foreground">PUE</div>
            <div className="text-right font-medium">{fmt(grid.pue)}</div>
            <div className="text-muted-foreground">UPS load</div>
            <div className="text-right font-medium">{fmt(ups.load_kw)} kW</div>
            <div className="text-muted-foreground">UPS headroom</div>
            <div className={`text-right font-medium ${capColor(upsPct)}`}>{fmt(upsHeadroom)} kW</div>
            <div className="text-muted-foreground">Gen headroom</div>
            <div className={`text-right font-medium ${gensetHeadroom < 5 ? "text-amber-600" : "text-emerald-600"}`}>
              {fmt(gensetHeadroom)} kW
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="text-muted-foreground">Power redundancy</div>
            <div className="text-right font-medium">{redundancy.power}</div>
            <div className="text-muted-foreground">Cooling redundancy</div>
            <div className="text-right font-medium">{redundancy.cooling}</div>
            <div className="text-muted-foreground">Network redundancy</div>
            <div className="text-right font-medium">{redundancy.network}</div>
            <div className="text-muted-foreground">UPS SoC</div>
            <div className="text-right font-medium">{fmt(ups.soc_pct, 0)}%</div>
            <div className="text-muted-foreground">UPS autonomy</div>
            <div className="text-right font-medium">{ups.autonomy_min} min</div>
            <div className="text-muted-foreground">Gen fuel</div>
            <div className="text-right font-medium">{genset.fuel_pct}%</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

const OptimizationPanel = ({
  racks,
  room,
  grid,
  ups,
  genset,
  redundancy,
  onApply,
}: {
  racks: Rack[];
  room: RoomState;
  grid: any;
  ups: any;
  genset: any;
  redundancy: any;
  onApply?: (action: { type: string; [key: string]: unknown }) => void;
}) => {
  const hotRacks = racks.filter((rack) => rack.avg_temp > 37).map((rack) => rack.rack);
  const suggestions: Array<{ id: string; text: string; action: { type: string; [key: string]: unknown } | null }> = [];
  if (room.temp_c > 27) {
    suggestions.push({
      id: "cooling_raise",
      text: "Room above 27 C. Increase CRAC fan 200 rpm.",
      action: { type: "fan", rpm: (room.fan_rpm || 1800) + 200 },
    });
  }
  if (grid.pue > 1.7) {
    suggestions.push({
      id: "pue_opt",
      text: "High PUE. Lower room target by 0.5 C and improve airflow.",
      action: { type: "temp", target: Math.max(20, (room.temp_c || 26) - 0.5) },
    });
  }
  if (hotRacks.length) {
    suggestions.push({
      id: "hot_aisle",
      text: `Hot racks: ${hotRacks.join(", ")}. Recommend airflow balancing.`,
      action: null,
    });
  }
  if (ups.autonomy_min < 10 && !genset.running) {
    suggestions.push({
      id: "start_gen",
      text: "Low UPS autonomy. Start generator.",
      action: { type: "gen", cmd: "start" },
    });
  }
  if (redundancy.cooling === "N") {
    suggestions.push({
      id: "cooling_redundancy",
      text: "Cooling redundancy degraded to N. Restore standby CRAH.",
      action: null,
    });
  }
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center gap-2 font-medium">
          <ShieldCheck className="h-5 w-5" />
          Optimization
        </div>
        {!suggestions.length && <div className="text-sm text-muted-foreground">No actions needed.</div>}
        <div className="space-y-2">
          {suggestions.map((suggestion) => (
            <div key={suggestion.id} className="flex items-center justify-between rounded-xl bg-muted/50 p-2 text-sm">
              <span>{suggestion.text}</span>
              {suggestion.action && (
                <Button size="sm" onClick={() => onApply?.(suggestion.action!)}>
                  Apply
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

const DiagnosticsPanel = ({
  apiEnabled,
  error,
  onClearApi,
  onUseMock,
  onTest,
  tests,
}: {
  apiEnabled: boolean;
  error: string;
  onClearApi: () => void;
  onUseMock: () => void;
  onTest: () => void;
  tests: Array<{ name: string; ok: boolean; msg: string }>;
}) => {
  const apiBase = getApiBase();
  const valid = isHttpUrl(apiBase);
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-medium">
            <Info className="h-5 w-5" />
            Diagnostics
          </div>
          <Badge variant={apiEnabled ? "default" : "secondary"}>{apiEnabled ? "API mode" : "Mock mode"}</Badge>
        </div>
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">API_BASE</span>
            <span className="font-mono break-all">{apiBase || "(empty)"}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">URL valid</span>
            {valid ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-red-600" />}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Online</span>
            {navigator.onLine ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            ) : (
              <XCircle className="h-4 w-4 text-red-600" />
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Last error</span>
            <span className="truncate" title={error || "None"}>
              {error || "None"}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={onUseMock}>
            Force mock
          </Button>
          <Button size="sm" variant="secondary" onClick={onClearApi}>
            Clear API_BASE
          </Button>
          <Button size="sm" onClick={onTest}>
            Run connectivity tests
          </Button>
        </div>
        {!!tests.length && (
          <div className="mt-2 space-y-1 text-xs">
            {tests.map((test) => (
              <div key={test.name} className="flex items-center gap-2">
                {test.ok ? <CheckCircle2 className="h-3 w-3 text-emerald-600" /> : <XCircle className="h-3 w-3 text-red-600" />}
                <span>
                  {test.name}: {test.msg}
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          <span>Tip: backend must enable CORS for this origin. Try GET /health in a browser tab.</span>
        </div>
      </CardContent>
    </Card>
  );
};

export default function App() {
  const apiBase = getApiBase();
  const [forceMock, setForceMock] = useState(false);
  const apiEnabled = Boolean(apiBase) && isHttpUrl(apiBase) && !forceMock;
  const role = (window.localStorage.getItem("dc_role") || "operator").toLowerCase();
  const limited = role === "limited";

  const mock = useMockSim(!apiEnabled);
  const controller = useControllerData(apiEnabled);

  const roomView = apiEnabled && controller.summary?.room ? controller.summary.room : mock.room;
  const rackView = apiEnabled && controller.summary?.racks?.length ? controller.summary.racks : mock.racks;
  const gensetView = apiEnabled && controller.summary?.genset ? controller.summary.genset : mock.genset;
  const upsView = apiEnabled && controller.summary?.ups ? controller.summary.ups : mock.ups;
  const gridView = apiEnabled && controller.summary?.grid ? controller.summary.grid : mock.grid;
  const redundancyView = apiEnabled && controller.summary?.redundancy ? controller.summary.redundancy : mock.redundancy;
  const seriesView = apiEnabled && controller.summary?.series?.length ? controller.summary.series : mock.series;

  const healthIntent = roomView.temp_c > 37 ? "warn" : roomView.temp_c < 18 ? "warn" : "ok";
  const itKw = rackView.reduce((total: number, rack: Rack) => total + (rack.power_kw || 0), 0);
  const showApiBanner = apiEnabled && controller.failCount >= 2;

  const setFan = async (rpm: number) => {
    try {
      if (apiEnabled) await httpPost(`/control/crac/fan?rpm=${rpm}`);
    } catch {
      /* no-op */
    }
    mock.setRoom((state) => ({ ...state, fan_rpm: rpm }));
  };

  const setTarget = async (target: number) => {
    try {
      if (apiEnabled) await httpPost(`/control/room/temp?target_c=${target}`);
    } catch {
      /* no-op */
    }
    mock.setRoom((state) => ({ ...state, temp_c: Math.min(state.temp_c, target) }));
  };

  const startGen = async () => {
    if (limited) return;
    try {
      if (apiEnabled) await httpPost("/control/gen/start");
    } catch {
      /* no-op */
    }
    mock.setGenset((state) => ({ ...state, running: true }));
  };

  const stopGen = async () => {
    if (limited) return;
    try {
      if (apiEnabled) await httpPost("/control/gen/stop");
    } catch {
      /* no-op */
    }
    mock.setGenset((state) => ({ ...state, running: false }));
  };

  const applyAction = async (action: { type: string; [key: string]: unknown }) => {
    if (action.type === "fan" && typeof action.rpm === "number") {
      return setFan(action.rpm);
    }
    if (action.type === "temp" && typeof action.target === "number") {
      return setTarget(action.target);
    }
    if (action.type === "gen" && action.cmd === "start") {
      return startGen();
    }
  };

  const [tests, setTests] = useState<Array<{ name: string; ok: boolean; msg: string }>>([]);

  const runTests = async () => {
    const steps: Array<{ name: string; ok: boolean; msg: string }> = [];
    const base = getApiBase();
    const valid = base && isHttpUrl(base);
    steps.push({ name: "API_BASE set", ok: Boolean(base), msg: base ? "ok" : "empty" });
    steps.push({ name: "URL format", ok: Boolean(valid), msg: valid ? "ok" : "invalid" });
    const endpoints = ["/health", "/inventory/devices", "/ui/summary"];
    for (const endpoint of endpoints) {
      if (valid) {
        try {
          const response = await fetch(joinUrl(base, endpoint));
          steps.push({ name: `GET ${endpoint}`, ok: response.ok, msg: response.ok ? "200" : String(response.status) });
        } catch {
          steps.push({ name: `GET ${endpoint}`, ok: false, msg: "failed" });
        }
      }
    }
    setTests(steps);
  };

  const rackHealth = useCallback((rack: Rack) => {
    const capKw = 4.0;
    const tempScore = rack.avg_temp < 35 ? 0 : rack.avg_temp < 38 ? 1 : 2;
    const capScore = rack.power_kw / capKw < 0.75 ? 0 : rack.power_kw / capKw < 0.9 ? 1 : 2;
    const score = tempScore + capScore;
    return score >= 3 ? "critical" : score >= 1 ? "warn" : "ok";
  }, []);

  return (
    <div className="space-y-6 bg-background p-4 text-foreground md:p-6">
      <header className="flex flex-col items-start gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">DCIM Simulator Pro</h1>
          <div className="text-sm text-muted-foreground">Inventory, telemetry, capacity, redundancy, and control</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            placeholder="Controller URL"
            defaultValue={apiBase}
            onBlur={(event) => {
              window.localStorage.setItem(API_KEY, event.target.value.trim());
              window.location.reload();
            }}
            className="w-[260px]"
          />
          <Input
            placeholder="Role: operator or limited"
            defaultValue={role}
            onBlur={(event) => {
              window.localStorage.setItem("dc_role", event.target.value.trim());
              window.location.reload();
            }}
            className="w-[220px]"
          />
          <Button variant="secondary" size="sm" onClick={() => setForceMock((value) => !value)}>
            {forceMock ? "Use API" : "Use mock"}
          </Button>
          <Badge variant={apiEnabled ? "default" : "secondary"}>
            {apiEnabled ? "Controller linked" : "Mock only"}
          </Badge>
        </div>
      </header>

      {showApiBanner && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-500 bg-amber-500/10 p-3 text-sm">
          <AlertTriangle className="h-4 w-4" />
          Fetch is failing. Switch to mock mode or open Diagnostics to test the API.
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-5">
        <Stat icon={Thermometer} label="Room temp" value={roomView.temp_c.toFixed(1)} suffix=" °C" intent={healthIntent as "warn" | "ok" | undefined} />
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="rounded-xl bg-muted p-3">
              <Fan className="h-6 w-6 animate-spin-slow" />
            </div>
            <div>
              <div className="text-sm text-muted-foreground">CRAC fan</div>
              <div className="text-2xl font-semibold tracking-tight">{roomView.fan_rpm || 1800} rpm</div>
            </div>
          </CardContent>
        </Card>
        <Stat icon={Zap} label="IT load" value={itKw.toFixed(2)} suffix=" kW" />
        <Stat icon={Gauge} label="Cooling" value={(gridView.cooling_kw || 0).toFixed(2)} suffix=" kW" />
        <Stat icon={Power} label="PUE" value={(gridView.pue || 0).toFixed(2)} />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <TrendPanel data={seriesView} />
        </div>
        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-medium">
                <Settings className="h-5 w-5" />
                Controls
              </div>
              <Badge>{apiEnabled ? "API live" : "Mock mode"}</Badge>
            </div>
            <div className="grid gap-6 md:grid-cols-2">
              <div>
                <div className="mb-2 text-sm">CRAC fan RPM</div>
                <Slider defaultValue={[roomView.fan_rpm || 1800]} min={1400} max={2800} step={100} onValueChange={([value]) => setFan(value)} />
                <div className="mt-2 flex items-center justify-between text-sm text-muted-foreground">
                  <span>{roomView.fan_rpm || 1800} rpm</span>
                  <Button size="sm" onClick={() => setFan((roomView.fan_rpm || 1800) + 100)}>
                    Boost
                  </Button>
                </div>
              </div>
              <div>
                <div className="mb-2 text-sm">Room target temp</div>
                <Slider defaultValue={[roomView.temp_c || 24]} min={20} max={30} step={0.5} onValueChange={([value]) => setTarget(value)} />
                <div className="mt-2 flex items-center justify-between text-sm text-muted-foreground">
                  <span>{roomView.temp_c?.toFixed(1)} °C</span>
                  <Button size="sm" onClick={() => setTarget(Math.max(20, (roomView.temp_c || 24) - 0.5))}>
                    Trim
                  </Button>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={startGen} disabled={limited}>
                Start generator
              </Button>
              <Button variant="secondary" size="sm" onClick={stopGen} disabled={limited}>
                Stop generator
              </Button>
            </div>
            <div className="text-xs text-muted-foreground">
              Controls call the controller API if configured. In mock mode they adjust the local simulator only.
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <CapacityPanel racks={rackView} grid={gridView} ups={upsView} genset={gensetView} redundancy={redundancyView} />
        <OptimizationPanel racks={rackView} room={roomView} grid={gridView} ups={upsView} genset={gensetView} redundancy={redundancyView} onApply={applyAction} />
        <DiagnosticsPanel
          apiEnabled={apiEnabled}
          error={controller.error}
          onClearApi={() => {
            window.localStorage.removeItem(API_KEY);
            window.location.reload();
          }}
          onUseMock={() => setForceMock(true)}
          onTest={runTests}
          tests={tests}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {rackView.map((rack: Rack, index: number) => {
          const capKw = 4.0;
          const capPct = (rack.power_kw / capKw) * 100;
          const state = rackHealth(rack);
          return (
            <Card
              key={rack.rack ?? index}
              className={state === "critical" ? "border-red-500" : state === "warn" ? "border-amber-400" : ""}
            >
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Server className="h-5 w-5" />
                    <span className="font-semibold">{rack.rack || `R${index + 1}`}</span>
                  </div>
                  <Badge variant={state === "critical" ? "destructive" : "secondary"}>
                    {state === "critical" ? "Critical" : state === "warn" ? "Warning" : "OK"}
                  </Badge>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div className="text-sm text-muted-foreground">IT power</div>
                  <div className="text-right font-medium">{rack.power_kw?.toFixed(2)} kW</div>
                  <div className="text-sm text-muted-foreground">Capacity</div>
                  <div className={`text-right font-medium ${capColor(capPct)}`}>
                    {capKw.toFixed(1)} kW ({Math.round(capPct)}%)
                  </div>
                  <div className="text-sm text-muted-foreground">Avg temp</div>
                  <div className="text-right font-medium">{rack.avg_temp?.toFixed(1)} °C</div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section>
        <Card>
          <CardContent className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 font-medium">
                <Activity className="h-5 w-5" />
                Inventory
              </div>
              {controller.error && <Badge variant="destructive">{controller.error}</Badge>}
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {(controller.devices || []).map((device, index) => (
                <Card key={device.id ?? index} className="rounded-xl">
                  <CardContent className="space-y-1 p-3">
                    <div className="font-medium">{device.name || device.display || device.model || `device-${index}`}</div>
                    <div className="text-xs text-muted-foreground">{device.device_role?.name || device.role?.name || device.role || "device"}</div>
                    <div className="text-xs">
                      {device.site?.name || device.site || "Site"} • {device.rack?.name || device.rack || "Rack"}
                    </div>
                  </CardContent>
                </Card>
              ))}
              {(!controller.devices || controller.devices.length === 0) && (
                <div className="text-sm text-muted-foreground">No devices yet. Add some or keep previewing in mock mode.</div>
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      <footer className="py-6 text-xs text-muted-foreground">
        Tip: paste your controller URL above (example http://localhost:8080). The app stores it locally and reloads.
      </footer>
    </div>
  );
}
