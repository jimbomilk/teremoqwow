#!/usr/bin/env node

/**
 * tests/helpers/h2-scenario.mjs
 *
 * Hijo de procesos para los escenarios H2 (enmienda 2026-10-18, contrato #206,
 * decisión opción B: reconexión finita MAX_RECONNECT_ATTEMPTS).
 *
 * Ejecuta publishHeartbeats() REAL con mocks y emite líneas de evento
 * SÍNCRONAS a stdout ('connect', 'publish', 'returned-normally') mediante
 * fs.writeSync, de modo que el test padre pueda afirmar la secuencia exacta
 * incluso cuando el hijo termina con process.exit(1) (writeSync no se trunca).
 *
 * El mock de timer cierra la conexión (resuelve connection.closed) DURING la
 * espera, antes de que la Promise.race se asiente: el timer gana la race y el
 * guard `if (closedState)` es lo ÚNICO que puede detectar el cierre. Ese es
 * exactamente el superficie de la mutación H2 (`if (false && closedState)`).
 *
 * Escenarios:
 *   exhaust — MAX_RECONNECT_ATTEMPTS=2 vía ENV (no inyectado): la conexión
 *             cierra en cada espera del timer; el publisher debe agotar los
 *             intentos y hacer process.exit(1) con log FATAL (sin colgar).
 *   reset   — maxReconnectAttempts=2 inyectado; la conexión #2 publica UN
 *             frame antes de cerrar; el contador debe resetearse al iniciar
 *             publicación, así que exit(1) solo ocurre tras la conexión #3.
 *   guard   — como exhaust pero con maxPublishes=3: si el guard closedState
 *             se muta a `if (false && closedState)`, el publisher publicaría
 *             3 frames y saldría con código 0 en vez de exit(1).
 *
 * Uso: node tests/helpers/h2-scenario.mjs <exhaust|reset|guard>
 */

import { writeSync } from 'node:fs';
import { publishHeartbeats } from '../../src/publisher.mjs';

const scenario = process.argv[2] || 'exhaust';

function emit(event) {
  writeSync(1, event + '\n');
}

let connectCount = 0;
let waitsThisConnection = 0;
let currentClosedResolve = null;

const mockOrigin = { consume: () => ({}) };

const mockConnect = async () => {
  connectCount++;
  waitsThisConnection = 0;
  emit('connect');
  return {
    closed: new Promise((resolve) => {
      currentClosedResolve = resolve;
    }),
    close: () => {},
  };
};

const mockTrack = {
  appendGroup: () => ({
    writeJson: () => {
      emit('publish');
    },
    close: () => {},
  }),
};

// Cada wait() cierra la conexión antes de retornar: el timer gana la
// Promise.race y solo el guard closedState puede detectar el cierre.
const mockTimer = {
  wait: async () => {
    waitsThisConnection++;
    const allowOnePublish =
      scenario === 'reset' && connectCount === 2 && waitsThisConnection === 1;
    if (!allowOnePublish && currentClosedResolve) {
      currentClosedResolve();
    }
  },
};

const noopSleep = async () => {};

const options = {
  connect: mockConnect,
  origin: mockOrigin,
  track: mockTrack,
  timer: mockTimer,
  sleep: noopSleep,
};

if (scenario === 'exhaust') {
  options.maxPublishes = 100;
  // maxReconnectAttempts NO se inyecta: viene del ENV MAX_RECONNECT_ATTEMPTS=2
} else if (scenario === 'reset' || scenario === 'guard') {
  options.maxReconnectAttempts = 2;
  options.maxPublishes = scenario === 'guard' ? 3 : 100;
} else {
  writeSync(2, `unknown scenario: ${scenario}\n`);
  process.exit(2);
}

await publishHeartbeats(options);
emit('returned-normally');
