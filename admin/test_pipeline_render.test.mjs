// Tests de la UI Pipeline (#214). Sin DOM real ni dependencias: node:test + contenedor falso.
// Run: node --test admin/test_pipeline_render.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  renderPipeline, renderHistory, escapeHtml, formatTime,
} from './src/js/pages/pipeline-render.js';
import {
  describeError, runAction, refresh, attachClicks, startPolling,
} from './src/js/pages/pipeline-actions.js';

// ── fixtures ────────────────────────────────────────────────────────────────
const T = '2026-10-12T12:00:00Z';
const SIGS = {
  ingest: ['ingest.video', 'ingest.audio', 'ingest.data'],
  relay: ['relay.public', 'relay.announce', 'relay.catalog', 'relay.tracks'],
  player: ['player.http', 'player.manifest', 'player.segments'],
};
const sig = (name, status = 'OK', extra = {}) => ({
  signal: name, status, freshness: status === 'UNKNOWN' ? 'NEVER' : 'FRESH', ttl_seconds: 1200,
  reason: `${name} reason`, observed_at: T, last_transition_at: T, last_green_at: T, ...extra,
});
function phase(id, index, status = 'OK', over = {}) {
  const { transport = {}, human = { status: 'NOT_VERIFIED' }, signals } = over;
  return {
    id, index, title: `Titulo ${id}`,
    transport: { status, own_status: status, reason: `${id} ${status}`, observed_at: T,
      last_transition_at: T, last_green_at: T, stale: false, ...transport },
    human,
    signals: signals ?? SIGS[id].map((s) => sig(s)),
  };
}
const snap = (overrides = {}) => ({
  generated_at: T,
  phases: [phase('ingest', 1), phase('relay', 2), phase('player', 3)],
  ...overrides,
});
const html = (d, e = null) => renderPipeline(d, e);
// Trozo de HTML de una fase concreta (cada fase vive en <section data-phase-card="id">).
function card(out, id) {
  const m = out.match(new RegExp(`<section[^>]*data-phase-card="${id}"[\\s\\S]*?</section>`));
  assert.ok(m, `no hay tarjeta para ${id}`);
  return m[0];
}
const transportBadge = (c) => c.match(/<span class="badge transport-([a-z]+)"[^>]*>([^<]*)<\/span>/);

// ── pureza ──────────────────────────────────────────────────────────────────
test('pipeline-render.js es puro: sin document/window/imports ni globals de navegador', () => {
  const src = readFileSync(new URL('./src/js/pages/pipeline-render.js', import.meta.url), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  assert.equal(/\b(document|window|localStorage|navigator|fetch|location)\b/.test(code), false);
  assert.equal(/^\s*import\s/m.test(code), false);
  assert.equal(/toLocale/.test(code), false, 'formateo no determinista');
  assert.equal(/\bonclick\b/i.test(code), false);
});

test('el módulo se importa y ejecuta en Node sin DOM (globalThis sin document/window)', () => {
  assert.equal(typeof globalThis.document, 'undefined');
  assert.equal(typeof globalThis.window, 'undefined');
  assert.equal(typeof html(snap()), 'string');
});

// ── 5 estados de transporte ─────────────────────────────────────────────────
test('los 5 estados de transporte se renderizan con texto y clase distintos', () => {
  const seen = new Map();
  for (const st of ['OK', 'DEGRADED', 'DOWN', 'BLOCKED', 'UNKNOWN']) {
    const extra = st === 'BLOCKED' ? { blocked_by: 'ingest' } : {};
    const out = html(snap({ phases: [phase('ingest', 1, st, { transport: extra }), phase('relay', 2), phase('player', 3)] }));
    const b = transportBadge(card(out, 'ingest'));
    assert.ok(b, `badge de transporte para ${st}`);
    assert.equal(b[1], st.toLowerCase());
    assert.match(b[2], new RegExp(st));
    seen.set(st, `${b[1]}|${b[2]}`);
  }
  assert.equal(new Set(seen.values()).size, 5);
});

test('el estado humano VERIFIED/NOT_VERIFIED va aparte (otra clase) y no mezcla con transporte', () => {
  const v = html(snap({ phases: [phase('ingest', 1, 'OK', { human: { status: 'VERIFIED', verified_by: 'ana@x.io', verified_at: T, note: 'se ve bien' } }), phase('relay', 2), phase('player', 3)] }));
  const c = card(v, 'ingest');
  assert.match(c, /class="badge human-verified"[^>]*>[^<]*VERIFIED/);
  assert.match(c, /ana@x\.io/);
  assert.match(c, /se ve bien/);
  assert.match(c, /data-action="revoke"/);
  assert.doesNotMatch(c, /data-action="verify"/);
  const n = card(v, 'relay');
  assert.match(n, /class="badge human-not_verified"[^>]*>[^<]*NOT_VERIFIED/);
  assert.match(n, /data-action="verify"/);
  assert.doesNotMatch(n, /data-action="revoke"/);
  // las clases human-* nunca se usan para transporte y viceversa
  assert.doesNotMatch(transportBadge(c)[0], /human-/);
});

test('texto fijo: la máquina solo verifica llegada de datos; la calidad la valida una persona', () => {
  const t = 'la máquina solo verifica llegada de datos; la calidad audiovisual la valida una persona';
  assert.ok(html(snap()).toLowerCase().includes(t));
  assert.ok(html(null, { code: 'REDIS_UNAVAILABLE', message: 'x', details: { status: 'UNKNOWN' } }).toLowerCase().includes(t));
});

// ── stale / blocked / degraded ──────────────────────────────────────────────
test('STALE ≠ DOWN: fase UNKNOWN caducada muestra "caducada" y no DOWN; DOWN real no dice caducada', () => {
  const stale = snap({ phases: [
    phase('ingest', 1, 'UNKNOWN', { transport: { stale: true, reason: 'señales caducadas' },
      signals: SIGS.ingest.map((s) => sig(s, 'UNKNOWN', { freshness: 'STALE' })) }),
    phase('relay', 2), phase('player', 3)] });
  const c = card(html(stale), 'ingest');
  assert.match(c, /class="stale-note"/);
  assert.match(transportBadge(c)[1], /unknown/);
  assert.doesNotMatch(c, /transport-down/);
  assert.match(c, /caducada/i);
  assert.equal((c.match(/class="signal [^"]*sig-stale/g) || []).length, 3);

  const down = snap({ phases: [
    phase('ingest', 1, 'DOWN', { signals: [sig('ingest.video', 'DOWN'), sig('ingest.audio'), sig('ingest.data')] }),
    phase('relay', 2), phase('player', 3)] });
  const d = card(html(down), 'ingest');
  assert.match(transportBadge(d)[1], /down/);
  assert.doesNotMatch(d, /caducada/i);
  assert.doesNotMatch(d, /stale-note/);
  assert.doesNotMatch(d, /sig-stale/);
});

test('una señal STALE en fase DEGRADED se marca caducada sin pintar la fase como caducada', () => {
  const s = snap({ phases: [
    phase('ingest', 1, 'DEGRADED', { signals: [sig('ingest.video'), sig('ingest.audio'), sig('ingest.data', 'UNKNOWN', { freshness: 'STALE' })] }),
    phase('relay', 2), phase('player', 3)] });
  const c = card(html(s), 'ingest');
  assert.equal((c.match(/sig-stale/g) || []).length, 1);
  assert.doesNotMatch(c, /stale-note/);
  assert.match(c, /ingest\.data[\s\S]*caducada/);
});

test('BLOCKED muestra blocked_by, own_status y las señales reales', () => {
  const s = snap({ phases: [
    phase('ingest', 1, 'DOWN'),
    phase('relay', 2, 'BLOCKED', { transport: { own_status: 'OK', blocked_by: 'ingest', reason: 'Bloqueada por ingest' } }),
    phase('player', 3, 'BLOCKED', { transport: { own_status: 'DEGRADED', blocked_by: 'relay' },
      signals: [sig('player.http'), sig('player.manifest', 'DOWN'), sig('player.segments')] })] });
  const out = html(s);
  const r = card(out, 'relay');
  assert.match(r, /bloqueada por[^<]*<[^>]*>ingest</i);
  assert.match(r, /propio[^<]*<[^>]*>OK</i);
  for (const name of SIGS.relay) assert.ok(r.includes(name), name);
  const p = card(out, 'player');
  assert.match(p, /bloqueada por[^<]*<[^>]*>relay</i);
  assert.match(p, /propio[^<]*<[^>]*>DEGRADED</i);
  assert.match(p, /class="signal sig-down"><span class="sig-name">player\.manifest/);
});

test('DEGRADED muestra las métricas reales; ausentes no rompen; nunca "null"/"undefined"', () => {
  const s = snap({ phases: [
    phase('ingest', 1, 'DEGRADED', { signals: [
      sig('ingest.video', 'OK', { metrics: { bytes: 123456, objects: 42, window_seconds: 60, http_status: 200 } }),
      sig('ingest.audio'), sig('ingest.data', 'DOWN')] }),
    phase('relay', 2), phase('player', 3)] });
  const out = html(s);
  const c = card(out, 'ingest');
  for (const v of ['123456', '42', '60', '200']) assert.ok(c.includes(v), v);
  assert.doesNotMatch(out, /null|undefined|NaN/);
  assert.doesNotMatch(card(out, 'relay'), /bytes|objects/i);
});

test('metrics con basura (null, string, objeto) no rompe ni se pinta', () => {
  const bad = [null, 'x', 5, [], { bytes: 'abc', objects: null, http_status: {} }];
  for (const m of bad) {
    const s = snap(); s.phases[0].signals[0].metrics = m;
    const out = html(s);
    assert.doesNotMatch(out, /undefined|NaN|\[object/);
  }
});

// ── estructura ──────────────────────────────────────────────────────────────
test('siempre 3 fases en orden ingest, relay, player aunque lleguen desordenadas', () => {
  const s = snap({ phases: [phase('player', 3), phase('ingest', 1), phase('relay', 2)] });
  const out = html(s);
  const ids = [...out.matchAll(/data-phase-card="([a-z]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids, ['ingest', 'relay', 'player']);
});

test('datos ausentes/incompletos no lanzan y dan 3 fases UNKNOWN', () => {
  for (const d of [undefined, null, {}, { phases: [] }, { phases: 'x' }, { phases: [null, 7, {}] }]) {
    const out = renderPipeline(d, null);
    const ids = [...out.matchAll(/data-phase-card="([a-z]+)"/g)].map((m) => m[1]);
    assert.deepEqual(ids, ['ingest', 'relay', 'player'], JSON.stringify(d));
    assert.doesNotMatch(out, /undefined|\[object/);
  }
});

test('un estado de transporte desconocido cae a unknown, no inyecta su valor en la clase', () => {
  const s = snap(); s.phases[0].transport.status = '"><img src=x onerror=alert(1)>';
  const c = card(html(s), 'ingest');
  assert.match(transportBadge(c)[1], /^unknown$/);
  assert.doesNotMatch(c, /<img/);
});

// ── 503 ─────────────────────────────────────────────────────────────────────
test('503 REDIS_UNAVAILABLE → 3 fases UNKNOWN, aviso honesto, sin botones de verificar ni verde', () => {
  const out = html(null, { code: 'REDIS_UNAVAILABLE', message: 'Redis unavailable', details: { status: 'UNKNOWN' } });
  const ids = [...out.matchAll(/data-phase-card="([a-z]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids, ['ingest', 'relay', 'player']);
  for (const id of ids) assert.match(transportBadge(card(out, id))[1], /unknown/);
  assert.match(out, /Redis no disponible/);
  assert.match(out, /desconocid/i);
  assert.doesNotMatch(out, /transport-ok|transport-degraded/);
  assert.doesNotMatch(out, /data-action=/);
});

test('error distinto de 503 → panel de error escapado, sin falsas fases verdes', () => {
  const out = html(null, { code: 'INTERNAL_ERROR', message: '<script>alert(1)</script>' });
  assert.doesNotMatch(out, /<script>/);
  assert.match(out, /INTERNAL_ERROR/);
  assert.doesNotMatch(out, /transport-ok/);
});

// ── XSS ─────────────────────────────────────────────────────────────────────
const EVIL = `<script>alert(1)</script>"'&<img onerror=x>`;
test('escapeHtml escapa < > & " \' y tolera no-strings', () => {
  assert.equal(escapeHtml(`<a href="x">'&'</a>`), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;');
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
  assert.equal(escapeHtml(5), '5');
});

test('reason, note, verified_by, signal y title se escapan en el HTML de las fases', () => {
  const s = snap();
  s.phases[0].title = EVIL;
  s.phases[0].transport.reason = EVIL;
  s.phases[0].transport.blocked_by = EVIL;
  s.phases[0].human = { status: 'VERIFIED', verified_by: EVIL, verified_at: T, note: EVIL };
  s.phases[0].signals[0].signal = EVIL;
  s.phases[0].signals[0].reason = EVIL;
  s.phases[1].human = { status: 'NOT_VERIFIED', last_revoked_by: EVIL, last_revoked_at: T };
  const out = html(s);
  assert.doesNotMatch(out, /<script>|<img/);
  assert.ok(out.includes('&lt;script&gt;alert(1)&lt;/script&gt;&quot;&#39;&amp;&lt;img onerror=x&gt;'));
});

test('data-phase de los botones no se puede inyectar con un id malicioso', () => {
  const s = snap(); s.phases[0].id = '"><script>x</script>';
  const out = html(s);
  assert.doesNotMatch(out, /<script>/);
});

test('el historial escapa actor, note, reason y fase', () => {
  const out = renderHistory({ events: [
    { type: 'HUMAN_VERIFIED', phase: 'ingest', at: T, actor: EVIL, note: EVIL },
    { type: 'HUMAN_REVOKED', phase: 'relay', at: T, actor: 'a', reason: EVIL },
    { type: 'TRANSITION', phase: EVIL, at: T, from_status: EVIL, to_status: 'DOWN', reason: EVIL },
  ] });
  assert.doesNotMatch(out, /<script>|<img/);
});

// ── botones sin inline ──────────────────────────────────────────────────────
test('botones usan data-phase + data-action, sin onclick/on* inline ni javascript:', () => {
  const out = html(snap());
  assert.equal((out.match(/<button[^>]*data-action="verify"[^>]*data-phase="(ingest|relay|player)"|<button[^>]*data-phase="(ingest|relay|player)"[^>]*data-action="verify"/g) || []).length, 3);
  assert.doesNotMatch(out, /\son[a-z]+\s*=/i);
  assert.doesNotMatch(out, /javascript:/i);
});

// ── historial ───────────────────────────────────────────────────────────────
test('historial: tipo, at, fase, from→to, actor, note/reason', () => {
  const out = renderHistory({ events: [
    { type: 'TRANSITION', phase: 'relay', at: '2026-10-12T12:03:04Z', from_status: 'OK', to_status: 'DOWN', reason: 'se cayó' },
    { type: 'HUMAN_VERIFIED', phase: 'ingest', at: T, actor: 'ana@x.io', note: 'nítido' },
    { type: 'HUMAN_REVOKED', phase: 'player', at: T, actor: 'bob', reason: 'artefactos' },
  ] });
  assert.match(out, /TRANSITION/);
  assert.match(out, /2026-10-12 12:03:04 UTC/);
  assert.match(out, /relay/);
  assert.match(out, /OK\s*→\s*DOWN/);
  assert.match(out, /se cayó/);
  assert.match(out, /HUMAN_VERIFIED[\s\S]*ana@x\.io[\s\S]*nítido/);
  assert.match(out, /HUMAN_REVOKED[\s\S]*bob[\s\S]*artefactos/);
});

test('historial vacío/ausente/mal formado no rompe', () => {
  for (const h of [null, undefined, {}, { events: [] }, { events: 'x' }, { events: [null, 3, {}] }]) {
    const out = renderHistory(h);
    assert.equal(typeof out, 'string');
    assert.doesNotMatch(out, /undefined|\[object|null/);
  }
  assert.match(renderHistory({ events: [] }), /sin eventos/i);
});

test('formatTime es determinista (UTC) y tolera basura', () => {
  assert.equal(formatTime('2026-10-12T14:00:00+02:00'), '2026-10-12 12:00:00 UTC');
  assert.equal(formatTime('2026-10-12T12:00:00Z'), '2026-10-12 12:00:00 UTC');
  assert.equal(formatTime(null), '—');
  assert.equal(formatTime('basura'), '—');
});

// ── acciones ────────────────────────────────────────────────────────────────
const resp = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => { if (body === undefined) throw new Error('no json'); return body; } });
function recorder(handler) {
  const calls = [];
  const api = async (path, opts = {}) => { calls.push({ path, method: opts.method || 'GET', body: opts.body }); return handler(path, opts, calls); };
  return { api, calls };
}

test('describeError: mensaje distinto y útil para 401/403/404/409/503/otros', () => {
  const msgs = new Map();
  for (const [st, body] of [[401], [403], [404, { code: 'PHASE_NOT_FOUND' }], [409, { code: 'ALREADY_VERIFIED' }],
    [409, { code: 'NOT_VERIFIED' }], [503, { code: 'REDIS_UNAVAILABLE' }], [400, { code: 'VALIDATION_ERROR', message: 'note too long' }], [500]]) {
    const m = describeError(st, body);
    assert.ok(typeof m === 'string' && m.length > 5, `${st}`);
    msgs.set(`${st}${body?.code ?? ''}`, m);
  }
  assert.equal(new Set(msgs.values()).size, msgs.size);
  assert.match(msgs.get('409ALREADY_VERIFIED'), /ya (está|estaba) verificada/i);
  assert.match(msgs.get('409NOT_VERIFIED'), /no (está|estaba) verificada/i);
  assert.match(msgs.get('401'), /sesión/i);
  assert.match(msgs.get('403'), /permiso/i);
  assert.match(msgs.get('503REDIS_UNAVAILABLE'), /redis/i);
});

test('Verificar → POST /admin/pipeline/phases/<id>/verification con body solo {note}, y recarga', async () => {
  const { api, calls } = recorder(() => resp(200, {}));
  const notes = []; let reloads = 0;
  const r = await runAction({ api, phase: 'relay', action: 'verify', askNote: () => 'se ve bien',
    notify: (m) => notes.push(m), reload: async () => { reloads++; } });
  assert.deepEqual(calls.map((c) => [c.method, c.path]), [['POST', '/admin/pipeline/phases/relay/verification']]);
  assert.deepEqual(JSON.parse(calls[0].body), { note: 'se ve bien' });
  assert.equal(reloads, 1);
  assert.equal(r.ok, true);
});

test('Revocar → DELETE con body solo {reason}', async () => {
  const { api, calls } = recorder(() => resp(200, {}));
  await runAction({ api, phase: 'player', action: 'revoke', askNote: () => 'artefactos', notify() {}, reload: async () => {} });
  assert.deepEqual(calls.map((c) => [c.method, c.path]), [['DELETE', '/admin/pipeline/phases/player/verification']]);
  assert.deepEqual(JSON.parse(calls[0].body), { reason: 'artefactos' });
});

test('el body nunca lleva operador/timestamp aunque el usuario los escriba en la nota', async () => {
  const { api, calls } = recorder(() => resp(200, {}));
  await runAction({ api, phase: 'ingest', action: 'verify', askNote: () => '{"operator":"x","verified_at":"y"}', notify() {}, reload: async () => {} });
  const b = JSON.parse(calls[0].body);
  assert.deepEqual(Object.keys(b), ['note']);
  assert.equal(typeof b.note, 'string');
});

test('nota vacía → body {} (sin clave); cancelar el prompt → ninguna llamada', async () => {
  let { api, calls } = recorder(() => resp(200, {}));
  await runAction({ api, phase: 'ingest', action: 'verify', askNote: () => '', notify() {}, reload: async () => {} });
  assert.deepEqual(JSON.parse(calls[0].body), {});
  ({ api, calls } = recorder(() => resp(200, {})));
  const r = await runAction({ api, phase: 'ingest', action: 'verify', askNote: () => null, notify() {}, reload: async () => {} });
  assert.equal(calls.length, 0);
  assert.equal(r.cancelled, true);
});

test('fase o acción inválida → no llama a la API', async () => {
  const { api, calls } = recorder(() => resp(200, {}));
  for (const [phase, action] of [['../x', 'verify'], ['ingest', 'delete'], ['', 'verify'], [undefined, 'verify'], ['INGEST', 'verify']]) {
    const r = await runAction({ api, phase, action, askNote: () => 'x', notify() {}, reload: async () => {} });
    assert.equal(r.ok, false);
  }
  assert.equal(calls.length, 0);
});

for (const [st, body, re] of [[401, undefined, /sesión/i], [403, { code: 'FORBIDDEN' }, /permiso/i], [404, { code: 'PHASE_NOT_FOUND' }, /fase/i],
  [409, { code: 'ALREADY_VERIFIED' }, /verificada/i], [503, { code: 'REDIS_UNAVAILABLE' }, /redis/i]]) {
  test(`error ${st} se muestra al usuario y se recarga (sin lanzar)`, async () => {
    const { api } = recorder(() => resp(st, body));
    const notes = []; let reloads = 0;
    const r = await runAction({ api, phase: 'ingest', action: 'verify', askNote: () => 'n', notify: (m) => notes.push(m), reload: async () => { reloads++; } });
    assert.equal(r.ok, false);
    assert.equal(notes.length, 1);
    assert.match(notes[0], re);
    assert.equal(reloads, 1);
  });
}

test('api() que lanza (Error("401") o red) se muestra y no se propaga; 401 no recarga', async () => {
  const notes = []; let reloads = 0;
  const base = { phase: 'ingest', action: 'verify', askNote: () => 'n', notify: (m) => notes.push(m), reload: async () => { reloads++; } };
  const r1 = await runAction({ ...base, api: async () => { throw new Error('401'); } });
  assert.equal(r1.ok, false); assert.match(notes[0], /sesión/i); assert.equal(reloads, 0);
  const r2 = await runAction({ ...base, api: async () => { throw new TypeError('Failed to fetch'); } });
  assert.equal(r2.ok, false); assert.equal(notes.length, 2);
});

test('si reload falla tras la acción no se propaga', async () => {
  const { api } = recorder(() => resp(200, {}));
  const r = await runAction({ api, phase: 'ingest', action: 'verify', askNote: () => 'n', notify() {}, reload: async () => { throw new Error('boom'); } });
  assert.equal(r.ok, true);
});

// ── delegación de clicks ────────────────────────────────────────────────────
function fakeContainer() {
  const listeners = [];
  return { listeners, addEventListener(t, fn) { listeners.push([t, fn]); }, fire(target) { return Promise.all(listeners.filter(([t]) => t === 'click').map(([, fn]) => fn({ target }))); } };
}
const fakeBtn = (phase, action) => ({ closest: (sel) => (sel.includes('data-phase') ? { dataset: { phase, action } } : null) });

test('attachClicks engancha UNA sola vez por contenedor y despacha phase/action', async () => {
  const c = fakeContainer(); const got = [];
  attachClicks(c, (p, a) => got.push([p, a]));
  attachClicks(c, (p, a) => got.push(['dup', p, a]));
  assert.equal(c.listeners.length, 1);
  await c.fire(fakeBtn('relay', 'verify'));
  await c.fire({ closest: () => null });
  await c.fire({});
  await c.fire(null);
  assert.deepEqual(got, [['relay', 'verify']]);
});

// ── refresh ─────────────────────────────────────────────────────────────────
const SNAP = snap();
const HIST = { limit: 50, retention_max_events: 1000, events: [{ type: 'TRANSITION', phase: 'ingest', at: T, from_status: 'UNKNOWN', to_status: 'OK', reason: 'r' }] };

test('refresh pide status e historial?limit=50 y pinta ambos', async () => {
  const { api, calls } = recorder((p) => (p.startsWith('/admin/pipeline/status') ? resp(200, SNAP) : resp(200, HIST)));
  let painted = null;
  const r = await refresh({ api, setContent: (h) => { painted = h; }, isActive: () => true });
  assert.deepEqual(calls.map((c) => c.path), ['/admin/pipeline/status', '/admin/pipeline/history?limit=50']);
  assert.equal(r.painted, true);
  assert.match(painted, /data-phase-card="ingest"/);
  assert.match(painted, /TRANSITION/);
});

test('status 503 → 3 fases UNKNOWN + aviso, y NO se pide historial', async () => {
  const { api, calls } = recorder(() => resp(503, { code: 'REDIS_UNAVAILABLE', message: 'x', details: { status: 'UNKNOWN' } }));
  let painted = '';
  await refresh({ api, setContent: (h) => { painted = h; }, isActive: () => true });
  assert.equal(calls.length, 1);
  assert.match(painted, /Redis no disponible/);
  assert.equal((painted.match(/data-phase-card=/g) || []).length, 3);
  assert.doesNotMatch(painted, /Historial/i);
});

test('historial que falla (500 / lanza) se omite sin romper el estado', async () => {
  for (const hist of [() => resp(500, { code: 'INTERNAL_ERROR' }), () => { throw new TypeError('net'); }]) {
    const { api } = recorder((p) => (p.startsWith('/admin/pipeline/status') ? resp(200, SNAP) : hist()));
    let painted = '';
    await refresh({ api, setContent: (h) => { painted = h; }, isActive: () => true });
    assert.equal((painted.match(/data-phase-card=/g) || []).length, 3);
  }
});

test('status 500 con cuerpo no JSON → estado honesto UNKNOWN (sin conexión), no lanza', async () => {
  const { api } = recorder(() => resp(500));
  let painted = '';
  await refresh({ api, setContent: (h) => { painted = h; }, isActive: () => true });
  assert.match(painted, /sin conexión con admin-api: estado UNKNOWN/i);
  assert.doesNotMatch(painted, /transport-ok/);
});

// ── H1: fallo de red / respuesta inválida / HTTP inesperado → UNKNOWN honesto, y se recupera ──────────
const OFFLINE = /sin conexión con admin-api: estado UNKNOWN/i;
const failures = {
  'red caída (TypeError Failed to fetch)': () => { throw new TypeError('Failed to fetch'); },
  'HTTP 500 con JSON': () => resp(500, { code: 'INTERNAL_ERROR', message: 'boom' }),
  'HTTP 500 sin JSON': () => resp(500),
  'HTTP 502': () => resp(502),
  'HTTP 403': () => resp(403, { code: 'FORBIDDEN' }),
  '200 con JSON inválido': () => resp(200),
  '200 con JSON no objeto': () => resp(200, [1, 2]),
  '503 sin cuerpo reconocible': () => resp(503),
};
for (const [name, fail] of Object.entries(failures)) {
  test(`H1 ${name}: tras un snapshot verde ya no queda ningún badge OK y aparece el aviso; luego se recupera`, async () => {
    let mode = 'good';
    const { api, calls } = recorder((p) => {
      if (mode === 'fail') return fail();
      return p.startsWith('/admin/pipeline/status') ? resp(200, SNAP) : resp(200, HIST);
    });
    let painted = '';
    const run = () => refresh({ api, setContent: (h) => { painted = h; }, isActive: () => true });
    await run();
    assert.match(painted, /transport-ok/);
    mode = 'fail';
    const n = calls.length;
    const r = await run();                       // no debe lanzar
    assert.equal(r.painted, true);
    assert.equal(calls.length, n + 1, 'sin status válido no se pide historial');
    assert.doesNotMatch(painted, /transport-ok|transport-degraded|>OK</);
    assert.doesNotMatch(painted, /data-action=/);
    assert.match(painted, OFFLINE);
    const ids = [...painted.matchAll(/data-phase-card="([a-z]+)"/g)].map((m) => m[1]);
    assert.deepEqual(ids, ['ingest', 'relay', 'player']);
    for (const id of ids) assert.match(transportBadge(card(painted, id))[1], /unknown/);
    mode = 'good';
    await run();                                  // recuperación
    assert.match(painted, /transport-ok/);
    assert.doesNotMatch(painted, OFFLINE);
  });
}

test('H1 carga inicial sin conexión: pinta UNKNOWN en vez de lanzar', async () => {
  let painted = '';
  await refresh({ api: async () => { throw new TypeError('Failed to fetch'); }, setContent: (h) => { painted = h; }, isActive: () => true });
  assert.match(painted, OFFLINE);
});

test('H1 un fallo de red en el polling pinta UNKNOWN y el interval sigue vivo para recuperarse', async () => {
  const t = fakeTimers(); let mode = 'fail'; let painted = '';
  const { api } = recorder((p) => {
    if (mode === 'fail') throw new TypeError('Failed to fetch');
    return p.startsWith('/admin/pipeline/status') ? resp(200, SNAP) : resp(200, HIST);
  });
  const doRefresh = () => refresh({ api, setContent: (h) => { painted = h; }, isActive: () => true });
  const id = startPolling({ refresh: doRefresh, isActive: () => true, setInterval: t.setInterval, clearInterval: t.clearInterval, setMonitorInterval() {}, ms: 1 });
  await t.live.get(id).fn();
  assert.match(painted, OFFLINE);
  assert.equal(t.live.size, 1);
  mode = 'good';
  await t.live.get(id).fn();
  assert.match(painted, /transport-ok/);
});

test('H1 un 401 sigue propagándose (lo gestiona api()) y no se pinta como sin conexión', async () => {
  let painted = false;
  await assert.rejects(refresh({ api: async () => { throw new Error('401'); }, setContent: () => { painted = true; }, isActive: () => true }), /401/);
  assert.equal(painted, false);
});

test('refresh no pinta si el usuario ya navegó a otra página (durante el await)', async () => {
  let active = true;
  const { api } = recorder(async (p) => { active = false; return p.startsWith('/admin/pipeline/status') ? resp(200, SNAP) : resp(200, HIST); });
  let painted = false;
  const r = await refresh({ api, setContent: () => { painted = true; }, isActive: () => active });
  assert.equal(painted, false);
  assert.equal(r.painted, false);
});

test('refresh propaga Error("401") (lo maneja router/auth) y no pinta', async () => {
  let painted = false;
  await assert.rejects(refresh({ api: async () => { throw new Error('401'); }, setContent: () => { painted = true; }, isActive: () => true }), /401/);
  assert.equal(painted, false);
});

// ── polling ─────────────────────────────────────────────────────────────────
function fakeTimers() {
  let next = 1; const live = new Map();
  return { live, setInterval: (fn, ms) => { const id = next++; live.set(id, { fn, ms }); return id; }, clearInterval: (id) => live.delete(id) };
}

test('polling: un solo interval registrado con setMonitorInterval; tick refresca', async () => {
  const t = fakeTimers(); const registered = []; let n = 0;
  const id = startPolling({ refresh: async () => { n++; }, isActive: () => true, setInterval: t.setInterval, clearInterval: t.clearInterval, setMonitorInterval: (i) => registered.push(i), ms: 30000 });
  assert.equal(t.live.size, 1);
  assert.equal(t.live.get(id).ms, 30000);
  assert.deepEqual(registered, [id]);
  await t.live.get(id).fn();
  assert.equal(n, 1);
});

test('polling: si ya no está activo el tick limpia su interval y no refresca', async () => {
  const t = fakeTimers(); let n = 0; let active = true;
  const id = startPolling({ refresh: async () => { n++; }, isActive: () => active, setInterval: t.setInterval, clearInterval: t.clearInterval, setMonitorInterval() {}, ms: 1 });
  active = false;
  await t.live.get(id).fn();
  assert.equal(n, 0);
  assert.equal(t.live.size, 0);
});

test('polling: un refresh que lanza (401/red) no produce rechazo no capturado', async () => {
  const t = fakeTimers();
  const id = startPolling({ refresh: async () => { throw new Error('401'); }, isActive: () => true, setInterval: t.setInterval, clearInterval: t.clearInterval, setMonitorInterval() {}, ms: 1 });
  await t.live.get(id).fn(); // si lanzara, el test fallaría
});

test('polling: no solapa refreshes lentos', async () => {
  const t = fakeTimers(); let running = 0, max = 0, calls = 0; let release;
  const id = startPolling({ refresh: () => { calls++; running++; max = Math.max(max, running); return new Promise((r) => { release = () => { running--; r(); }; }); },
    isActive: () => true, setInterval: t.setInterval, clearInterval: t.clearInterval, setMonitorInterval() {}, ms: 1 });
  const a = t.live.get(id).fn(); const b = t.live.get(id).fn();
  await b; release(); await a;
  assert.equal(calls, 1); assert.equal(max, 1);
});
