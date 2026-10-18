/**
 * RED TEST: El observador debe iterar sobre grupos usando nextGroup()
 * y leer JSON de cada uno.
 *
 * Este es el patrón correcto que el observer.mjs debe usar.
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';

async function readAllJsonFromTrack(ordered, windowSeconds = 20) {
  /**
   * Lee todos los objetos JSON disponibles en un track usando el patrón:
   * nextGroup() → readJson() en loop → siguiente grupo
   *
   * Retorna array de objetos
   */
  const objects = [];
  const deadline = Date.now() + windowSeconds * 1000;

  while (Date.now() < deadline) {
    const timeRemaining = deadline - Date.now();
    if (timeRemaining <= 0) break;

    try {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('nextGroup timeout')), timeRemaining)
      );

      const group = await Promise.race([
        ordered.nextGroup(),
        timeoutPromise,
      ]);

      if (!group) {
        // No more groups available right now
        break;
      }

      // Read all frames (JSON objects) from this group
      let obj;
      while ((obj = await group.readJson()) !== undefined) {
        objects.push(obj);
      }
    } catch (err) {
      if (err.message === 'nextGroup timeout') {
        // Window expired
        break;
      }
      // Other error: break
      throw err;
    }
  }

  return objects;
}

test('RED: Observer correctly reads JSON from multiple groups using nextGroup pattern', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const bootId = 'aabbccddeeff0011';

  // PUBLISHER: Create 3 groups, 1 heartbeat each
  for (let i = 0; i < 3; i++) {
    const group = track.appendGroup();
    group.writeJson({
      v: 1,
      boot_id: bootId,
      seq: i,
      emitted_at: new Date().toISOString(),
      source_id: 'anon/live1',
    });
    group.close();
  }

  // OBSERVER: Read all JSON
  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const objects = await readAllJsonFromTrack(ordered, 5); // 5s window

  assert.strictEqual(objects.length, 3, 'Should read 3 objects');
  assert.strictEqual(objects[0].seq, 0, 'First: seq=0');
  assert.strictEqual(objects[1].seq, 1, 'Second: seq=1');
  assert.strictEqual(objects[2].seq, 2, 'Third: seq=2');

  // Verify monotonicity
  for (let i = 1; i < objects.length; i++) {
    assert.ok(objects[i].seq > objects[i-1].seq, `seq should be monotonic: ${objects[i].seq} > ${objects[i-1].seq}`);
  }

  console.log('✓ RED test passes: nextGroup+readJson pattern correctly reads multiple groups');
});

// Export the helper for use in observer.mjs
export { readAllJsonFromTrack };
