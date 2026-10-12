// Deadlines de refresh/runAction/polling (R1 ronda 3) con timers falsos inyectados.
// Run: node --test admin/test_pipeline_actions.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { refresh, runAction, startPolling, REQUEST_TIMEOUT_MS } from './src/js/pages/pipeline-actions.js';

const T = '2026-10-12T12:00:00Z';
const SIGS = { ingest: ['ingest.video', 'ingest.audio', 'ingest.data'],
  relay: ['relay.public', 'relay.announce', 'relay.catalog', 'relay.tracks'], player: ['player.http', 'player.subscribe'] };
const phase = (id, index, status) => ({ id, index, title: id,
  transport: { status, own_status: status, reason: 'r', observed_at: T, last_transition_at: T, last_green_at: T, stale: false },
  human: { status: 'NOT_VERIFIED' },
  signals: SIGS[id].map((s) => ({ signal: s, status, freshness: 'FRESH', ttl_seconds: 1200, reason: 'r',
    observed_at: T, last_transition_at: T, last_green_at: T })) });
const GREEN = { generated_at: T, phases: [phase('ingest', 1, 'OK'), phase('relay', 2, 'OK'), phase('player', 3, 'OK')] };
const HIST = { limit: 50, retention_max_events: 1000, events: [] };
const resp = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const never = () => new Promise(() => {});
const tick = () => new Promise((r) => setImmediate(r));

function fakeTimers() {
  let next = 1; const live = new Map(); const set = [];
  return {
    live, set,
    setTimeout: (fn, ms) => { const id = next++; live.set(id, fn); set.push(ms); return id; },
    clearTimeout: (id) => { live.delete(id); },
    fire: () => { for (const [id, fn] of [...live]) { live.delete(id); fn(); } },
  };
}
const router = (h) => (p, o) => h(p, o);
const isStatus = (p) => p.startsWith('/admin/pipeline/status');

async function run(promise, timers) { await tick(); timers.fire(); return promise; }

test('el deadline por defecto es 15 s y se exporta', async () => {
  assert.equal(REQUEST_TIMEOUT_MS, 15000);
  const t = fakeTimers();
  await refresh({ api: async (p) => resp(200, isStatus(p) ? GREEN : HIST), setContent() {}, isActive: () => true, timers: t });
  assert.deepEqual(t.set, [15000, 15000]);
});

test('status que nunca resuelve → UNKNOWN tras el deadline, sin verde, sin timers colgados; y luego se recupera', async () => {
  const t = fakeTimers(); const painted = []; let hang = true; let seenSignal;
  const api = async (p, o) => { if (hang) { seenSignal = o && o.signal; return never(); } return resp(200, isStatus(p) ? GREEN : HIST); };
  const out = await run(refresh({ api, setContent: (h) => painted.push(h), isActive: () => true, timers: t }), t);
  assert.deepEqual(out, { painted: true });
  assert.match(painted.at(-1), /sin conexión con admin-api: estado UNKNOWN/i);
  assert.doesNotMatch(painted.at(-1), /transport-ok/);
  assert.equal(seenSignal.aborted, true, 'la petición se aborta vía AbortSignal');
  assert.equal(t.live.size, 0);
  hang = false;
  await refresh({ api, setContent: (h) => painted.push(h), isActive: () => true, timers: t });
  assert.match(painted.at(-1), /transport-ok/);
  assert.equal(t.live.size, 0);
});

test('res.json() pendiente en status → UNKNOWN tras el deadline', async () => {
  const t = fakeTimers(); const painted = [];
  const api = async () => ({ ok: true, status: 200, json: never });
  await run(refresh({ api, setContent: (h) => painted.push(h), isActive: () => true, timers: t }), t);
  assert.match(painted.at(-1), /sin conexión con admin-api: estado UNKNOWN/i);
  assert.doesNotMatch(painted.at(-1), /transport-ok/);
  assert.equal(t.live.size, 0);
});

test('historial pendiente → se pinta el snapshot fresco + aviso "Historial no disponible"; sin timers colgados', async () => {
  const t = fakeTimers(); const painted = [];
  const api = async (p) => (isStatus(p) ? resp(200, GREEN) : never());
  await run(refresh({ api, setContent: (h) => painted.push(h), isActive: () => true, timers: t }), t);
  assert.equal(painted.length, 1);
  assert.match(painted[0], /transport-ok/);
  assert.match(painted[0], /Historial no disponible/);
  assert.equal(t.live.size, 0);
});

test('historial que falla (HTTP 500) también avisa; con historial OK no hay aviso', async () => {
  const t = fakeTimers(); const painted = [];
  await refresh({ api: async (p) => (isStatus(p) ? resp(200, GREEN) : resp(500, {})), setContent: (h) => painted.push(h), isActive: () => true, timers: t });
  assert.match(painted[0], /Historial no disponible/);
  await refresh({ api: async (p) => resp(200, isStatus(p) ? GREEN : HIST), setContent: (h) => painted.push(h), isActive: () => true, timers: t });
  assert.doesNotMatch(painted[1], /Historial no disponible/);
});

test('deadline que ignora la señal: Promise.race garantiza igualmente la resolución', async () => {
  const t = fakeTimers(); const painted = [];
  const api = () => never(); // no mira opts.signal
  const out = await run(refresh({ api, setContent: (h) => painted.push(h), isActive: () => true, timers: t }), t);
  assert.equal(out.painted, true);
});

test('un 401 sigue propagándose y limpia el timer', async () => {
  const t = fakeTimers();
  await assert.rejects(refresh({ api: async () => { throw new Error('401'); }, setContent() {}, isActive: () => true, timers: t }), /401/);
  assert.equal(t.live.size, 0);
});

test('acción pendiente: error claro de timeout, recarga, sin éxito falso, sin timers colgados', async () => {
  const t = fakeTimers(); const notes = []; let reloaded = 0;
  const p = runAction({ api: () => never(), phase: 'ingest', action: 'verify', askNote: () => 'n',
    notify: (m) => notes.push(m), reload: async () => { reloaded++; }, timers: t });
  const out = await run(p, t);
  assert.equal(out.ok, false); assert.equal(out.timeout, true);
  assert.equal(notes.length, 1);
  assert.match(notes[0], /Tiempo de espera agotado/);
  assert.equal(reloaded, 1);
  assert.equal(t.live.size, 0);
});

test('acción con cuerpo de error pendiente (res.json nunca resuelve) también vence', async () => {
  const t = fakeTimers(); const notes = [];
  const api = async () => ({ ok: false, status: 409, json: never });
  const out = await run(runAction({ api, phase: 'relay', action: 'revoke', askNote: () => '', notify: (m) => notes.push(m),
    reload: async () => {}, timers: t }), t);
  assert.equal(out.timeout, true);
  assert.match(notes[0], /Tiempo de espera agotado/);
});

test('acción OK y acción con error normal limpian su timer y no notifican timeout', async () => {
  const t = fakeTimers(); const notes = [];
  const ok = await runAction({ api: async () => resp(201, {}), phase: 'ingest', action: 'verify', askNote: () => '', notify: (m) => notes.push(m), reload: async () => {}, timers: t });
  assert.deepEqual(ok, { ok: true });
  const bad = await runAction({ api: async () => resp(403, {}), phase: 'ingest', action: 'verify', askNote: () => '', notify: (m) => notes.push(m), reload: async () => {}, timers: t });
  assert.equal(bad.status, 403);
  assert.equal(notes.length, 1);
  assert.doesNotMatch(notes[0], /espera/);
  assert.equal(t.live.size, 0);
});

test('polling: un status colgado libera busy y el siguiente tick se recupera', async () => {
  const t = fakeTimers(); const painted = []; let hang = true; const intervals = [];
  const api = async (p) => (hang ? never() : resp(200, isStatus(p) ? GREEN : HIST));
  const doRefresh = () => refresh({ api, setContent: (h) => painted.push(h), isActive: () => true, timers: t });
  startPolling({ refresh: doRefresh, isActive: () => true, setInterval: (fn) => { intervals.push(fn); return 1; },
    clearInterval() {}, setMonitorInterval() {}, ms: 30000 });
  const first = intervals[0]();
  await tick(); t.fire(); await first;
  assert.match(painted.at(-1), /sin conexión con admin-api/i);
  hang = false;
  await intervals[0]();
  assert.match(painted.at(-1), /transport-ok/, 'busy se liberó: el segundo tick no fue ignorado');
  assert.equal(t.live.size, 0);
});
