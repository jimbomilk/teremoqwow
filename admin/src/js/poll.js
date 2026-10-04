import { api } from './api.js';

export function startGlobalStatusPoll() {
  async function poll() {
    try {
      const rc = await api('/admin/relay/connections');
      const rcData = await rc.json();
      document.getElementById('gs-relay').textContent = rcData.online ? 'relay 🟢' : 'relay 🔴';
      document.getElementById('gs-relay').style.color = rcData.online ? 'var(--green)' : 'var(--red)';
      const bc = await api('/admin/broadcasts');
      const bcData = await bc.json();
      const active = bcData.filter(b => b.status === 'active');
      const viewers = bcData.reduce((s, b) => s + (b.viewers || 0), 0);
      document.getElementById('gs-streams').textContent = `${active.length} señales`;
      document.getElementById('gs-viewers').textContent = `${viewers} viewers`;
      const al = await api('/admin/audio/alerts');
      const alData = await al.json();
      const alertsEl = document.getElementById('gs-alerts');
      alertsEl.textContent = `${alData.length} ${alData.length === 1 ? 'alerta' : 'alertas'}`;
      alertsEl.style.color = alData.length > 0 ? 'var(--red)' : 'var(--muted)';
    } catch (_) {}
  }
  poll();
  setInterval(poll, 10000);
}
