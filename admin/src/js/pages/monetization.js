import { api } from '../api.js';
import { setContent } from '../router.js';

export async function loadMonetization() {
  const [statsR, eventsR] = await Promise.all([
    api('/admin/monetization/stats'),
    api('/admin/monetization/events'),
  ]);
  const stats = await statsR.json();
  const events = await eventsR.json();
  const eRows = events.map(e => `<tr><td><code>${e.id}</code></td><td>${e.type}</td>
    <td>${e.data?.object?.amount_paid ? (e.data.object.amount_paid / 100).toFixed(2) + ' ' + e.data.object.currency.toUpperCase() : '—'}</td>
    <td>${new Date(e.created * 1000).toLocaleString()}</td></tr>`).join('');
  setContent(`
    <div class="grid-3">
      <div class="card"><div class="label">MRR</div><div class="value green">${(stats.mrr_eur / 100).toFixed(2)} €</div></div>
      <div class="card"><div class="label">Suscripciones activas</div><div class="value">${stats.active_subscriptions}</div></div>
      <div class="card"><div class="label">Churn</div><div class="value yellow">${stats.churn_rate_pct || 0}%</div></div>
      <div class="card"><div class="label">Dunning</div><div class="value ${stats.dunning_count > 0 ? 'red' : ''}">${stats.dunning_count || 0}</div></div>
    </div>
    <div class="section-title">Últimos eventos Stripe ${stats.source === 'mock' ? '(mock)' : ''}</div>
    <table><thead><tr><th>ID</th><th>Tipo</th><th>Importe</th><th>Fecha</th></tr></thead><tbody>${eRows}</tbody></table>`);
}
