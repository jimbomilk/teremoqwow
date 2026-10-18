#!/usr/bin/env node

/**
 * test-publisher-h2-reconnect-finite.mjs
 *
 * Enmienda 2026-10-18 del contrato #206 (decisión H2, opción B):
 * el bucle de reconexión es FINITO — MAX_RECONNECT_ATTEMPTS (env, entero >0,
 * default 30) intentos consecutivos fallidos; agotados → log FATAL a stderr
 * (con número de intentos) + process.exit(1). Éxito al iniciar publicación
 * resetea el contador a 0. Backoff 1s→5s y reset-on-connect SIN cambios.
 *
 * ── MUTACIÓN H2 QUE MATAN ESTOS TESTS ─────────────────────────────────────
 * Mutación: `if (closedState)` → `if (false && closedState)` (o eliminar el
 * guard) en el bucle interno de publishHeartbeats().
 *
 * Con el guard mutado, el cierre de conexión resuelto por el mock DURING la
 * espera del timer (el timer gana la Promise.race; el guard es la ÚNICA vía
 * de detección) pasa desapercibido: el publisher sigue publicando hasta
 * maxPublishes y retorna con código 0 en vez de detectar pérdida de conexión,
 * reconectar y agotar intentos con exit(1).
 *
 * El escenario 'guard' (maxPublishes=3) lo afirma explícitamente:
 *   guard intacto  → 0 publishes, 2 connects, exit code 1, log FATAL
 *   guard mutado   → 3 publishes, exit code 0, 'returned-normally'
 * Los escenarios 'exhaust' y 'reset' también fallan con el guard mutado
 * (publicarían hasta maxPublishes=100 y saldrían con código 0).
 *
 * Los escenarios de comportamiento se ejecutan en un PROCESO HIJO
 * (tests/helpers/h2-scenario.mjs) para que el process.exit(1) REAL sea
 * observable y para que un bucle infinito (código pre-enmienda) no cuelgue
 * el runner: el padre mata el hijo tras 5 s → test FAIL determinista.
 *
 * Mutaciones adicionales que mata este archivo:
 *   - eliminar `reconnectAttempts = 0` tras publicación exitosa → falla
 *     escenario 'reset' (espera 3 connects; sin reset serían 2).
 *   - eliminar el check de agotamiento (bucle infinito) → timeout → FAIL.
 *   - exit(0)/exit sin código en vez de exit(1) → falla assert de código.
 *   - parseMaxReconnectAttempts tolerante ("0"/"abc"/"-2" → otro valor) →
 *     fallan los asserts de contrato de env.
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const HELPER = fileURLToPath(new URL('./helpers/h2-scenario.mjs', import.meta.url));
const CHILD_TIMEOUT_MS = 5000;

/**
 * Ejecuta un escenario H2 en un hijo y devuelve {code, signal, events,
 * stderr, timedOut}. events = líneas stdout síncronas del escenario.
 */
function runScenario(scenario, extraEnv = {}) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [HELPER, scenario], {
      env: {
        ...process.env,
        BROADCAST: 'anon/live1-meta',
        HEALTH_MARKER_PATH: join(tmpdir(), `h2-marker-${scenario}-${Date.now()}`),
        ...extraEnv,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const events = [];
    let stdoutBuf = '';
    let stderrBuf = '';
    let timedOut = false;

    child.stdout.on('data', (d) => {
      stdoutBuf += d.toString();
      let idx;
      while ((idx = stdoutBuf.indexOf('\n')) >= 0) {
        events.push(stdoutBuf.slice(0, idx));
        stdoutBuf = stdoutBuf.slice(idx + 1);
      }
    });
    child.stderr.on('data', (d) => {
      stderrBuf += d.toString();
    });

    const killer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, CHILD_TIMEOUT_MS);

    child.on('exit', (code, signal) => {
      clearTimeout(killer);
      resolve({ code, signal, events, stderr: stderrBuf, timedOut });
    });
  });
}

function count(events, name) {
  return events.filter((e) => e === name).length;
}

// ── Contrato de parsing de MAX_RECONNECT_ATTEMPTS ─────────────────────────

test('H2 env contract: parseMaxReconnectAttempts — ausente/inválida → 30, "5" → 5', async () => {
  const mod = await import('../src/publisher.mjs');
  assert.equal(
    typeof mod.parseMaxReconnectAttempts,
    'function',
    'publisher.mjs debe exportar parseMaxReconnectAttempts (contrato enmienda H2)'
  );
  const parse = mod.parseMaxReconnectAttempts;

  // Ausente o vacía → default 30
  assert.equal(parse(undefined), 30, 'undefined → 30');
  assert.equal(parse(null), 30, 'null → 30');
  assert.equal(parse(''), 30, 'cadena vacía → 30');

  // Entero positivo válido
  assert.equal(parse('5'), 5, '"5" → 5');
  assert.equal(parse('1'), 1, '"1" → 1 (mínimo válido)');
  assert.equal(parse('30'), 30, '"30" → 30');
  assert.equal(parse(7), 7, 'número entero 7 → 7');

  // Inválidas → default 30 (entero > 0 obligatorio)
  assert.equal(parse('0'), 30, '"0" → 30 (no es > 0)');
  assert.equal(parse('-2'), 30, '"-2" → 30 (negativo)');
  assert.equal(parse('abc'), 30, '"abc" → 30 (no numérico)');
  assert.equal(parse('2.5'), 30, '"2.5" → 30 (no entero)');
  assert.equal(parse('1e3'), 30, '"1e3" → 30 (notación no aceptada)');
  assert.equal(parse('  4  '), 4, '"  4  " → 4 (whitespace tolerado por Number)');
  assert.equal(parse(NaN), 30, 'NaN → 30');
  assert.equal(parse(Infinity), 30, 'Infinity → 30 (no es entero finito)');
});

test('H2 env contract: módulo usa MAX_RECONNECT_ATTEMPTS con default 30', async () => {
  const fs = await import('node:fs').then((m) => m.promises);
  const source = await fs.readFile(
    fileURLToPath(new URL('../src/publisher.mjs', import.meta.url)),
    'utf8'
  );
  assert.ok(
    source.includes('process.env.MAX_RECONNECT_ATTEMPTS'),
    'debe leer process.env.MAX_RECONNECT_ATTEMPTS (igual que las demás envs)'
  );
  assert.ok(
    /DEFAULT_MAX_RECONNECT_ATTEMPTS\s*=\s*30/.test(source),
    'default documentado = 30 (producción; docker-compose NO añade la env)'
  );
});

// ── Escenario exhaust: agota intentos → exit(1), sin colgar ───────────────

test('H2 exhaust: con MAX_RECONNECT_ATTEMPTS=2 (env) agota intentos y sale con código 1', async () => {
  const r = await runScenario('exhaust', { MAX_RECONNECT_ATTEMPTS: '2' });

  assert.ok(
    !r.timedOut,
    'el publisher NO debe colgar en bucle infinito de reconexión ' +
    '(mutación: eliminar el check de agotamiento → timeout → FAIL). ' +
    `Últimos eventos: ${JSON.stringify(r.events.slice(-6))}`
  );
  assert.equal(r.code, 1, `debe terminar con process.exit(1); code=${r.code} signal=${r.signal}`);
  assert.ok(!r.events.includes('returned-normally'), 'no debe retornar normalmente');

  // 2 intentos consecutivos fallidos: connect #1 pierde conexión (attempts=1),
  // connect #2 pierde conexión (attempts=2 = MAX) → FATAL exit(1)
  assert.equal(count(r.events, 'connect'), 2, 'exactamente 2 conexiones antes de agotar');
  assert.equal(count(r.events, 'publish'), 0, 'ningún frame publicado (conexión cierra en cada espera)');

  // Log claro a stderr con número de intentos (contrato enmienda)
  assert.match(r.stderr, /FATAL/, 'debe loggear FATAL a stderr');
  assert.match(
    r.stderr,
    /MAX_RECONNECT_ATTEMPTS/,
    'el log FATAL debe citar MAX_RECONNECT_ATTEMPTS'
  );
  assert.match(r.stderr, /2\/2|2 .*intentos|attempts.*2/i, 'el log debe incluir el número de intentos');
});

// ── Escenario guard: mata la mutación H2 explícitamente ───────────────────

test('H2 guard mutation: cerrar conexión durante la espera del timer ejercita el guard closedState', async () => {
  // maxPublishes=3 + maxReconnectAttempts=2 inyectados.
  // El mock resuelve connection.closed DURING timer.wait(): el timer gana la
  // Promise.race y SOLO el guard `if (closedState)` puede detectar el cierre.
  //
  // MUTACIÓN MATADA: `if (false && closedState)` / eliminar el guard.
  //   - guard intacto: connectionLost en cada conexión → 0 publishes,
  //     2 connects, FATAL, exit code 1.
  //   - guard mutado: no detecta cierre → publica 3 frames (maxPublishes)
  //     → retorna normalmente con exit code 0 → este test FALLA.
  const r = await runScenario('guard');

  assert.ok(!r.timedOut, 'no debe colgar (bucle finito por MAX_RECONNECT_ATTEMPTS inyectado)');
  assert.equal(
    count(r.events, 'publish'),
    0,
    'guard intacto: NUNCA publica sobre conexión cerrada. ' +
    'Si hay publishes, el guard closedState fue mutado (if (false && closedState)) ' +
    `— eventos: ${JSON.stringify(r.events)}`
  );
  assert.equal(r.code, 1, `guard intacto → agota intentos → exit(1); code=${r.code}`);
  assert.ok(!r.events.includes('returned-normally'), 'guard mutado retornaría normalmente');
  assert.equal(count(r.events, 'connect'), 2, '2 intentos consecutivos fallidos');
});

// ── Escenario reset: conexión exitosa (publicación iniciada) resetea ──────

test('H2 reset: publicación iniciada resetea el contador de intentos consecutivos', async () => {
  // maxReconnectAttempts=2 inyectado. Secuencia del escenario:
  //   conn #1: cierra en espera → attempts=1 → reconecta
  //   conn #2: publica 1 frame (RESET attempts=0) → cierra → attempts=1
  //   conn #3: cierra → attempts=2 = MAX → FATAL exit(1)
  // Sin el reset (mutación: eliminar `reconnectAttempts = 0`), la conn #2
  // agotaría (attempts=2) y solo habría 2 connects → este test FALLA.
  const r = await runScenario('reset');

  assert.ok(!r.timedOut, 'no debe colgar');
  assert.equal(r.code, 1, `debe terminar con exit(1); code=${r.code}`);
  assert.equal(count(r.events, 'publish'), 1, 'exactamente 1 frame publicado (conn #2)');
  assert.equal(
    count(r.events, 'connect'),
    3,
    'el contador se resetea tras publicar: hacen falta 3 conexiones para agotar 2 intentos CONSECUTIVOS. ' +
    `Eventos: ${JSON.stringify(r.events)}`
  );
  assert.match(r.stderr, /FATAL/, 'log FATAL presente');
});

// ── Backoff intacto (contrato punto 3: no cambia comportamiento) ──────────

test('H2 backoff: el agotamiento respeta el backoff existente 1s→5s (secuencia en stderr)', async () => {
  const r = await runScenario('exhaust', { MAX_RECONNECT_ATTEMPTS: '3' });

  assert.ok(!r.timedOut, 'no debe colgar');
  assert.equal(r.code, 1, 'exit(1) tras 3 intentos');
  assert.equal(count(r.events, 'connect'), 3, '3 conexiones con MAX_RECONNECT_ATTEMPTS=3');

  // Backoff sin cambios: primer reintento 1500ms (1000*1.5), cap 5000
  const reconnectLines = r.stderr.split('\n').filter((l) => l.includes('Reconnecting in'));
  assert.ok(reconnectLines.length >= 2, 'debe loggear Reconnecting in ...ms (backoff intacto)');
  assert.match(reconnectLines[0], /1500ms/, 'primer backoff = 1500ms (1000 * 1.5, igual que antes)');
});
