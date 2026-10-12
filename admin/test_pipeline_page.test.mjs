// Tests del pipeline.js REAL (no réplicas): sus puertos externos (../api.js, ../router.js, ../store.js)
// se sustituyen por stubs vía un hook de resolución; document/window son dobles mínimos.
// Run: node --test admin/test_pipeline_page.test.mjs
// PIPELINE_PAGE=<ruta a pipeline.js> permite probar una copia mutada (nunca el árbol real).
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';
import { resolve as resolvePath } from 'node:path';

register('./test_pipeline_hooks.mjs', import.meta.url);

const pageUrl = process.env.PIPELINE_PAGE
  ? pathToFileURL(resolvePath(process.env.PIPELINE_PAGE)).href
  : new URL('./src/js/pages/pipeline.js', import.meta.url).href;

// ── harness ─────────────────────────────────────────────────────────────────
const T = '2026-10-12T12:00:00Z';
const SIGS = {
  ingest: ['ingest.video', 'ingest.audio', 'ingest.data'],
  relay: ['relay.public', 'relay.announce', 'relay.catalog', 'relay.tracks'],
  player: ['player.http', 'player.subscribe'],
};
const phase = (id, index, status) => ({
  id, index, title: `Titulo ${id}`,
  transport: { status, own_status: status, reason: `${id} ${status}`, observed_at: T, last_transition_at: T, last_green_at: T, stale: false },
  human: { status: 'NOT_VERIFIED' },
  signals: SIGS[id].map((s) => ({ signal: s, status, freshness: 'FRESH', ttl_seconds: 1200, reason: 'r',
    observed_at: T, last_transition_at: T, last_green_at: T })),
});
const snapshot = (status) => ({ generated_at: T, phases: [phase('ingest', 1, status), phase('relay', 2, status), phase('player', 3, status)] });
const GREEN = snapshot('OK');
const DOWN = snapshot('DOWN');
const HIST = { limit: 50, retention_max_events: 1000, events: [] };
const resp = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

const store = await import('./test_pipeline_stubs/store.mjs');
const state = {};
let page;

function deferred() { let res; const p = new Promise((r) => { res = r; }); return { p, res }; }

function setup() {
  const listeners = [];
  const container = { addEventListener: (type, fn) => listeners.push([type, fn]) };
  const timers = { next: 1, live: new Map() };
  Object.assign(state, {
    container, listeners, timers, calls: [], contents: [], monitor: [], prompts: [], alerts: [],
    handler: (p) => (p.startsWith('/admin/pipeline/status') ? resp(200, GREEN) : resp(200, HIST)),
  });
  globalThis.document = { getElementById: (id) => (id === 'content' ? container : null) };
  globalThis.window = {
    setInterval: (fn, ms) => { const id = timers.next++; timers.live.set(id, { fn, ms }); return id; },
    clearInterval: (id) => { timers.live.delete(id); },
    prompt: (msg) => { state.prompts.push(msg); return 'nota'; },
    alert: (msg) => { state.alerts.push(msg); },
  };
  globalThis.__pp = {
    api: async (path, opts = {}) => { state.calls.push({ path, method: opts.method || 'GET', body: opts.body }); return state.handler(path, opts, state.calls); },
    setContent: (h) => { state.contents.push(h); },
    // igual que router.navigate: setMonitorInterval solo memoriza el id (el router lo limpia al navegar)
    setMonitorInterval: (id) => { state.monitor.push(id); },
  };
  store.setCurrentPage('pipeline');
}

/** Equivale a router.navigate(): limpia el interval registrado y cambia de página. */
function navigateTo(name) {
  const last = state.monitor.at(-1);
  if (last !== undefined) globalThis.window.clearInterval(last);
  store.setCurrentPage(name);
}
const last = () => state.contents.at(-1);
const statusCalls = () => state.calls.filter((c) => c.path === '/admin/pipeline/status').length;
const live = () => state.timers.live;

beforeEach(async () => {
  setup();
  page = await import(pageUrl);
});

// ── comportamiento del módulo real ──────────────────────────────────────────
test('loadPipeline hace GET status (+ historial) y pinta las 3 fases', async () => {
  await page.loadPipeline();
  assert.deepEqual(state.calls.map((c) => c.path), ['/admin/pipeline/status', '/admin/pipeline/history?limit=50']);
  assert.equal(state.contents.length, 1);
  assert.equal((last().match(/data-phase-card=/g) || []).length, 3);
  assert.match(last(), /transport-ok/);
  assert.equal(live().size, 1, 'un único interval de polling');
  assert.equal([...live().values()][0].ms, 30000);
  assert.equal(state.listeners.length, 1, 'un listener de click en #content');
  navigateTo('x');
});

test('un tick del timer vuelve a consultar y a pintar', async () => {
  await page.loadPipeline();
  const before = statusCalls();
  state.handler = (p) => (p.startsWith('/admin/pipeline/status') ? resp(200, DOWN) : resp(200, HIST));
  const [, tick] = [...live().entries()][0];
  await tick.fn();
  assert.equal(statusCalls(), before + 1);
  assert.equal(state.contents.length, 2);
  assert.match(last(), /transport-down/);
  assert.doesNotMatch(last(), /transport-ok/);
  navigateTo('x');
});

test('clic en un botón llama a runAction con data-phase/data-action: POST + recarga', async () => {
  await page.loadPipeline();
  const [, onClick] = state.listeners[0];
  const statusBefore = statusCalls();
  const btn = { dataset: { phase: 'relay', action: 'verify' } };
  await onClick({ target: { closest: () => btn } });
  assert.equal(state.prompts.length, 1);
  const post = state.calls.find((c) => c.method === 'POST');
  assert.equal(post.path, '/admin/pipeline/phases/relay/verification');
  assert.deepEqual(JSON.parse(post.body), { note: 'nota' });
  assert.equal(statusCalls(), statusBefore + 1, 'tras la acción se recarga el estado');
  navigateTo('x');
});

test('revocar → DELETE y recarga', async () => {
  await page.loadPipeline();
  const [, onClick] = state.listeners[0];
  await onClick({ target: { closest: () => ({ dataset: { phase: 'player', action: 'revoke' } }) } });
  const del = state.calls.find((c) => c.method === 'DELETE');
  assert.equal(del.path, '/admin/pipeline/phases/player/verification');
  assert.equal(state.contents.length, 2);
  navigateTo('x');
});

test('navegar fuera detiene el polling: el tick limpia y no consulta ni pinta', async () => {
  await page.loadPipeline();
  const [, tick] = [...live().entries()][0];
  store.setCurrentPage('otra');          // el usuario navega sin que el router haya limpiado aún
  const calls = state.calls.length, paints = state.contents.length;
  await tick.fn();
  assert.equal(state.calls.length, calls);
  assert.equal(state.contents.length, paints);
  assert.equal(live().size, 0, 'el interval se limpia solo');
});

test('un fallo de red en un tick pinta UNKNOWN y luego se recupera (módulo real)', async () => {
  await page.loadPipeline();
  const [, tick] = [...live().entries()][0];
  state.handler = () => { throw new TypeError('Failed to fetch'); };
  await tick.fn();
  assert.match(last(), /sin conexión con admin-api: estado UNKNOWN/i);
  assert.doesNotMatch(last(), /transport-ok/);
  state.handler = (p) => (p.startsWith('/admin/pipeline/status') ? resp(200, GREEN) : resp(200, HIST));
  await tick.fn();
  assert.match(last(), /transport-ok/);
  navigateTo('x');
});

// ── H2: carreras de navegación ──────────────────────────────────────────────
test('A espera historial, se navega fuera y vuelta, B completa DOWN, A termina: no sobrescribe y hay UN interval', async () => {
  const gate = deferred();
  let statusN = 0;
  state.handler = (p) => {
    if (p.startsWith('/admin/pipeline/status')) { statusN++; return resp(200, statusN === 1 ? GREEN : DOWN); }
    return statusN === 1 ? gate.p.then(() => resp(200, HIST)) : resp(200, HIST);
  };
  const a = page.loadPipeline();                       // A: status verde, bloqueada en el historial
  await new Promise((r) => setImmediate(r));
  navigateTo('otra');
  store.setCurrentPage('pipeline');                    // vuelta a Pipeline
  await page.loadPipeline();                           // B completa con DOWN
  assert.match(last(), /transport-down/);
  const paintsB = state.contents.length;
  gate.res();                                          // A termina
  await a;
  assert.equal(state.contents.length, paintsB, 'A caducada no pinta');
  assert.match(last(), /transport-down/);
  assert.doesNotMatch(last(), /transport-ok/);
  assert.equal(live().size, 1, 'un único interval activo (sin duplicar)');
  navigateTo('x');
  assert.equal(live().size, 0);
});

test('cargar dos veces seguidas sin navegar no duplica intervals', async () => {
  await page.loadPipeline();
  await page.loadPipeline();
  assert.equal(live().size, 1);
  navigateTo('x');
  assert.equal(live().size, 0);
});

test('un reload lanzado por una acción de una instancia caducada no pinta', async () => {
  await page.loadPipeline();
  const [, onClick] = state.listeners[0];
  const gate = deferred();
  state.handler = (p, o) => (o && o.method === 'POST' ? gate.p.then(() => resp(200, {})) : resp(200, snapshot('DOWN')));
  const click = onClick({ target: { closest: () => ({ dataset: { phase: 'ingest', action: 'verify' } }) } });
  await new Promise((r) => setImmediate(r));
  navigateTo('otra');
  const paints = state.contents.length;
  gate.res();
  await click;
  assert.equal(state.contents.length, paints);
});

// R2 (ronda 3): la recarga de una acción debe quedar ligada a la generación del CLIC (no a la vigente al recargar,
// ni solo a currentPage). Mata mutantes `reload: () => refresh({... isActive: () => currentPage === 'pipeline'})`
// y `reload: () => reloadFor(generation)()`.
test('acción de A: su recarga recibe snapshot OK y espera el historial; se navega y vuelve; B pinta DOWN; el historial tardío de A no pinta ni deja verde', async () => {
  await page.loadPipeline();                           // A (gen 1)
  const [, onClick] = state.listeners[0];
  const gate = deferred();
  state.handler = (p, o) => {
    if (o && o.method === 'POST') return resp(201, {});
    if (p.startsWith('/admin/pipeline/status')) return resp(200, GREEN);
    return gate.p.then(() => resp(200, HIST));          // historial de la recarga de A: pendiente
  };
  const click = onClick({ target: { closest: () => ({ dataset: { phase: 'ingest', action: 'verify' } }) } });
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  assert.ok(state.calls.some((c) => c.method === 'POST'), 'la acción se ejecutó');
  navigateTo('otra');
  store.setCurrentPage('pipeline');                    // vuelta a Pipeline
  state.handler = (p) => (p.startsWith('/admin/pipeline/status') ? resp(200, DOWN) : resp(200, HIST));
  await page.loadPipeline();                           // B (gen 2) completa con DOWN
  assert.match(last(), /transport-down/);
  const paintsB = state.contents.length;
  gate.res();                                          // el historial de la recarga de A llega tarde
  await click;
  assert.equal(state.contents.length, paintsB, 'cero pintados adicionales');
  assert.match(last(), /transport-down/);
  assert.doesNotMatch(last(), /transport-ok/);
  navigateTo('x');
});

// R2 variante: el POST de A termina DESPUÉS de que B ya cargó; la recarga se lanza tarde y debe seguir ligada a la
// generación del clic (mata `reload: () => reloadFor(generation)()`, que evaluaría la generación vigente al recargar).
test('acción de A cuyo POST termina tras volver a Pipeline y cargar B: su recarga tardía (snapshot OK) no pinta', async () => {
  await page.loadPipeline();                           // A
  const [, onClick] = state.listeners[0];
  const gate = deferred();
  state.handler = (p, o) => (o && o.method === 'POST' ? gate.p.then(() => resp(201, {})) : resp(200, DOWN));
  const click = onClick({ target: { closest: () => ({ dataset: { phase: 'ingest', action: 'verify' } }) } });
  await new Promise((r) => setImmediate(r));
  navigateTo('otra');
  store.setCurrentPage('pipeline');
  await page.loadPipeline();                           // B pinta DOWN
  assert.match(last(), /transport-down/);
  const paintsB = state.contents.length;
  state.handler = (p, o) => (o && o.method === 'POST' ? resp(201, {})
    : p.startsWith('/admin/pipeline/status') ? resp(200, GREEN) : resp(200, HIST));  // la recarga de A vería verde
  gate.res();
  await click;
  assert.ok(state.calls.some((c) => c.path === '/admin/pipeline/status'), 'la recarga tardía sí consultó');
  assert.equal(state.contents.length, paintsB, 'cero pintados adicionales');
  assert.doesNotMatch(last(), /transport-ok/);
  navigateTo('x');
});
