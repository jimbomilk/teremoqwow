import { api } from '../api.js';
import { setContent, setMonitorInterval } from '../router.js';

export async function loadMonitor() {
  setContent(`
    <div style="display:grid;grid-template-columns:1fr 340px;gap:1.25rem">
      <div>
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.75rem">
          <div class="section-title" style="margin:0">Consumer — stream en vivo</div>
          <select id="mon-broadcast" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.3rem 0.5rem;border-radius:4px;font-size:0.82rem">
            <option value="anon/live1">anon/live1</option>
          </select>
          <button class="btn" onclick="refreshMonitor()">⟳ Reconectar</button>
        </div>
        <div style="background:#000;border-radius:8px;overflow:hidden;aspect-ratio:16/9;position:relative;border:1px solid var(--border)">
          <iframe id="mon-player"
            src="${window.PLAYER_URL || 'http://localhost:5173'}"
            style="width:100%;height:100%;border:none"
            allow="autoplay; camera; microphone"
            sandbox="allow-scripts allow-same-origin allow-forms">
          </iframe>
          <div id="mon-overlay" style="position:absolute;inset:0;background:rgba(0,0,0,0.7);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff">
            <div style="font-size:2rem;margin-bottom:0.5rem">📡</div>
            <div id="mon-status-text" style="font-size:0.9rem;color:var(--muted)">Verificando origen...</div>
          </div>
        </div>
      </div>
      <div>
        <div class="section-title" style="margin-bottom:0.75rem">Estado del origen</div>
        <div class="card" id="mon-source-card">
          <div class="loading" style="padding:1rem 0">Consultando relay...</div>
        </div>
        <div class="section-title" style="margin:1rem 0 0.75rem">Relay</div>
        <div class="card">
          <div class="flag-row" style="border:none;padding:0.4rem 0">
            <span style="font-size:0.82rem;color:var(--muted)">MoQ Relay</span>
            <a href="http://localhost:8090" target="_blank" style="color:var(--accent);font-size:0.82rem">localhost:8090 ↗</a>
          </div>
          <div class="flag-row" style="border:none;padding:0.4rem 0">
            <span style="font-size:0.82rem;color:var(--muted)">Player</span>
            <a href="http://localhost:5173" target="_blank" style="color:var(--accent);font-size:0.82rem">localhost:5173 ↗</a>
          </div>
        </div>
      </div>
    </div>`);
  startMonitorPolling();
}

async function startMonitorPolling() {
  // Clear any previous interval registered via setMonitorInterval
  setMonitorInterval(null);
  await pollMonitorSource();
  setMonitorInterval(setInterval(pollMonitorSource, 3000));
}

async function pollMonitorSource() {
  const broadcast = document.getElementById('mon-broadcast')?.value || 'anon/live1';
  try {
    const r = await api(`/admin/monitor/source?broadcast=${encodeURIComponent(broadcast)}`);
    const d = await r.json();
    const card = document.getElementById('mon-source-card');
    const overlay = document.getElementById('mon-overlay');
    const statusTxt = document.getElementById('mon-status-text');
    if (!card) return;

    if (d.broadcasting) {
      card.innerHTML = `
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem">
          <span style="width:10px;height:10px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 1.5s infinite"></span>
          <span style="color:var(--green);font-weight:600">TRANSMITIENDO</span>
        </div>
        <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.5rem">Broadcast: <code>${d.broadcast}</code></div>
        <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.25rem">Tracks activos:</div>
        ${d.tracks.map(t => `<div style="font-size:0.78rem;padding:2px 0;color:var(--text)">· <code>${t}</code></div>`).join('')}
        <div style="margin-top:0.5rem;font-size:0.75rem;color:var(--muted)">Clock: ${d.has_clock ? '✓ presente' : '—'} · Fuente: ${d.source}</div>`;
      if (overlay) overlay.style.display = 'none';
    } else {
      card.innerHTML = `
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem">
          <span style="width:10px;height:10px;border-radius:50%;background:var(--red);display:inline-block"></span>
          <span style="color:var(--red);font-weight:600">SIN SEÑAL</span>
        </div>
        <div style="font-size:0.82rem;color:var(--muted)">No hay broadcast activo en <code>${d.broadcast}</code></div>
        <div style="margin-top:0.75rem">
          <button class="btn" style="font-size:0.8rem" onclick="injectBroadcast('${d.broadcast}', 4000)">▶ Inyectar stream de prueba</button>
        </div>`;
      if (overlay) { overlay.style.display = 'flex'; if (statusTxt) statusTxt.textContent = 'Sin señal — inyecta un stream primero'; }
    }
  } catch (e) {
    const card = document.getElementById('mon-source-card');
    if (card) card.innerHTML = '<div style="color:var(--red);font-size:0.82rem">Error consultando el relay</div>';
  }
}

function refreshMonitor() {
  const iframe = document.getElementById('mon-player');
  if (iframe) iframe.src = iframe.src;
  pollMonitorSource();
}

window.refreshMonitor = refreshMonitor;
