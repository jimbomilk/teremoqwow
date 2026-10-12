/**
 * Lógica de acciones/refresh/polling de la vista Pipeline (#214), sin DOM ni globals de navegador.
 * Todo lo externo (api, setContent, timers, prompt) se inyecta, para probarlo con node:test.
 */
import { renderPipeline, renderHistory, escapeHtml, PHASE_ORDER, UNREACHABLE_CODE } from './pipeline-render.js';

export const HISTORY_LIMIT = 50;
export const POLL_MS = 30000;
const ACTIONS = {
  verify: { method: 'POST', field: 'note' },
  revoke: { method: 'DELETE', field: 'reason' },
};

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

async function readJson(res) {
  try { return await res.json(); } catch { return undefined; }
}

/** Mensaje humano para un error HTTP de las acciones. */
export function describeError(status, body) {
  const code = isObj(body) ? body.code : undefined;
  if (status === 401) return 'Sesión caducada o no válida: vuelve a iniciar sesión.';
  if (status === 403) return 'No tienes permiso para esta acción (se requiere rol de operador).';
  if (status === 404) return 'La fase no existe (PHASE_NOT_FOUND).';
  if (status === 409 && code === 'NOT_VERIFIED') return 'La fase no está verificada: nada que revocar.';
  if (status === 409 && code === 'ALREADY_VERIFIED') return 'La fase ya está verificada.';
  if (status === 409) return 'Conflicto: otra operación en curso sobre la fase; reintenta.';
  if (status === 503) return 'Redis no disponible: no se pudo completar la acción; el estado es desconocido.';
  if (status === 400) {
    return `Petición rechazada: ${isObj(body) && body.message ? body.message : 'datos no válidos'}.`;
  }
  return `Error inesperado del servidor (HTTP ${status}).`;
}

/**
 * Verificar/Revocar una fase. El body lleva SOLO {note} / {reason}: operador y fecha los pone el servidor.
 * Nunca lanza: devuelve {ok, cancelled?}. Tras actuar (también si falló) recarga, salvo en 401.
 */
export async function runAction({ api, phase, action, askNote, notify, reload }) {
  const spec = Object.prototype.hasOwnProperty.call(ACTIONS, action) ? ACTIONS[action] : null;
  if (!spec || !PHASE_ORDER.includes(phase)) return { ok: false, invalid: true };

  const text = askNote(action);
  if (text === null || text === undefined) return { ok: false, cancelled: true };
  const body = {};
  if (typeof text === 'string' && text.trim() !== '') body[spec.field] = text;

  let result;
  try {
    const res = await api(`/admin/pipeline/phases/${phase}/verification`, {
      method: spec.method, body: JSON.stringify(body),
    });
    if (res.ok) {
      result = { ok: true };
    } else {
      notify(describeError(res.status, await readJson(res)));
      result = { ok: false, status: res.status };
    }
  } catch (err) {
    const unauthorized = err && err.message === '401';
    notify(unauthorized ? describeError(401) : `No se pudo contactar con el servidor: ${err && err.message}`);
    if (unauthorized) return { ok: false, status: 401 };
    result = { ok: false, network: true };
  }
  try { await reload(); } catch { /* el siguiente ciclo de polling reintenta */ }
  return result;
}

/** Delegación de clicks: UN listener por contenedor (aunque se llame varias veces). */
const attached = new WeakSet();
export function attachClicks(container, onAction) {
  if (!container || typeof container.addEventListener !== 'function' || attached.has(container)) return false;
  attached.add(container);
  container.addEventListener('click', (e) => {
    const target = e && e.target;
    const btn = target && typeof target.closest === 'function'
      ? target.closest('button[data-phase][data-action]') : null;
    if (!btn || !btn.dataset) return undefined;
    return onAction(btn.dataset.phase, btn.dataset.action);
  });
  return true;
}

/**
 * Pide estado (+ historial si el estado respondió 200) y pinta si `isActive()` sigue siendo true.
 * Propaga Error('401') (lo gestiona api()/router). Cualquier otro fallo (red caída, respuesta no JSON,
 * HTTP distinto de 200 y del 503 REDIS_UNAVAILABLE conocido) se pinta como estado UNKNOWN honesto:
 * nunca se conserva el HTML anterior.
 */
export async function refresh({ api, setContent, isActive }) {
  const unreachable = (message) => ({ code: UNREACHABLE_CODE, message });
  let data = null;
  let error = null;
  let history = null;

  try {
    const res = await api('/admin/pipeline/status');
    if (res.ok) {
      data = await readJson(res);
      if (!isObj(data)) { data = null; error = unreachable('Respuesta de estado no válida'); }
    } else {
      const body = res.status === 503 ? await readJson(res) : undefined;
      error = isObj(body) && body.code === 'REDIS_UNAVAILABLE'
        ? body : unreachable(`Respuesta inesperada del servidor (HTTP ${res.status})`);
    }
  } catch (err) {
    if (err && err.message === '401') throw err;
    data = null;
    error = unreachable(`Sin conexión: ${err && err.message}`);
  }

  if (data) {
    try {
      const h = await api(`/admin/pipeline/history?limit=${HISTORY_LIMIT}`);
      if (h.ok) history = await readJson(h);
    } catch (err) {
      if (err && err.message === '401') throw err;
      history = null; // el historial es secundario: se omite sin romper el estado
    }
  }

  if (!isActive()) return { painted: false };
  setContent(renderPipeline(data, error) + (data && history ? renderHistory(history) : ''));
  return { painted: true };
}

/** Registra UN interval; cada tick: no solapa, se limpia si la página ya no está activa, nunca rechaza. */
export function startPolling({ refresh: doRefresh, isActive, setInterval, clearInterval, setMonitorInterval, ms = POLL_MS }) {
  let busy = false;
  const id = setInterval(async () => {
    if (!isActive()) { clearInterval(id); return; }
    if (busy) return;
    busy = true;
    try { await doRefresh(); } catch { /* 401/red: el siguiente tick reintenta; 401 lo gestiona auth */ } finally { busy = false; }
  }, ms);
  setMonitorInterval(id);
  return id;
}

export { escapeHtml };
