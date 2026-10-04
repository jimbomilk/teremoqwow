import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadFederation() {
  const r = await api('/admin/federation/nodes');
  const { active, pending } = await r.json();
  setContent(`
    <div class="grid-3">
      <div class="card"><div class="label">Nodos activos</div><div class="value green">${active.length}</div></div>
      <div class="card"><div class="label">Pendientes</div><div class="value yellow">${pending.length}</div></div>
    </div>
    <div class="section-title">Simular nodo externo</div>
    <div class="card" style="max-width:480px;margin-bottom:1rem;display:flex;gap:0.75rem;align-items:flex-end">
      <div style="flex:1"><div style="font-size:0.75rem;color:var(--muted);margin-bottom:4px">Node ID</div>
        <input id="fed-id" placeholder="sim-relay-xxx" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem"/></div>
      <div style="flex:1"><div style="font-size:0.75rem;color:var(--muted);margin-bottom:4px">Región</div>
        <input id="fed-region" value="eu-west-1" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.4rem;border-radius:4px;font-size:0.85rem"/></div>
      <button class="btn" onclick="simulateNode()">+ Simular nodo</button>
    </div>
    <div class="section-title">Nodos pendientes de aprobación</div>
    ${pending.length ? `<table><thead><tr><th>Node ID</th><th>Región</th><th>Sim</th><th>Acción</th></tr></thead><tbody>${
      pending.map(n => `<tr><td>${n.id || '—'}</td><td>${n.region || '—'}</td><td>${n.simulated ? '<span class="badge yellow">sim</span>' : '—'}</td>
      <td><button class="btn" onclick="approveNode('${n.id}')">Aprobar</button>
      <button class="btn danger" onclick="revokeNode('${n.id}')">Revocar</button></td></tr>`).join('')
    }</tbody></table>`
      : '<p style="color:var(--muted);font-size:0.85rem">No hay nodos pendientes</p>'}`);
}

async function approveNode(id) {
  await api(`/admin/federation/nodes/${id}/approve`, { method: 'POST' });
  loadFederation();
}

async function revokeNode(id) {
  await api(`/admin/federation/nodes/${id}/revoke`, { method: 'POST' });
  loadFederation();
}

async function simulateNode() {
  const id     = document.getElementById('fed-id')?.value.trim() || '';
  const region = document.getElementById('fed-region')?.value.trim() || 'eu-west-1';
  const body   = id ? { node_id: id, region } : { region };
  await api('/admin/federation/simulate-node', { method: 'POST', body: JSON.stringify(body) });
  loadFederation();
}

window.approveNode   = approveNode;
window.revokeNode    = revokeNode;
window.simulateNode  = simulateNode;
