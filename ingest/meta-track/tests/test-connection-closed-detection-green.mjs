/**
 * GREEN TEST: readJsonAcrossGroups strictly enforces track closure detection
 * (después de la corrección)
 *
 * Cambio: Ahora undefined de nextGroup() es tratado como track closure,
 * incluso si ocurre antes del deadline. Esto previene false positive
 * {connected:true} cuando la conexión se ha perdido.
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('GREEN: readJsonAcrossGroups detects track closure and ALWAYS throws', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar 1 grupo
  const group1 = track.appendGroup();
  group1.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 0 });
  group1.close();

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 5000; // 5s window

  // Lanzar lectura
  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Esperar a que lea el primer grupo
  await new Promise(r => setTimeout(r, 300));

  // Cerrar track mid-window
  subscriber.close();

  // La lectura DEBE detectar cierre y lanzar error
  // (NO retornar [] silenciosamente)
  let caughtError = null;
  try {
    await readPromise;
  } catch (err) {
    caughtError = err;
  }

  assert.ok(
    caughtError !== null,
    'readJsonAcrossGroups MUST throw error when track closes before deadline. ' +
    'Expected: "Track closed" error. Got: no error (treated as normal completion).'
  );

  assert.ok(
    caughtError.message.includes('Track closed') || caughtError.message.includes('closed'),
    `Error message must indicate track closed. Got: "${caughtError.message}"`
  );

  console.log(`✓ GREEN: Track closure detected and error thrown: ${caughtError.message}`);
});

test('GREEN: Track closure before deadline is ALWAYS an error, not silent normal end', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 3000; // 3s window

  // Start read
  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Immediately close track (well before deadline)
  await new Promise(r => setTimeout(r, 50));
  subscriber.close();

  // Wait for result with safety timeout
  let threwError = false;
  let resultValue = null;

  try {
    resultValue = await Promise.race([
      readPromise,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('readJsonAcrossGroups hung or timeout')), 2000)
      ),
    ]);
  } catch (err) {
    if (!err.message.includes('hung') && !err.message.includes('timeout')) {
      // This is the expected error from track closure
      threwError = true;
    } else {
      // readJsonAcrossGroups didn't complete and didn't throw - it hung
      throw new Error(
        'readJsonAcrossGroups hung or timed out instead of detecting track closure. ' +
        'Bug: undefined handling needs fixing.'
      );
    }
  }

  assert.ok(
    threwError,
    'When track closes before deadline, readJsonAcrossGroups MUST throw error. ' +
    `Got: no error, returned: ${JSON.stringify(resultValue)}`
  );

  console.log(`✓ GREEN: Early track closure properly detected as error (not silent return)`);
});
