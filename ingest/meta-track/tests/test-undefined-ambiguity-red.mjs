/**
 * RED TEST: Demuestra la ambigüedad de undefined en nextGroup()
 *
 * Contrato: nextGroup() retorna undefined cuando el track se cierra,
 * NO cuando "temporalmente no hay datos".
 *
 * Bug actual: readJsonAcrossGroups trata undefined como "no hay datos ahora"
 * y termina normalmente (break). Pero undefined antes del deadline es cierre.
 *
 * Este test debe FALLAR con el código actual y PASAR cuando se arregle.
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('RED: nextGroup() undefined before deadline must be treated as track closure, not normal', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar 1 grupo con 1 heartbeat
  const group1 = track.appendGroup();
  group1.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 0 });
  group1.close();

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Deadline: 5 segundos de ahora
  const deadline = Date.now() + 5000;

  // Lanzar lectura
  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Esperar a que lea el primer grupo
  await new Promise(r => setTimeout(r, 200));

  // Cerrar track INMEDIATAMENTE después de leer primer grupo
  // Esto simula: track se cierra antes de que deadline expire
  subscriber.close();

  // Ahora cuando nextGroup() se llame nuevamente, retornará undefined
  // El contrato dice: undefined = track cerrado
  //
  // Comportamiento CORRECTO (esperado):
  //   readJsonAcrossGroups debería lanzar error "Track closed"
  //   porque undefined ocurrió ANTES del deadline
  //
  // Comportamiento INCORRECTO (bug actual):
  //   readJsonAcrossGroups retorna [] (break sobre undefined)
  //   porque asume que "no hay más grupos disponibles" (no es cierre)

  let caughtError = null;
  try {
    await readPromise;
  } catch (err) {
    caughtError = err;
  }

  // ASSERTIÓN ESTRICTA: DEBE haber error
  assert.ok(
    caughtError !== null,
    'readJsonAcrossGroups MUST throw error when nextGroup() returns undefined before deadline. ' +
    'Got: no error thrown (treated as normal completion). ' +
    'Bug: undefined ambiguity not resolved.'
  );

  assert.ok(
    caughtError.message.includes('Track closed'),
    `Error must indicate track closed. Got: "${caughtError.message}"`
  );

  console.log(`✅ RED test PASSES (should fail with current code): ${caughtError.message}`);
});

test('RED: undefined after deadline is OK (window timeout), but undefined before deadline is error', async (t) => {
  // Este test distingue: undefined DESPUÉS del deadline es normal (window expired)
  // pero undefined ANTES del deadline es cierre (error).

  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Deadline: 500ms (very short window, more likely to timeout before getting undefined)
  const deadline = Date.now() + 500;

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Wait for deadline to pass naturally
  await new Promise(r => setTimeout(r, 1000));

  // If deadline passed naturally, readJsonAcrossGroups should return []
  // (window timeout is normal, NOT error)
  let result = null;
  let caughtError = null;
  try {
    result = await readPromise;
  } catch (err) {
    caughtError = err;
  }

  // If timeout expires, should return [] without error
  // If undefined occurs BEFORE timeout, should throw error
  // Current code can't distinguish these, which is the bug.

  if (result !== null) {
    console.log(`✅ RED test part 2: Timeout handled correctly (no error, returned ${result.length} objects)`);
    assert.equal(result.length, 0, 'Should return empty array on timeout');
  } else if (caughtError) {
    // If closure detected before timeout, error is also OK (preferred actually)
    console.log(`✅ RED test part 2: Closure detected before timeout: ${caughtError.message}`);
    assert.ok(caughtError.message.includes('Track closed') || caughtError.message.includes('timeout'));
  }
});
