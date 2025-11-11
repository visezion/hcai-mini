const DEFAULT_PORTS = { modbus: 502, snmp: 161, bacnet: 47808, mqtt: 1883 };

let lastDiscoveryPayload = null;
let currentRack = null;
const approvedDevices = new Set();

function postJSON(url, payload) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  }).then(async (res) => {
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const data = await res.json();
        detail = data.detail || detail;
      } catch (err) {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json();
  });
}

function formatTime(ts) {
  if (!ts) return '--';
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function setTheme(theme) {
  document.body.setAttribute('data-theme', theme);
  localStorage.setItem('hcai-theme', theme);
  const toggle = document.getElementById('theme-toggle');
  if (toggle) toggle.checked = theme === 'dark';
}

function initTheme() {
  const stored = localStorage.getItem('hcai-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  setTheme(stored || (prefersDark ? 'dark' : 'light'));
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('change', (e) => {
      setTheme(e.target.checked ? 'dark' : 'light');
    });
  }
}

function initNavigation() {
  const navButtons = document.querySelectorAll('.nav-btn');
  const pages = document.querySelectorAll('.page');
  navButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      navButtons.forEach((b) => b.classList.remove('active'));
      pages.forEach((page) => page.classList.remove('active'));
      btn.classList.add('active');
      const target = document.getElementById(`page-${btn.dataset.page}`);
      if (target) target.classList.add('active');
    });
  });
}

function renderStatus(status = {}) {
  document.querySelector('#stat-site strong').textContent = status.site || '--';
  const modeEl = document.querySelector('#stat-mode strong');
  modeEl.textContent = status.mode || '--';
  modeEl.className = `mode-chip ${status.mode || 'unknown'}`;
  document.querySelector('#stat-racks strong').textContent = status.tracked_racks ?? 0;
  document.querySelector('#stat-ingest strong').textContent = formatTime(status.last_ingest_ts);
  const telMeta = document.getElementById('telemetry-updated');
  if (telMeta) telMeta.textContent = `Updated ${formatTime(status.last_ingest_ts)}`;
  const ingestCard = document.querySelector('#summary-ingest .value');
  const ingestMeta = document.getElementById('summary-ingest-meta');
  if (ingestCard) ingestCard.textContent = (status.ingest_count ?? 0).toLocaleString();
  if (ingestMeta) ingestMeta.textContent = status.last_ingest_ts ? `Last at ${formatTime(status.last_ingest_ts)}` : 'Awaiting telemetry…';
  const autoToggle = document.getElementById('auto-toggle');
  if (autoToggle && typeof status.auto_enabled === 'boolean') {
    autoToggle.checked = status.auto_enabled;
  }
}

function renderTiles(data) {
  const container = document.getElementById('tiles');
  container.innerHTML = '';
  const entries = Object.entries(data || {});
  if (!entries.length) {
    container.innerHTML = '<p class="empty">Waiting for telemetry...</p>';
  }
  const racks = [];
  entries.forEach(([rack, info]) => {
    racks.push(rack);
    const card = document.createElement('div');
    card.className = 'tile';
    const metrics = info.metrics || {};
    card.innerHTML = `
      <div class="tile-header">
        <h3>${rack}</h3>
        <span>${formatTime(info.ts)}</span>
      </div>
      <div class="tile-body">
        <div><label>Temp</label><strong>${metrics.temp_c ?? '--'} &deg;C</strong></div>
        <div><label>Humidity</label><strong>${metrics.hum_pct ?? '--'} %</strong></div>
        <div><label>Power</label><strong>${metrics.power_kw ?? '--'} kW</strong></div>
        <div><label>Airflow</label><strong>${metrics.airflow_cfm ?? '--'} cfm</strong></div>
      </div>`;
    container.appendChild(card);
  });
  if (racks.length) {
    const selector = document.getElementById('history-rack');
    if (selector) {
      selector.innerHTML = racks.map((r) => `<option value="${r}">${r}</option>`).join('');
      if (!currentRack || !racks.includes(currentRack)) currentRack = racks[0];
      selector.value = currentRack;
      loadHistory(currentRack);
    }
  }
}

async function loadHistory(rack) {
  if (!rack) return;
  try {
    const res = await fetch(`/telemetry/history?rack=${encodeURIComponent(rack)}&limit=40`);
    const data = await res.json();
    renderHistory(data.points || []);
  } catch (err) {
    console.error('history fetch failed', err);
  }
}

function renderHistory(points = []) {
  const list = document.getElementById('history-list');
  if (!list) return;
  list.innerHTML = '';
  if (!points.length) {
    list.innerHTML = '<li><span>No history yet</span><span>--</span></li>';
    return;
  }
  points.slice().reverse().forEach((pt) => {
    const li = document.createElement('li');
    li.innerHTML = `<span>${pt.ts}</span><span>${pt.temp_c ?? '--'} °C</span>`;
    list.appendChild(li);
  });
}

function renderActions(actions = []) {
  const body = document.getElementById('actions-body');
  body.innerHTML = '';
  const summaryVal = document.querySelector('#summary-actions .value');
  const summaryMeta = document.getElementById('summary-actions-meta');
  if (summaryVal) summaryVal.textContent = actions.length.toString();
  if (!actions.length) {
    body.innerHTML = '<tr><td colspan="7">No controller actions recorded</td></tr>';
    if (summaryMeta) summaryMeta.textContent = 'No actions queued';
    return;
  }
  if (summaryMeta) summaryMeta.textContent = `${actions[0].mode} · ${actions[0].reason || 'controller event'}`;
  actions.forEach((action) => {
    const cmd = action.cmd || {};
    const explain = cmd.explain?.message || '--';
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${action.id ?? '--'}</td>
      <td>${formatTime(action.ts)}</td>
      <td>${action.device_id}</td>
      <td>${action.reason || '--'}</td>
      <td>${explain}</td>
      <td>${action.status || '--'}</td>
      <td></td>`;
    const cell = row.querySelector('td:last-child');
    if (action.status === 'pending_manual') {
      const btn = document.createElement('button');
      btn.textContent = 'Comply';
      btn.addEventListener('click', () => approveAction(action.id));
      cell.appendChild(btn);
    } else {
      cell.textContent = '-';
    }
    body.appendChild(row);
  });
}

function renderAnomalies(anomalies = []) {
  const list = document.getElementById('anomalies-list');
  list.innerHTML = '';
  const summaryVal = document.querySelector('#summary-anomaly .value');
  const summaryMeta = document.getElementById('summary-anomaly-meta');
  if (summaryVal) summaryVal.textContent = anomalies.filter((a) => Number(a.is_alarm) === 1).length;
  if (!anomalies.length) {
    list.innerHTML = '<li class="empty">No anomaly alerts in the last window.</li>';
    if (summaryMeta) summaryMeta.textContent = 'No active alerts';
    return;
  }
  if (summaryMeta) {
    const alarm = anomalies.find((a) => Number(a.is_alarm) === 1);
    summaryMeta.textContent = alarm ? `${alarm.rack} flagged at ${formatTime(alarm.ts)}` : 'All scores healthy';
  }
  anomalies.forEach((entry) => {
    const li = document.createElement('li');
    const alarm = Number(entry.is_alarm) === 1;
    li.className = alarm ? 'alarm' : '';
    const score = typeof entry.score === 'number' ? entry.score.toFixed(3) : entry.score;
    li.innerHTML = `
      <div>
        <strong>${entry.rack || 'rack'}</strong>
        <span>${formatTime(entry.ts)}</span>
      </div>
      <p>Score: ${score} (th ${entry.threshold})</p>`;
    list.appendChild(li);
  });
}

function renderDevices(devices = []) {
  const body = document.getElementById('devices-body');
  if (!body) return;
  body.innerHTML = '';
  if (!devices.length) {
    body.innerHTML = '<tr><td colspan="5">No devices configured</td></tr>';
    return;
  }
  devices.forEach((dev) => {
    if (dev.proto && dev.host) {
      approvedDevices.add(`${dev.proto}:${dev.host}`);
    }
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${dev.id}</td>
      <td>${dev.type || '--'}</td>
      <td>${dev.proto || '--'}</td>
      <td>${dev.host}</td>
      <td>${dev.port || '--'}</td>`;
    body.appendChild(tr);
  });
}

function renderTemplates(templates = []) {
  const body = document.getElementById('templates-body');
  if (!body) return;
  body.innerHTML = '';
  if (!templates.length) {
    body.innerHTML = '<tr><td colspan="5">No templates loaded</td></tr>';
    return;
  }
  templates.forEach((tpl) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${tpl.template || tpl.name || '--'}</td>
      <td>${tpl.proto || '--'}</td>
      <td>${tpl.type || '--'}</td>
      <td>${tpl.map || '--'}</td>
      <td>${tpl.file || '--'}</td>`;
    body.appendChild(tr);
  });
}

function renderDiscoveryHistory(history = []) {
  const list = document.getElementById('discovery-history');
  if (!list) return;
  list.innerHTML = '';
  if (!history.length) {
    list.innerHTML = '<li><span>No scans yet</span><span>--</span></li>';
    return;
  }
  history.slice(-10).forEach((entry) => {
    const count = entry.raw_count ?? entry.raw?.length ?? 0;
    const li = document.createElement('li');
    li.innerHTML = `<span>${entry.ts || '--'}</span><span>${count} hosts</span>`;
    list.appendChild(li);
  });
}

function renderDiscovery(discoverPayload = {}) {
  lastDiscoveryPayload = discoverPayload;
  const body = document.getElementById('discovery-body');
  body.innerHTML = '';
  const devices = discoverPayload.devices || [];
  const state = discoverPayload.state || {};
  const statusEl = document.getElementById('discovery-status');
  const stateName = state.status || 'idle';
  if (statusEl) {
    statusEl.textContent = state.message || 'Idle';
    statusEl.className = `status-chip ${stateName}`;
    statusEl.title = state.error || '';
  }
  const button = document.getElementById('start-discovery');
  if (button) {
    const running = stateName === 'running';
    button.disabled = running;
    button.textContent = running ? 'Scanning...' : 'Discover devices';
  }
  renderDiscoveryHistory(discoverPayload.history || []);
  if (!devices.length) {
    body.innerHTML = '<tr><td colspan="5">No devices discovered yet</td></tr>';
    return;
  }
  devices.forEach((device) => {
    const key = `${device.proto || 'proto'}:${device.ip}`;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${device.ip}</td>
      <td>${device.proto || 'unknown'}</td>
      <td>${device.map || device.template || '--'}</td>`;
    const tdValidate = document.createElement('td');
    const validateBtn = document.createElement('button');
    validateBtn.textContent = 'Validate';
    validateBtn.addEventListener('click', () => validateDevice(device));
    tdValidate.appendChild(validateBtn);
    tr.appendChild(tdValidate);
    const td = document.createElement('td');
    const btn = document.createElement('button');
    if (approvedDevices.has(key)) {
      btn.textContent = 'Approved';
      btn.disabled = true;
    } else {
      btn.textContent = 'Approve';
      btn.addEventListener('click', async () => {
        const payload = {
          id: `${device.proto || 'dev'}_${device.ip.replace(/\./g, '_')}`,
          type: device.type_guess || 'crac',
          proto: device.proto || 'modbus',
          host: device.ip,
          port: device.port || DEFAULT_PORTS[device.proto || ''] || 0,
          map: device.map || 'crac_standard',
        };
        btn.disabled = true;
        btn.textContent = 'Saving...';
        try {
          const resp = await postJSON('/discover/approve', payload);
          approvedDevices.add(key);
          btn.textContent = resp.action === 'updated' ? 'Updated' : 'Approved';
          loadDevices();
        } catch (err) {
          btn.disabled = false;
          btn.textContent = 'Approve';
          alert(err.message || 'Unable to approve device');
        }
      });
    }
    td.appendChild(btn);
    tr.appendChild(td);
    body.appendChild(tr);
  });
}

function initHistorySelector() {
  const selector = document.getElementById('history-rack');
  if (selector) {
    selector.addEventListener('change', (e) => {
      currentRack = e.target.value;
      loadHistory(currentRack);
    });
  }
}

function initDiscoveryButton() {
  const startButton = document.getElementById('start-discovery');
  if (startButton) {
    startButton.addEventListener('click', async () => {
      const subnet = document.getElementById('subnet').value;
      try {
        await postJSON('/discover/start', { subnet, actor: 'operator' });
      } catch (err) {
        alert(err.message || 'Failed to start discovery');
      }
    });
  }
}

async function validateDevice(device) {
  try {
    const port = device.port || DEFAULT_PORTS[device.proto || ''] || 0;
    const res = await postJSON('/devices/validate', { host: device.ip, port });
    alert(res.message || 'Validation succeeded');
  } catch (err) {
    alert(err.message || 'Validation failed');
  }
}

async function approveAction(id) {
  try {
    await postJSON('/actions/approve', { id });
  } catch (err) {
    alert(err.message || 'Failed to comply');
  }
}

async function loadDevices() {
  try {
    const res = await fetch('/devices');
    const data = await res.json();
    renderDevices(data.devices || []);
  } catch (err) {
    console.error('device fetch failed', err);
    renderDevices([]);
  }
}

async function loadTemplates() {
  try {
    const res = await fetch('/templates');
    const data = await res.json();
    renderTemplates(data.templates || []);
  } catch (err) {
    console.error('template fetch failed', err);
    renderTemplates([]);
  }
}

async function loadMode() {
  try {
    const res = await fetch('/mode');
    const data = await res.json();
    const toggle = document.getElementById('auto-toggle');
    if (toggle) toggle.checked = data.auto_enabled;
  } catch (err) {
    console.error('mode fetch failed', err);
  }
}

function initModeToggle() {
  const toggle = document.getElementById('auto-toggle');
  if (toggle) {
    toggle.addEventListener('change', async (e) => {
      try {
        await postJSON('/mode', { auto_enabled: e.target.checked });
      } catch (err) {
        alert(err.message || 'Failed to update mode');
      }
    });
  }
}

function initWebSocket() {
  const ws = new WebSocket(`ws://${window.location.host}/ws`);
  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    renderTiles(payload.tiles);
    renderDiscovery(payload.discover);
    renderActions(payload.actions);
    renderAnomalies(payload.anomalies);
    renderStatus(payload.status);
  };
  ws.onclose = () => setTimeout(initWebSocket, 2000);
  ws.onerror = () => ws.close();
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initNavigation();
  initDiscoveryButton();
  initHistorySelector();
  initModeToggle();
  loadMode();
  loadDevices();
  loadTemplates();
  initWebSocket();
});
