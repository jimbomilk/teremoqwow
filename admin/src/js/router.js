import { setCurrentPage } from './store.js';
import { loadBroadcasts } from './pages/broadcasts.js';
import { loadFederation }  from './pages/federation.js';
import { loadDRM }         from './pages/drm.js';
import { loadMonetization } from './pages/monetization.js';
import { loadQoS }         from './pages/qos.js';
import { loadSecurity }    from './pages/security.js';
import { loadFlags }       from './pages/flags.js';
import { loadAudit }       from './pages/audit.js';
import { loadOverlays }    from './pages/overlays.js';

export const pages = {
  broadcasts:   { title: 'Broadcasts',    load: loadBroadcasts },
  federation:   { title: 'Federación',    load: loadFederation },
  drm:          { title: 'DRM / Rights',  load: loadDRM },
  monetization: { title: 'Monetización',  load: loadMonetization },
  qos:          { title: 'QoS',           load: loadQoS },
  security:     { title: 'Seguridad',     load: loadSecurity },
  flags:        { title: 'Feature Flags', load: loadFlags },
  audit:        { title: 'Auditoría',     load: loadAudit },
  overlays:     { title: 'Overlays',      load: loadOverlays },
};

export function setContent(html) {
  document.getElementById('content').innerHTML = html;
}

export function loadPage(page) {
  document.getElementById('content').innerHTML = '<div class="loading">Cargando...</div>';
  Promise.resolve(pages[page].load()).catch(err => {
    if (err.message !== '401') {
      setContent(`<div style="color:var(--red);padding:1rem;font-family:monospace;font-size:0.85rem">Error cargando ${page}: ${err.message}</div>`);
    }
  });
}

let _monitorInterval = null;

export function navigate(el) {
  if (_monitorInterval) { clearInterval(_monitorInterval); _monitorInterval = null; }
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  el.classList.add('active');
  const page = el.dataset.page;
  setCurrentPage(page);
  document.getElementById('page-title').textContent = pages[page].title;
  loadPage(page);
}

export function setMonitorInterval(id) { _monitorInterval = id; }

window.navigate = navigate;
