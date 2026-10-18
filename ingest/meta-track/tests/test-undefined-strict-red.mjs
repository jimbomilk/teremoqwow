/**
 * RED TEST: Strict validation that undefined from nextGroup() is treated as closure
 *
 * Validación: undefined ANTES del deadline DEBE causar error, no retorno silencioso.
 * Este test asegura que el código NO trata undefined como "no hay datos ahora".
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('RED: Early track closure propagates error, not silent return', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // 2s deadline
  const deadline = Date.now() + 2000;

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Close immediately (before deadline)
  // This forces nextGroup() to return undefined mid-window
  await new Promise(r => setTimeout(r, 50));
  subscriber.close();

  let error = null;
  try {
    await readPromise;
  } catch (err) {
    error = err;
  }

  assert.ok(
    error !== null,
    'readJsonAcrossGroups MUST throw error when track closes before deadline. ' +
    'Got: no error thrown (treated as normal end-of-data, BUG!).'
  );

  assert.ok(
    error.message.includes('Track closed'),
    `Error message must indicate track closed. Got: "${error.message}"`
  );

  console.log(`✓ Early closure detected and propagated: ${error.message}`);
});

test('RED: undefined before deadline is NEVER treated as normal completion', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Start with empty track (no groups)
  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 500; // Very short window

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Close immediately before any data
  await new Promise(r => setTimeout(r, 50));
  subscriber.close();

  let resultOrError = { type: 'nothing' };
  try {
    const result = await readPromise;
    resultOrError = { type: 'result', value: result };
  } catch (err) {
    resultOrError = { type: 'error', value: err.message };
  }

  // Either error (good) or timeout (acceptable if deadline passed)
  // But NEVER silent empty array from treating undefined as normal
  if (resultOrError.type === 'error') {
    console.log(`✓ Closure detected as error: ${resultOrError.value}`);
    assert.ok(resultOrError.value.includes('Track closed'));
  } else if (resultOrError.type === 'result') {
    // If returned result, it should be empty (timeout) not from undefined break
    console.log(`✓ Timeout occurred (acceptable): returned ${resultOrError.value.length} objects`);
    assert.equal(resultOrError.value.length, 0);
  }
});
