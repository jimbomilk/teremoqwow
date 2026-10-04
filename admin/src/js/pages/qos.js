import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadQoS() {
  const [alertsR, latencyR] = await Promise.all([
    api('/admin/qos/alerts'),
    api('/admin/qos/latency'),
  ]);
  const alertData = await alertsR.json();
  const { alerts } = alertData;
  const latency = await latencyR.json();
  const alertsHtml = alerts.length
    ? alerts.map(a => {
        const sim = a.labels?.source === 'simulated';
        return `<div class="alert-item" style="${sim ? 'border-color:rgba(255,193,7,0.4);background:rgba(255,193,7,0.08)' : ''}">
          <span class="aname">${a.labels?.alertname || '?'}</span>
          ${sim ? '<span class="badge yellow" style="margin-left:6px">simulada</span>' : ''}
          — ${a.annotations?.description || a.annotations?.summary || ''}
          ${sim ? `<button class="btn" style="float:right;font-size:0.72rem;padding:2px 8px" onclick="resolveAlert('${a.id}')">Resolver</button>` : ''}
        </div>`;
      }).join('')
    : '<p style="color:var(--green);font-size:0.85rem">✓ Sin alertas activas</p>';
  const latRows = latency.map(r => `<tr><td><code>${r.namespace}</code></td>
    <td class="${r.p95 > 700 ? 'red' : ''}">${r.p95 || 0} ms</td><td>${r.samples}</td></tr>`).join('');
  const grafana = window.GRAFANA_URL || 'http://localhost:3000';
  let grafanaAvailable = false;
  try {
    const gr = await fetch(`${grafana}/api/health`, { signal: AbortSignal.timeout(2000) });
    grafanaAvailable = gr.ok;
  } catch (e) { grafanaAvailable = false; }

  const grafanaHtml = grafanaAvailable
    ? `<iframe class="grafana" src="${grafana}/d/teremoqwow?orgId=1&kiosk=tv" title="Grafana"></iframe>`
    : `<div style="background:var(--surface);border:1px dashed var(--border);border-radius:8px;padding:2rem;text-align:center;color:var(--muted)">
        <div style="font-size:1.5rem;margin-bottom:0.5rem">📊</div>
        <div style="margin-bottom:0.5rem">Grafana no está disponible en modo dev sin Docker</div>
        <div style="font-size:0.8rem">Para ver el dashboard completo: <code style="background:var(--bg);padding:2px 6px;border-radius:4px">docker compose up grafana prometheus</code></div>
        <div style="margin-top:1rem"><a href="${grafana}" target="_blank" style="color:var(--accent)">${grafana}</a></div>
       </div>`;

  const alertNames = ['LipSyncDrift', 'BufferBelowThreshold', 'HighE2ELatency', 'VideoContinuityError'];
  setContent(`
    <div class="section-title">Alertas Prometheus activas ${alertData.simulated ? `<span style="color:var(--muted);font-size:0.75rem">(${alertData.simulated} simuladas)</span>` : ''}</div>
    ${alertsHtml}
    <div class="section-title" style="margin-top:1.25rem">Consola de pruebas — disparar alerta</div>
    <div class="card" style="max-width:480px;margin-bottom:1rem;display:flex;gap:0.75rem;align-items:flex-end">
      <div style="flex:1"><div style="font-size:0.75rem;color:var(--muted);margin-bottom:4px">Tipo de alerta</div>
        <select id="alert-type" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem">
          ${alertNames.map(n => `<option value="${n}">${n}</option>`).join('')}
        </select></div>
      <button class="btn" style="border-color:var(--red);color:var(--red)" onclick="fireAlert()">🔥 Disparar</button>
    </div>
    <div class="section-title" style="margin-top:1.25rem">Latencia P95 por broadcast (últimos 15 min)</div>
    <table><thead><tr><th>Namespace</th><th>P95</th><th>Muestras</th></tr></thead><tbody>${latRows}</tbody></table>
    <div class="section-title" style="margin-top:1.25rem">Dashboard Grafana</div>
    ${grafanaHtml}`);
}

async function fireAlert() {
  const name = document.getElementById('alert-type')?.value;
  await api('/admin/qos/alerts/test', { method: 'POST', body: JSON.stringify({ alert_name: name }) });
  loadQoS();
}

async function resolveAlert(id) {
  await api('/admin/qos/alerts/resolve', { method: 'POST', body: JSON.stringify({ id }) });
  loadQoS();
}

window.fireAlert    = fireAlert;
window.resolveAlert = resolveAlert;
