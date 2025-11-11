const pages = document.querySelectorAll('section.page');
const navButtons = document.querySelectorAll('nav button');
navButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    navButtons.forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    pages.forEach((section) => {
      section.classList.toggle('active', section.id === btn.dataset.page);
    });
  });
});

async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  return res.json();
}

function renderTiles(data) {
  const container = document.getElementById('tiles');
  container.innerHTML = '';
  Object.entries(data || {}).forEach(([rack, info]) => {
    const card = document.createElement('div');
    card.className = 'tile';
    card.innerHTML = `<h3>${rack}</h3>
      <p>Temp: ${(info.metrics?.temp_c ?? '--')} &deg;C</p>
      <p>Humidity: ${(info.metrics?.hum_pct ?? '--')} %</p>
      <p>Power: ${(info.metrics?.power_kw ?? '--')} kW</p>`;
    container.appendChild(card);
  });
}

function renderDiscovery(devices) {
  const body = document.getElementById('discovery-body');
  body.innerHTML = '';
  (devices || []).forEach((device) => {
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
};

const startButton = document.getElementById('start-discovery');
startButton.addEventListener('click', async () => {
  const subnet = document.getElementById('subnet').value;
  await postJSON('/discover/start', { subnet });
});
