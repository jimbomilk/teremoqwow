/**
 * RED TEST: Closure error near deadline can be swallowed
 *
 * Issue #2: Si error "Track closed" ocurre justo antes del deadline,
 * y hay un retry/sleep que cruza deadline, el timeout puede tragarse el error.
 *
 * Escenario:
 *  - Deadline: 1s
 *  - A 950ms: Track se cierra → error "Track closed"
 *  - Pero el error está en try/catch
 *  - Si hay un sleep antes de chequear timeout...
 *  - A 1050ms: Check `if (timeRemaining <= 0)` → break
 *  - El error de cierre se perdió, devuelve success []
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('RED: Closure error just before deadline must not be swallowed by timeout', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Deadline: 1s
  const deadline = Date.now() + 1000;

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Cerrar track justo antes del deadline (pero sin pasar)
  // Simula: track se cierra a 950ms
  await new Promise(r => setTimeout(r, 950));
  subscriber.close();

  let result = null;
  let error = null;

  try {
    result = await readPromise;
  } catch (err) {
    error = err;
  }

  // El comportamiento CORRECTO es:
  // 1. Close causó error "Track closed"
  // 2. Error se propaga (no es tragado)
  //
  // El comportamiento INCORRECTO es:
  // 1. Close causó error
  // 2. Error se entra en try/catch
  // 3. Pero luego el loop timeout deadline check (if timeRemaining <= 0)
  //    lo trata como "window expired" y rompe
  // 4. Retorna [] sin error ← FALSE POSITIVE connected:true

  if (error) {
    assert.ok(
      error.message.includes('Track closed'),
      `Error must indicate track closed. Got: "${error.message}"`
    );
    console.log(`✓ RED: Closure error propagated (not swallowed): ${error.message}`);
  } else {
    assert.fail(
      'readJsonAcrossGroups returned success when track closed just before deadline. ' +
      'Bug: Closure error was swallowed, observeTrack() would report connected:true falsely.'
    );
  }
});

test('RED: Deadline crossing during error handling must not suppress Track closed error', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Very tight deadline: 200ms
  const deadline = Date.now() + 200;

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Close track almost at deadline
  // 150ms: close track → track closure error in readPromise
  // 200ms: deadline expires → loop checks `if (timeRemaining <= 0) break`
  // BUG: if error handling happens to check deadline before re-throwing error,
  // the closure error gets swallowed
  await new Promise(r => setTimeout(r, 150));
  subscriber.close();

  let error = null;
  try {
    await readPromise;
  } catch (err) {
    error = err;
  }

  assert.ok(
    error !== null,
    'readJsonAcrossGroups must throw error when track closes before deadline. ' +
    'Bug: Closure error swallowed by deadline check.'
  );

  assert.ok(
    error.message.includes('Track closed'),
    `Error must indicate track closed. Got: "${error.message}"`
  );

  console.log(`✓ RED: Closure error not suppressed by deadline: ${error.message}`);
});
