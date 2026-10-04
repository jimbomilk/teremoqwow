import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadFlags() {
  const r = await api('/admin/flags');
  const flags = await r.json();
  const rows = Object.entries(flags).map(([k, v]) => `
    <div class="flag-row">
      <span>${k.replace(/_/g, ' ')}</span>
      <label class="toggle">
        <input type="checkbox" ${v ? 'checked' : ''} onchange="setFlag('${k}',this.checked)" />
        <span class="slider"></span>
      </label>
    </div>`).join('');
  setContent(`<div class="section-title">Feature Flags globales</div><div class="card" style="max-width:500px">${rows}</div>`);
}

async function setFlag(flag, enabled) {
  await api(`/admin/flags/${flag}`, { method: 'PATCH', body: JSON.stringify({ enabled }) });
}

window.setFlag = setFlag;
