import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadSecurity() {
  const r = await api('/admin/security/rate-limit-hits');
  const hits = await r.json();
  const rows = hits.map(h => `<tr><td><code>${h.ip}</code></td><td>${h.requests}</td><td>${h.ttl_s}s</td></tr>`).join('');
  setContent(`
    <div class="section-title">Rate-limit hits recientes (Redis rl:*)</div>
    ${hits.length ? `<table><thead><tr><th>IP</th><th>Requests</th><th>TTL</th></tr></thead><tbody>${rows}</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem">Sin hits (Redis vacío o no conectado)</p>'}
    <div class="section-title" style="margin-top:1.5rem">Rotar secretos</div>
    <div style="display:flex;gap:1rem;margin-top:0.5rem">
      <button class="btn" onclick="rotateSecret('webhook')">Rotar WEBHOOK_SECRET</button>
      <button class="btn" onclick="rotateSecret('jwt')">Rotar JWT key</button>
    </div>`);
}

async function rotateSecret(type) {
  const r = await api('/admin/security/rotate-secret', { method: 'POST', body: JSON.stringify({ type }) });
  const data = await r.json();
  alert(`Nuevo secreto (preview): ${data.new_secret_preview}\n\nAcción: ${data.action}\nVariable: ${data.env_var}`);
}

window.rotateSecret = rotateSecret;
