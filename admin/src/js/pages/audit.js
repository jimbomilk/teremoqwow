import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadAudit() {
  const r = await api('/admin/audit?limit=50');
  const log = await r.json();
  const rows = log.map(e => `<tr><td>${e.ts}</td><td>${e.actor}</td>
    <td><span class="badge blue">${e.role}</span></td>
    <td><code>${e.action}</code></td><td>${e.detail || '—'}</td><td>${e.ip}</td></tr>`).join('');
  setContent(`
    <div class="section-title">Log de auditoría (últimas 50 acciones)</div>
    ${log.length ? `<table><thead><tr><th>Timestamp</th><th>Actor</th><th>Rol</th><th>Acción</th><th>Detalle</th><th>IP</th></tr></thead><tbody>${rows}</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem">Sin acciones registradas todavía</p>'}`);
}
