import { api } from '../api.js';
import { setContent } from '../router.js';

let _ovSelectedTemplate = null;
let _ovLLMCandidate = null;
let _ovCurrentTab = 'templates';

export async function loadOverlays() {
  const [tmplR, activeR, histR, bcR] = await Promise.all([
    api('/admin/overlays/templates'),
    api('/admin/overlays/active'),
    api('/admin/overlays/history'),
    api('/admin/broadcasts'),
  ]);
  const templates = await tmplR.json();
  const activeOverlays = await activeR.json();
  const history = await histR.json();
  const broadcasts = await bcR.json();
  const activeBC = broadcasts.filter(b => b.status === 'active');

  setContent(`
    <div style="display:grid;grid-template-columns:1fr 1.8fr 280px;gap:1rem;align-items:start">
      <div>
        <div class="section-title">Overlays activos</div>
        <div id="active-overlays-list">
          ${activeOverlays.length === 0
            ? '<p style="color:var(--muted);font-size:0.82rem">Sin overlays activos</p>'
            : activeOverlays.map(ov => `
              <div class="card" style="margin-bottom:0.5rem;padding:0.6rem 0.75rem">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem">
                  <div>
                    <span class="badge blue" style="font-size:0.65rem">${ov.template_id}</span>
                    <span style="font-size:0.7rem;color:var(--muted);margin-left:4px">${ov.zone}</span>
                    <div style="font-size:0.7rem;color:var(--muted)">${ov.broadcast_id}</div>
                  </div>
                  <button class="btn danger" style="font-size:0.7rem;padding:2px 8px"
                    onclick="unpublishOverlay('${ov.id}','${ov.broadcast_id}')">✕</button>
                </div>
              </div>`).join('')}
        </div>
        ${activeBC.length > 0 ? `
          <div style="margin-top:0.75rem">
            <button class="btn danger" style="font-size:0.75rem;width:100%"
              onclick="clearAllOverlays(document.getElementById('ov-broadcast').value)">
              🧹 Limpiar todo el broadcast
            </button>
          </div>` : ''}
      </div>
      <div>
        <div style="display:flex;gap:0;margin-bottom:1rem;border-bottom:1px solid var(--border)">
          <button id="tab-templates" onclick="switchOverlayTab('templates')"
            style="padding:0.4rem 1rem;background:var(--accent);color:#000;border:none;cursor:pointer;font-size:0.8rem">
            📋 Templates
          </button>
          <button id="tab-llm" onclick="switchOverlayTab('llm')"
            style="padding:0.4rem 1rem;background:none;color:var(--muted);border:none;cursor:pointer;font-size:0.8rem">
            ✨ Generar con IA
          </button>
        </div>
        <div id="ov-tab-templates">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;margin-bottom:0.75rem">
            <div>
              <div style="font-size:0.7rem;color:var(--muted);margin-bottom:2px">Broadcast</div>
              <select id="ov-broadcast" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.3rem;border-radius:4px;font-size:0.8rem">
                ${activeBC.map(b => `<option value="${b.id}">${b.id}</option>`).join('') || '<option value="">Sin broadcasts activos</option>'}
              </select>
            </div>
            <div>
              <div style="font-size:0.7rem;color:var(--muted);margin-bottom:2px">Zona</div>
              <select id="ov-zone" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.3rem;border-radius:4px;font-size:0.8rem">
                ${['top-left', 'top-center', 'top-right', 'middle-left', 'center', 'middle-right',
                   'bottom-left', 'bottom-center', 'bottom-right', 'bottom-bar', 'top-bar', 'full']
                  .map(z => `<option value="${z}"${z === 'bottom-bar' ? ' selected' : ''}>${z}</option>`).join('')}
              </select>
            </div>
            <div>
              <div style="font-size:0.7rem;color:var(--muted);margin-bottom:2px">Duración (s, 0=∞)</div>
              <input id="ov-duration" type="number" value="10" min="0"
                style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.3rem;border-radius:4px;font-size:0.8rem"/>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem" id="ov-template-grid">
            ${templates.map(t => `
              <div id="tmpl-card-${t.id}"
                style="background:var(--surface);border:1px solid var(--border);border-radius:6px;
                       padding:0.5rem;cursor:pointer;text-align:center"
                onclick="selectOverlayTemplate('${t.id}')">
                <div style="font-size:0.62rem;color:var(--accent);margin-bottom:3px">${t.id}</div>
                <div style="font-size:0.7rem;font-weight:500">${t.name}</div>
                <div style="font-size:0.6rem;color:var(--muted)">${t.kind}</div>
              </div>`).join('')}
          </div>
          <div id="ov-form" style="margin-top:0.75rem;display:none">
            <div class="section-title" style="margin-bottom:0.5rem" id="ov-form-title">—</div>
            <div id="ov-form-fields"></div>
            <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
              <button class="btn" onclick="previewOverlay()"
                style="flex:1;font-size:0.8rem">👁️ Vista previa</button>
              <button onclick="publishOverlay()"
                style="flex:2;background:rgba(79,195,247,0.15);border:1px solid var(--accent);
                       color:var(--accent);padding:0.35rem;border-radius:4px;cursor:pointer;font-size:0.8rem">
                📡 Publicar
              </button>
            </div>
            <div id="ov-status" style="margin-top:0.4rem;font-size:0.75rem;color:var(--muted)"></div>
          </div>
        </div>
        <div id="ov-tab-llm" style="display:none">
          <div style="margin-bottom:0.5rem">
            <div style="font-size:0.7rem;color:var(--muted);margin-bottom:2px">Prompt</div>
            <textarea id="ov-llm-prompt" placeholder="Ej: Muestra el logo de Nike en la esquina superior derecha durante 10 segundos"
              style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);
                     padding:0.5rem;border-radius:4px;font-size:0.82rem;min-height:80px;resize:vertical"></textarea>
          </div>
          <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem">
            <select id="ov-llm-zone" style="flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.3rem;border-radius:4px;font-size:0.8rem">
              <option value="">Zona automática</option>
              ${['top-left', 'top-right', 'bottom-bar', 'center', 'full'].map(z => `<option value="${z}">${z}</option>`).join('')}
            </select>
            <button onclick="generateLLMOverlay()"
              style="flex:2;background:rgba(76,175,80,0.15);border:1px solid var(--green);
                     color:var(--green);padding:0.35rem;border-radius:4px;cursor:pointer;font-size:0.8rem">
              ✨ Generar
            </button>
          </div>
          <div id="ov-llm-preview" style="display:none">
            <div class="section-title" style="margin-bottom:0.5rem">Vista previa del candidato</div>
            <div class="card" style="padding:0.5rem;margin-bottom:0.5rem">
              <pre id="ov-llm-json" style="font-size:0.65rem;color:#a0d8ef;white-space:pre-wrap;overflow-x:auto;margin:0"></pre>
            </div>
            <div style="display:flex;gap:0.5rem">
              <button onclick="publishLLMCandidate()"
                style="flex:1;background:rgba(79,195,247,0.15);border:1px solid var(--accent);
                       color:var(--accent);padding:0.35rem;border-radius:4px;cursor:pointer;font-size:0.8rem">
                📡 Publicar este
              </button>
              <button onclick="document.getElementById('ov-llm-preview').style.display='none'"
                class="btn danger" style="flex:1;font-size:0.8rem">Descartar</button>
            </div>
          </div>
          <div id="ov-llm-status" style="font-size:0.75rem;color:var(--muted)"></div>
        </div>
      </div>
      <div>
        <div class="section-title">Historial</div>
        <div style="font-size:0.75rem">
          ${history.length === 0
            ? '<p style="color:var(--muted)">Sin historial</p>'
            : history.slice(0, 30).map(h => `
              <div style="padding:0.35rem 0;border-bottom:1px solid var(--border)">
                <div style="display:flex;align-items:center;gap:0.3rem;flex-wrap:wrap">
                  <span class="badge ${h.action === 'published' ? 'green' : 'red'}" style="font-size:0.6rem">${h.action}</span>
                  <code style="font-size:0.65rem;color:var(--accent)">${h.template_id}</code>
                  <span style="font-size:0.6rem;color:var(--muted)">${h.zone}</span>
                </div>
                <div style="font-size:0.6rem;color:var(--muted)">${h.broadcast_id} · ${h.published_at?.slice(11, 19) || ''}</div>
                <button onclick='republishOverlay(${JSON.stringify({ template_id: h.template_id, zone: h.zone, duration_ms: h.duration_ms, animation: h.animation, data: h.data, broadcast_id: h.broadcast_id })})'
                  class="btn" style="font-size:0.6rem;padding:1px 6px;margin-top:2px">↺</button>
              </div>`).join('')}
        </div>
      </div>
    </div>
  `);

  _ovSelectedTemplate = null;
  _ovLLMCandidate = null;
}

function switchOverlayTab(tab) {
  _ovCurrentTab = tab;
  document.getElementById('ov-tab-templates').style.display = tab === 'templates' ? '' : 'none';
  document.getElementById('ov-tab-llm').style.display = tab === 'llm' ? '' : 'none';
  const tBtn = document.getElementById('tab-templates');
  const lBtn = document.getElementById('tab-llm');
  tBtn.style.background = tab === 'templates' ? 'var(--accent)' : 'none';
  tBtn.style.color = tab === 'templates' ? '#000' : 'var(--muted)';
  lBtn.style.background = tab === 'llm' ? 'var(--accent)' : 'none';
  lBtn.style.color = tab === 'llm' ? '#000' : 'var(--muted)';
}

async function selectOverlayTemplate(templateId) {
  document.querySelectorAll('[id^=tmpl-card-]').forEach(el => {
    el.style.borderColor = 'var(--border)';
    el.style.background = 'var(--surface)';
  });
  const card = document.getElementById(`tmpl-card-${templateId}`);
  if (card) { card.style.borderColor = 'var(--accent)'; card.style.background = 'rgba(79,195,247,0.08)'; }

  _ovSelectedTemplate = templateId;
  const form = document.getElementById('ov-form');
  form.style.display = '';
  document.getElementById('ov-form-title').textContent = templateId;

  try {
    const r = await api(`/admin/overlays/templates/${templateId}`);
    const meta = await r.json();
    const fields = document.getElementById('ov-form-fields');
    const required = meta.vars?.required || [];
    const optional = meta.vars?.optional || [];
    fields.innerHTML = [...required.map(v => `
      <div style="margin-bottom:0.4rem">
        <div style="font-size:0.65rem;color:var(--accent)">* ${v}</div>
        <input id="ov-field-${v}" placeholder="${v}" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:0.8rem"/>
      </div>`),
      ...optional.map(v => `
      <div style="margin-bottom:0.4rem">
        <div style="font-size:0.65rem;color:var(--muted)">${v} (opcional)</div>
        <input id="ov-field-${v}" placeholder="${v}" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:0.8rem"/>
      </div>`),
    ].join('');
  } catch (_) {}
}

function _collectFormData(vars) {
  const data = {};
  for (const v of vars) {
    const el = document.getElementById(`ov-field-${v}`);
    if (el && el.value.trim()) data[v] = el.value.trim();
  }
  return data;
}

async function publishOverlay() {
  const st = document.getElementById('ov-status');
  const broadcastId = document.getElementById('ov-broadcast')?.value;
  const zone = document.getElementById('ov-zone')?.value;
  const durationMs = (parseInt(document.getElementById('ov-duration')?.value || '10') || 0) * 1000;
  if (!_ovSelectedTemplate || !broadcastId) {
    if (st) st.textContent = '⚠ Selecciona un template y un broadcast';
    return;
  }
  if (st) st.textContent = 'Publicando...';
  try {
    const r = await api(`/admin/overlays/templates/${_ovSelectedTemplate}`);
    const meta = await r.json();
    const allVars = [...(meta.vars?.required || []), ...(meta.vars?.optional || [])];
    const data = _collectFormData(allVars);
    const res = await api('/admin/overlays/publish', {
      method: 'POST',
      body: JSON.stringify({
        broadcast_id: broadcastId,
        template_id: _ovSelectedTemplate,
        zone,
        duration_ms: durationMs,
        animation: 'fade',
        data,
      }),
    });
    const d = await res.json();
    if (!res.ok) { if (st) st.textContent = `⚠ ${d.error}`; return; }
    if (st) st.textContent = `✓ Overlay ${d.overlay_id.slice(0, 8)}… publicado`;
    setTimeout(() => loadOverlays(), 800);
  } catch (e) { if (st) st.textContent = 'Error: ' + e.message; }
}

async function unpublishOverlay(overlayId, broadcastId) {
  await api('/admin/overlays/unpublish', { method: 'POST', body: JSON.stringify({ overlay_id: overlayId, broadcast_id: broadcastId }) });
  loadOverlays();
}

async function clearAllOverlays(broadcastId) {
  if (!broadcastId || !confirm(`¿Limpiar todos los overlays de ${broadcastId}?`)) return;
  await api('/admin/overlays/clear-all', { method: 'POST', body: JSON.stringify({ broadcast_id: broadcastId }) });
  loadOverlays();
}

async function republishOverlay(ovData) {
  const broadcastId = document.getElementById('ov-broadcast')?.value || ovData.broadcast_id;
  await api('/admin/overlays/publish', {
    method: 'POST',
    body: JSON.stringify({ ...ovData, broadcast_id: broadcastId }),
  });
  loadOverlays();
}

async function generateLLMOverlay() {
  const st = document.getElementById('ov-llm-status');
  const prompt = document.getElementById('ov-llm-prompt')?.value.trim();
  const zone = document.getElementById('ov-llm-zone')?.value;
  const broadcastId = document.getElementById('ov-broadcast')?.value || '';
  if (!prompt) { if (st) st.textContent = '⚠ Escribe un prompt'; return; }
  if (st) st.textContent = 'Generando...';
  document.getElementById('ov-llm-preview').style.display = 'none';
  try {
    const res = await api('/admin/overlays/generate-llm', {
      method: 'POST',
      body: JSON.stringify({ prompt, zone_hint: zone || 'bottom-bar', broadcast_id: broadcastId }),
    });
    const d = await res.json();
    if (!res.ok) { if (st) st.textContent = `⚠ ${d.error}`; return; }
    _ovLLMCandidate = { ...d.candidate, broadcast_id: broadcastId };
    document.getElementById('ov-llm-json').textContent = JSON.stringify(d.candidate, null, 2);
    document.getElementById('ov-llm-preview').style.display = '';
    if (st) st.textContent = `Confianza: ${Math.round((d.candidate.confidence || 0) * 100)}% · ${d.candidate.explanation || ''}`;
  } catch (e) { if (st) st.textContent = 'Error: ' + e.message; }
}

async function publishLLMCandidate() {
  if (!_ovLLMCandidate) return;
  const broadcastId = _ovLLMCandidate.broadcast_id || document.getElementById('ov-broadcast')?.value || '';
  await api('/admin/overlays/publish', {
    method: 'POST',
    body: JSON.stringify({ ..._ovLLMCandidate, broadcast_id: broadcastId }),
  });
  _ovLLMCandidate = null;
  document.getElementById('ov-llm-preview').style.display = 'none';
  loadOverlays();
}

function previewOverlay() {
  const bc = document.getElementById('ov-broadcast')?.value;
  const zone = document.getElementById('ov-zone')?.value;
  alert(`Vista previa: template "${_ovSelectedTemplate}" en zona "${zone}" del broadcast "${bc}"\n(El preview real requiere el player activo)`);
}

window.unpublishOverlay      = unpublishOverlay;
window.clearAllOverlays      = clearAllOverlays;
window.switchOverlayTab      = switchOverlayTab;
window.selectOverlayTemplate = selectOverlayTemplate;
window.publishOverlay        = publishOverlay;
window.previewOverlay        = previewOverlay;
window.generateLLMOverlay    = generateLLMOverlay;
window.publishLLMCandidate   = publishLLMCandidate;
window.republishOverlay      = republishOverlay;
