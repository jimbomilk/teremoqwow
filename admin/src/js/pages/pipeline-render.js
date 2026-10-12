/**
 * Render PURO de la vista Pipeline (#214): datos → string HTML.
 *
 * Sin acceso a document/window/red y sin imports, para poder probarlo con node:test.
 * Toda cadena que viene del servidor se escapa con escapeHtml; los únicos valores
 * interpolados en atributos/clases salen de listas blancas fijas, nunca del dato.
 *
 * La máquina solo afirma llegada de datos; la calidad audiovisual la valida una persona.
 */

export const PHASE_ORDER = ['ingest', 'relay', 'player'];
/** Código (cliente) de "sin respuesta utilizable de admin-api": red caída, no-JSON o HTTP inesperado. */
export const UNREACHABLE_CODE = 'ADMIN_API_UNREACHABLE';
const PHASE_TITLES = {
  ingest: 'Ingesta de vídeo/audio/data',
  relay: 'MoQ + relay',
  player: 'Player + visualización',
};
const TRANSPORT_STATES = ['OK', 'DEGRADED', 'DOWN', 'BLOCKED', 'UNKNOWN'];
const HUMAN_STATES = ['VERIFIED', 'NOT_VERIFIED'];
const EVENT_TYPES = ['TRANSITION', 'HUMAN_VERIFIED', 'HUMAN_REVOKED'];
const METRIC_LABELS = [
  ['bytes', 'bytes'], ['objects', 'objetos'], ['window_seconds', 'ventana (s)'], ['http_status', 'HTTP'],
];

export const DISCLAIMER =
  'La máquina solo verifica llegada de datos; la calidad audiovisual la valida una persona.';

export function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

/** RFC 3339 → 'YYYY-MM-DD HH:MM:SS UTC' (determinista, independiente de la zona local). */
export function formatTime(iso) {
  if (typeof iso !== 'string' || !RFC3339.test(iso)) return '—';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return '—';
  return `${new Date(ms).toISOString().slice(0, 19).replace('T', ' ')} UTC`;
}

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const pick = (value, allowed, fallback) => (allowed.includes(value) ? value : fallback);

function metricsHtml(metrics) {
  if (!isObj(metrics)) return '';
  const parts = [];
  for (const [key, label] of METRIC_LABELS) {
    const v = metrics[key];
    if (typeof v === 'number' && Number.isFinite(v)) parts.push(`${label} ${v}`);
  }
  return parts.length ? `<span class="sig-metrics">${escapeHtml(parts.join(' · '))}</span>` : '';
}

function signalHtml(sig) {
  if (!isObj(sig)) return '';
  const stale = sig.freshness === 'STALE';
  const key = stale ? 'stale' : pick(sig.status, TRANSPORT_STATES, 'UNKNOWN').toLowerCase();
  const text = stale ? 'caducada' : pick(sig.status, TRANSPORT_STATES, 'UNKNOWN');
  const never = !stale && sig.freshness === 'NEVER' ? ' <em>(sin datos)</em>' : '';
  return `<li class="signal sig-${key}"><span class="sig-name">${escapeHtml(sig.signal)}</span> `
    + `<span class="sig-text">${text}</span>${never} `
    + `<span class="sig-reason">${escapeHtml(sig.reason)}</span> `
    + `<span class="sig-time">obs. ${formatTime(sig.observed_at)} · último OK ${formatTime(sig.last_green_at)}</span> `
    + `${metricsHtml(sig.metrics)}</li>`;
}

function humanHtml(id, human, known) {
  if (!known) {
    return '<div class="human"><span class="badge human-unknown">desconocida</span> '
      + '<span class="muted">Verificación humana desconocida (sin acceso al estado)</span></div>';
  }
  const h = isObj(human) ? human : {};
  const status = pick(h.status, HUMAN_STATES, 'NOT_VERIFIED');
  let out = `<div class="human"><span class="badge human-${status.toLowerCase()}">${status}</span> `;
  if (status === 'VERIFIED') {
    out += `<span class="muted">por ${escapeHtml(h.verified_by)} · ${formatTime(h.verified_at)}</span>`;
    if (h.note) out += ` <span class="human-note">“${escapeHtml(h.note)}”</span>`;
    out += ` <button class="btn btn-revoke" data-phase="${id}" data-action="revoke">Revocar</button>`;
  } else {
    if (h.last_revoked_by) {
      out += `<span class="muted">revocada por ${escapeHtml(h.last_revoked_by)} · ${formatTime(h.last_revoked_at)}</span> `;
    }
    out += `<button class="btn btn-verify" data-phase="${id}" data-action="verify">Verificar</button>`;
  }
  return `${out}</div>`;
}

function phaseHtml(id, p, known) {
  const real = isObj(p);
  const t = real && isObj(p.transport) ? p.transport : {};
  const status = pick(t.status, TRANSPORT_STATES, 'UNKNOWN');
  const signals = real && Array.isArray(p.signals) ? p.signals : [];
  const staleSignals = signals.some((s) => isObj(s) && s.freshness === 'STALE');
  const stale = t.stale === true || (status === 'UNKNOWN' && staleSignals);
  const title = real && p.title ? p.title : PHASE_TITLES[id];

  let body = `<section class="phase-card" data-phase-card="${id}">`;
  body += `<h3>${PHASE_ORDER.indexOf(id) + 1}. ${escapeHtml(title)} `
    + `<span class="badge transport-${status.toLowerCase()}">${status}</span></h3>`;
  if (!real) {
    body += '<div class="reason muted">Sin datos de esta fase</div>';
  } else {
    body += `<div class="reason">${escapeHtml(t.reason)}</div>`;
    if (status === 'BLOCKED') {
      body += `<div class="detail">Bloqueada por: <strong>${escapeHtml(t.blocked_by)}</strong> · `
        + `Estado propio: <strong>${escapeHtml(t.own_status)}</strong></div>`;
    }
    if (stale) {
      body += '<div class="stale-note">Observación caducada: sin datos recientes (no es un fallo confirmado).</div>';
    }
    body += `<div class="detail muted">Última observación ${formatTime(t.observed_at)} · `
      + `cambio de estado ${formatTime(t.last_transition_at)} · último OK ${formatTime(t.last_green_at)}</div>`;
  }
  if (signals.length) body += `<ul class="signals">${signals.map(signalHtml).join('')}</ul>`;
  body += humanHtml(id, real ? p.human : null, known && real);
  return `${body}</section>`;
}

function banner(text, cls) {
  return `<div class="pipeline-banner ${cls}">${escapeHtml(text)}</div>`;
}

/**
 * @param {object|null} data  snapshot (pipeline-snapshot.json) o null
 * @param {object|null} error envelope de error (common/v1/error.json) o null
 */
export function renderPipeline(data, error) {
  const disclaimer = `<p class="pipeline-disclaimer">${escapeHtml(DISCLAIMER)}</p>`;
  let notice = '';
  let known = true;
  let phases = [];

  if (isObj(error) && error.code === UNREACHABLE_CODE) {
    // Sin respuesta utilizable de admin-api: NO se conserva ni se infiere nada; todo UNKNOWN.
    known = false;
    notice = banner('Sin conexión con admin-api: estado UNKNOWN (no es verde). Se reintentará automáticamente.', 'warn');
  } else if (isObj(error)) {
    const unavailable = error.code === 'REDIS_UNAVAILABLE'
      || (isObj(error.details) && error.details.status === 'UNKNOWN');
    if (!unavailable) {
      return `<div class="pipeline-container">${disclaimer}`
        + `<div class="pipeline-error">Error: ${escapeHtml(error.code)} — ${escapeHtml(error.message)}</div></div>`;
    }
    known = false;
    notice = banner('Redis no disponible: el estado de las fases es desconocido (no es verde).', 'warn');
  } else if (isObj(data) && Array.isArray(data.phases)) {
    phases = data.phases;
  }

  const cards = PHASE_ORDER.map((id) => {
    const p = known ? phases.find((x) => isObj(x) && x.id === id) : null;
    return phaseHtml(id, p, known);
  });
  const stamp = known && isObj(data) && data.generated_at
    ? `<div class="muted generated">Generado ${formatTime(data.generated_at)}</div>` : '';
  return `<div class="pipeline-container">${disclaimer}${notice}${stamp}${cards.join('')}</div>`;
}

/** @param {{events:Array}|null} history respuesta de GET /admin/pipeline/history */
export function renderHistory(history) {
  const events = isObj(history) && Array.isArray(history.events) ? history.events.filter(isObj) : [];
  if (!events.length) {
    return '<section class="pipeline-history"><h3>Historial de eventos</h3><p class="muted">Sin eventos</p></section>';
  }
  const rows = events.map((e) => {
    const type = EVENT_TYPES.includes(e.type) ? e.type : '—';
    const change = e.from_status || e.to_status
      ? `${escapeHtml(e.from_status) || '—'} → ${escapeHtml(e.to_status) || '—'}` : '';
    const detail = e.type === 'HUMAN_REVOKED' ? e.reason : (e.note || e.reason);
    return `<tr class="ev ev-${type.toLowerCase()}"><td>${formatTime(e.at)}</td><td>${type}</td>`
      + `<td>${escapeHtml(e.phase)}</td><td>${change}</td><td>${escapeHtml(e.actor)}</td>`
      + `<td>${escapeHtml(detail)}</td></tr>`;
  });
  return '<section class="pipeline-history"><h3>Historial de eventos</h3><table class="history">'
    + '<thead><tr><th>Cuándo</th><th>Tipo</th><th>Fase</th><th>Cambio</th><th>Actor</th><th>Detalle</th></tr></thead>'
    + `<tbody>${rows.join('')}</tbody></table></section>`;
}
