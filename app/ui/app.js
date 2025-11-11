function postJSON(url, payload) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  }).then((res) => res.json());
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

function renderStatus(status = {}) {
  document.querySelector('#stat-site strong').textContent = status.site || '--';
  const modeEl = document.querySelector('#stat-mode strong');
  modeEl.textContent = status.mode || '--';
  modeEl.className = `mode-chip ${status.mode || 'unknown'}`;
  document.querySelector('#stat-racks strong').textContent = status.tracked_racks ?? 0;
  document.querySelector('#stat-ingest strong').textContent = formatTime(status.last_ingest_ts);
  const telMeta = document.getElementById('telemetry-updated');
  if (telMeta) {
    telMeta.textContent = `Updated ${formatTime(status.last_ingest_ts)}`;
  }
  const ingestCard = document.querySelector('#summary-ingest .value');
  const ingestMeta = document.getElementById('summary-ingest-meta');
  if (ingestCard) ingestCard.textContent = (status.ingest_count ?? 0).toLocaleString();
  if (ingestMeta) ingestMeta.textContent = status.last_ingest_ts ? `Last at ${formatTime(status.last_ingest_ts)}` : 'Awaiting telemetry�';
}

function renderTiles(data) {
  const container = document.getElementById('tiles');
  container.innerHTML = '';
  const entries = Object.entries(data || {});
  if (!entries.length) {
    container.innerHTML = '<p class="empty">Waiting for telemetry...</p>';
    return;
  }
  entries.forEach(([rack, info]) => {
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
}

function renderActions(actions = []) {
  const body = document.getElementById('actions-body');
  body.innerHTML = '';
  const summaryVal = document.querySelector('#summary-actions .value');
  const summaryMeta = document.getElementById('summary-actions-meta');
  if (summaryVal) summaryVal.textContent = actions.length.toString();
  if (!actions.length) {
    body.innerHTML = '<tr><td colspan="5">No controller actions recorded</td></tr>';
    if (summaryMeta) summaryMeta.textContent = 'No actions queued';
    return;
  }
  if (summaryMeta) summaryMeta.textContent = `${actions[0].mode} � ${actions[0].reason || 'controller event'}`;
  actions.forEach((action) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${formatTime(action.ts)}</td>
      <td>${action.device_id}</td>
      <td>${action.mode}</td>
      <td>${action.reason || '--'}</td>
      <td>${action.status || '--'}</td>`;
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
    const latestAlarm = anomalies.find((a) => Number(a.is_alarm) === 1);
    summaryMeta.textContent = latestAlarm ? `${latestAlarm.rack} flagged at ${formatTime(latestAlarm.ts)}` : 'All scores healthy';
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

let lastDiscoveryPayload = null;
const approvedDevices = new Set();

function renderDiscovery(discoverPayload) {
  lastDiscoveryPayload = discoverPayload;
  const body = document.getElementById('discovery-body');
  body.innerHTML = '';
  const devices = discoverPayload?.devices || [];
  const state = discoverPayload?.state || {};
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
  if (!devices.length) {
    body.innerHTML = '<tr><td colspan="4">No devices discovered yet</td></tr>';
    return;
  }
  devices.forEach((device) => {
    const key = `${device.proto || 'proto'}:${device.ip}`;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${device.ip}</td>
      <td>${device.proto || 'unknown'}</td>
      <td>${device.guess || '--'}</td>`;
    const td = document.createElement('td');
    const btn = document.createElement('button');
    if (approvedDevices.has(key)) {
      btn.textContent = 'Approved';
      btn.disabled = true;
    } else {
      btn.textContent = 'Approve';
      btn.addEventListener('click', async () => {
        const payload = {
          id: `${device.proto || 'dev'}_${device.ip.replace(/\\./g, '_')}`,
          type: device.guess || 'crac',
          proto: device.proto || 'modbus',
          host: device.ip,
          port: device.port || 502,
          map: device.map || 'crac_standard',
        };
        btn.disabled = true;
        btn.textContent = 'Saving...';
        try {
          await postJSON('/discover/approve', payload);
          approvedDevices.add(key);
          btn.textContent = 'Approved';
        } catch (err) {
          console.error('approve failed', err);
          btn.disabled = false;
          btn.textContent = 'Approve';
          alert('Unable to approve device. Check logs.');
        }
      });
    }
    td.appendChild(btn);
    tr.appendChild(td);
    body.appendChild(tr);
  });
}

function initDiscoveryButton() {
  const startButton = document.getElementById('start-discovery');
  if (startButton) {
    startButton.addEventListener('click', async () => {
      const subnet = document.getElementById('subnet').value;
      await postJSON('/discover/start', { subnet });
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
  ws.onclose = () => {
    setTimeout(initWebSocket, 2000);
  };
  ws.onerror = () => {
    ws.close();
  };
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initDiscoveryButton();
  initWebSocket();
});





