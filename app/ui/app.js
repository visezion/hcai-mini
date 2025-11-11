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
  if (!actions.length) {
    body.innerHTML = '<tr><td colspan="5">No controller actions recorded</td></tr>';
    return;
  }
  actions.forEach((action) => {
    let reason = action.reason || '--';
    let status = action.status || '--';
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${formatTime(action.ts)}</td>
      <td>${action.device_id}</td>
      <td>${action.mode}</td>
      <td>${reason}</td>
      <td>${status}</td>`;
    body.appendChild(row);
  });
}

function renderAnomalies(anomalies = []) {
  const list = document.getElementById('anomalies-list');
  list.innerHTML = '';
  if (!anomalies.length) {
    list.innerHTML = '<li class="empty">No anomaly alerts in the last window.</li>';
    return;
  }
  anomalies.forEach((entry) => {
    const li = document.createElement('li');
    const alarm = Number(entry.is_alarm) === 1;
    li.className = alarm ? 'alarm' : '';
    li.innerHTML = `
      <div>
        <strong>${entry.rack || 'rack'}</strong>
        <span>${formatTime(entry.ts)}</span>
      </div>
      <p>Score: ${entry.score?.toFixed ? entry.score.toFixed(3) : entry.score} (th ${entry.threshold})</p>`;
    list.appendChild(li);
  });
}

function renderDiscovery(discoverPayload) {
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
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${device.ip}</td>
      <td>${device.proto || 'unknown'}</td>
      <td>${device.guess || '--'}</td>`;
    const td = document.createElement('td');
    const btn = document.createElement('button');
    btn.textContent = 'Approve';
    btn.addEventListener('click', async () => {
      const payload = {
        id: `${device.proto || 'dev'}_${device.ip.replace(/\./g, '_')}`,
        type: device.guess || 'crac',
        proto: device.proto || 'modbus',
        host: device.ip,
        port: device.port || 502,
        map: device.map || 'crac_standard',
      };
      await postJSON('/discover/approve', payload);
      btn.disabled = true;
    });
    td.appendChild(btn);
    tr.appendChild(td);
    body.appendChild(tr);
  });
}

const ws = new WebSocket(`ws://${window.location.host}/ws`);
ws.onmessage = (event) => {
  const payload = JSON.parse(event.data);
  renderTiles(payload.tiles);
  renderDiscovery(payload.discover);
  renderActions(payload.actions);
  renderAnomalies(payload.anomalies);
  renderStatus(payload.status);
};

const startButton = document.getElementById('start-discovery');
if (startButton) {
  startButton.addEventListener('click', async () => {
    const subnet = document.getElementById('subnet').value;
    await postJSON('/discover/start', { subnet });
  });
}
