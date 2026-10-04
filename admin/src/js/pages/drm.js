import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadDRM() {
  const [subsR, simR, cfgR, contentR, geoR, logR] = await Promise.all([
    api('/admin/drm/subscriptions'),
    api('/admin/drm/subscriptions/sim-list'),
    api('/admin/drm/config'),
    api('/admin/drm/content'),
    api('/admin/drm/geo-rules'),
    api('/admin/drm/license-log?limit=20'),
  ]);
  const subs = await subsR.json();
  const simSubs = await simR.json();
  const cfg = await cfgR.json();
  const contentList = await contentR.json();
  const geoRules = await geoR.json();
  const licenseLog = await logR.json();

  const allSubs = [...subs, ...simSubs.filter(s => !subs.find(x => x.subscription_id === s.subscription_id))];
  const subRows = allSubs.map(s => {
    const pct = s.max_plays ? Math.min(100, Math.round((s.plays_used / s.max_plays) * 100)) : 0;
    const bar = s.max_plays ? `<div style="width:80px;height:6px;background:var(--border);border-radius:3px;display:inline-block;margin-left:6px"><div style="width:${pct}%;height:100%;background:${pct >= 100 ? 'var(--red)' : pct > 60 ? 'var(--yellow)' : 'var(--green)'};border-radius:3px"></div></div>` : '';
    return `<tr>
      <td><code>${s.subscription_id}</code></td>
      <td>${s.plays_used}${s.max_plays ? `/${s.max_plays}` : ''}${bar}</td>
      <td style="display:flex;gap:4px">
        ${s.max_plays ? `<button class="btn" onclick="consumePlay('${s.subscription_id}')">+1 Play</button>` : ''}
        <button class="btn" onclick="resetSub('${s.subscription_id}')">Reset</button>
        <button class="btn danger" onclick="revokeSub('${s.subscription_id}')">Revocar</button>
      </td></tr>`;
  }).join('');

  const contentRows = contentList.map(c => `<tr>
    <td><code>${c.content_id}</code></td>
    <td><span class="badge blue">${c.drm_system}</span></td>
    <td>${c.availability_windows?.length ? c.availability_windows.map(w => `${w.start_time.slice(0, 10)} → ${w.end_time.slice(0, 10)}`).join('<br>') : '—'}</td>
    <td>${c.created_at?.slice(0, 16).replace('T', ' ') || '—'}</td>
    <td><button class="btn danger" onclick="deleteDrmContent('${c.content_id}')">Eliminar</button></td>
  </tr>`).join('');

  const geoRows = geoRules.map(g => `<tr>
    <td><code>${g.content_id}</code></td>
    <td>${g.blocked_regions.map(r => `<span class="badge red">${r}</span>`).join(' ') || '—'}</td>
    <td><button class="btn danger" onclick="deleteGeoRule('${g.content_id}')">Eliminar</button></td>
  </tr>`).join('');

  const logRows = licenseLog.map(e => `<tr>
    <td>${e.ts}</td><td>${e.actor}</td>
    <td><code>${e.action}</code></td><td>${e.detail || '—'}</td>
  </tr>`).join('');

  const inp = (id, ph, w = 'flex:1') =>
    `<div style="${w}"><input id="${id}" placeholder="${ph}" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem"/></div>`;

  setContent(`
    <!-- Estado EZDRM -->
    <div class="section-title">Estado EZDRM</div>
    <div class="grid-3" style="margin-bottom:1rem">
      <div class="card"><div class="label">Modo</div><div class="value ${cfg.stub_mode ? 'yellow' : 'green'}">${cfg.stub_mode ? 'STUB' : 'Producción'}</div></div>
      <div class="card"><div class="label">Credenciales</div><div class="value ${cfg.credentials_set ? 'green' : 'red'}">${cfg.credentials_set ? '✓ Config' : '✗ Faltan'}</div></div>
      <div class="card"><div class="label">Whitelabel ID</div><div class="value ${cfg.whitelabel_id_set ? 'green' : 'red'}">${cfg.whitelabel_id_set ? '✓ Config' : '✗ Falta'}</div></div>
      <div class="card"><div class="label">API base URL</div><div class="value" style="font-size:0.75rem;word-break:break-all">${cfg.api_base_url}</div></div>
      <div class="card"><div class="label">Timeout</div><div class="value">${cfg.request_timeout}s</div></div>
    </div>
    ${cfg.stub_mode ? `<div style="background:rgba(255,193,7,0.08);border:1px solid rgba(255,193,7,0.3);border-radius:6px;padding:0.75rem;font-size:0.82rem;margin-bottom:1rem">
      ⚠️ Modo STUB activo — las licencias son ficticias. Para activar EZDRM real, configura
      <code>EZDRM_USERNAME</code>, <code>EZDRM_PASSWORD</code> y <code>EZDRM_WHITELABEL_ID</code>.
    </div>` : ''}

    <!-- Contenidos protegidos -->
    <div class="section-title">Contenidos protegidos por DRM</div>
    <div class="card" style="max-width:700px;margin-bottom:1rem;display:flex;gap:0.75rem;align-items:flex-end;flex-wrap:wrap">
      ${inp('drm-cid', 'content_id (ej: live1)')}
      <div style="width:160px"><select id="drm-sys" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem">
        <option value="widevine">Widevine</option><option value="playready">PlayReady</option><option value="fairplay">FairPlay</option>
      </select></div>
      ${inp('drm-win-start', 'Inicio (ISO 8601)', 'width:180px')}
      ${inp('drm-win-end', 'Fin (ISO 8601)', 'width:180px')}
      <button class="btn" onclick="createDrmContent()">+ Añadir</button>
    </div>
    ${contentList.length ? `<table><thead><tr><th>Content ID</th><th>DRM System</th><th>Ventanas</th><th>Creado</th><th></th></tr></thead><tbody>${contentRows}</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem">Sin contenidos registrados</p>'}

    <!-- Reglas de geobloqueo -->
    <div class="section-title" style="margin-top:1.5rem">Reglas de geobloqueo por contenido</div>
    <div class="card" style="max-width:600px;margin-bottom:1rem;display:flex;gap:0.75rem;align-items:flex-end;flex-wrap:wrap">
      ${inp('geo-cid', 'content_id')}
      ${inp('geo-regions', 'Regiones bloqueadas (ej: DE,FR,US)')}
      <button class="btn" onclick="setGeoRule()">Aplicar</button>
    </div>
    ${geoRules.length ? `<table><thead><tr><th>Content ID</th><th>Regiones bloqueadas</th><th></th></tr></thead><tbody>${geoRows}</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem">Sin reglas de geobloqueo</p>'}

    <!-- Frequency Rights / max_plays -->
    <div class="section-title" style="margin-top:1.5rem">Frequency Rights Management (max_plays)</div>
    <div class="grid-3" style="margin-bottom:0.75rem">
      <div class="card"><div class="label">Subs Redis</div><div class="value">${subs.length}</div></div>
      <div class="card"><div class="label">Subs simuladas</div><div class="value yellow">${simSubs.length}</div></div>
    </div>
    <div class="card" style="max-width:480px;margin-bottom:1rem;display:flex;gap:0.75rem;align-items:flex-end">
      <div style="flex:1"><div style="font-size:0.75rem;color:var(--muted);margin-bottom:4px">Subscription ID</div>
        <input id="drm-id" placeholder="sub_auto" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem"/></div>
      <div style="width:80px"><div style="font-size:0.75rem;color:var(--muted);margin-bottom:4px">Max plays</div>
        <input id="drm-max" type="number" value="5" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem"/></div>
      <button class="btn" onclick="createSimSub()">+ Crear</button>
    </div>
    ${allSubs.length ? `<table><thead><tr><th>Subscription ID</th><th>Plays</th><th>Acciones</th></tr></thead><tbody>${subRows}</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem">Sin datos — crea una suscripción de prueba</p>'}

    <!-- Log de licencias DRM -->
    <div class="section-title" style="margin-top:1.5rem">Log de auditoría DRM (últimas 20)</div>
    ${licenseLog.length ? `<table><thead><tr><th>Timestamp</th><th>Actor</th><th>Acción</th><th>Detalle</th></tr></thead><tbody>${logRows}</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem">Sin acciones DRM registradas</p>'}`);
}

async function createDrmContent() {
  const cid   = document.getElementById('drm-cid')?.value.trim();
  const sys   = document.getElementById('drm-sys')?.value;
  const start = document.getElementById('drm-win-start')?.value.trim();
  const end   = document.getElementById('drm-win-end')?.value.trim();
  if (!cid) { alert('content_id requerido'); return; }
  const body = { content_id: cid, drm_system: sys };
  if (start && end) body.availability_windows = [{ start_time: start, end_time: end }];
  const r = await api('/admin/drm/content', { method: 'POST', body: JSON.stringify(body) });
  if (!r.ok) { const d = await r.json(); alert(d.error); return; }
  loadDRM();
}

async function deleteDrmContent(cid) {
  if (!confirm(`¿Eliminar configuración DRM de "${cid}"?`)) return;
  await api(`/admin/drm/content/${encodeURIComponent(cid)}`, { method: 'DELETE' });
  loadDRM();
}

async function setGeoRule() {
  const cid     = document.getElementById('geo-cid')?.value.trim();
  const regions = document.getElementById('geo-regions')?.value.trim().toUpperCase().split(',').map(r => r.trim()).filter(Boolean);
  if (!cid) { alert('content_id requerido'); return; }
  const r = await api('/admin/drm/geo-rules', { method: 'POST', body: JSON.stringify({ content_id: cid, blocked_regions: regions }) });
  if (!r.ok) { const d = await r.json(); alert(d.error); return; }
  loadDRM();
}

async function deleteGeoRule(cid) {
  if (!confirm(`¿Eliminar geobloqueo de "${cid}"?`)) return;
  await api(`/admin/drm/geo-rules/${encodeURIComponent(cid)}`, { method: 'DELETE' });
  loadDRM();
}

async function resetSub(id) {
  await api(`/admin/drm/subscriptions/${id}/reset`, { method: 'POST' });
  loadDRM();
}

async function revokeSub(id) {
  if (!confirm(`¿Revocar acceso de ${id}?`)) return;
  await api(`/admin/drm/subscriptions/${id}/revoke`, { method: 'POST' });
  loadDRM();
}

async function createSimSub() {
  const id  = document.getElementById('drm-id')?.value.trim() || '';
  const max = parseInt(document.getElementById('drm-max')?.value || '5');
  const body = id ? { subscription_id: id, max_plays: max } : { max_plays: max };
  await api('/admin/drm/subscriptions/simulate', { method: 'POST', body: JSON.stringify(body) });
  loadDRM();
}

async function consumePlay(id) {
  const r = await api('/admin/drm/subscriptions/consume', { method: 'POST', body: JSON.stringify({ subscription_id: id }) });
  const d = await r.json();
  if (!d.allowed) alert(`❌ max_plays (${d.max_plays}) superado para ${id}`);
  loadDRM();
}

window.createDrmContent = createDrmContent;
window.deleteDrmContent = deleteDrmContent;
window.setGeoRule       = setGeoRule;
window.deleteGeoRule    = deleteGeoRule;
window.resetSub         = resetSub;
window.revokeSub        = revokeSub;
window.createSimSub     = createSimSub;
window.consumePlay      = consumePlay;
