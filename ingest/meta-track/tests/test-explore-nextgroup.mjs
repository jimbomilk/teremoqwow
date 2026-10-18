/**
 * INVESTIGACIÓN: Cómo leer JSON de múltiples grupos usando nextGroup() + readJson()
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';

test('EXPLORE: Using nextGroup() to read frames from each group', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const bootId = 'aabbccddeeff0011';

  // PUBLISHER: Create two groups
  const group1 = track.appendGroup();
  group1.writeJson({ v: 1, boot_id: bootId, seq: 0 });
  group1.close();

  const group2 = track.appendGroup();
  group2.writeJson({ v: 1, boot_id: bootId, seq: 1 });
  group2.close();

  // OBSERVER: Use nextGroup() to iterate
  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const objects = [];
  let nextGrp;
  const timeout = 3000;
  const startTime = Date.now();

  // Loop to read groups
  while (Date.now() - startTime < timeout) {
    try {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('nextGroup() timeout')), timeout - (Date.now() - startTime))
      );

      nextGrp = await Promise.race([
        ordered.nextGroup(),
        timeoutPromise,
      ]);

      if (!nextGrp) {
        // No more groups
        break;
      }

      console.log(`Got group ${nextGrp.sequence}`);

      // Read frames from this group
      let frame;
      while ((frame = await nextGrp.readJson()) !== undefined) {
        console.log(`  Frame: ${JSON.stringify(frame)}`);
        objects.push(frame);
      }
    } catch (err) {
      console.error(`Error in nextGroup loop: ${err.message}`);
      break;
    }
  }

  console.log(`Total objects read: ${objects.length}`);
  assert.strictEqual(objects.length, 2, 'Should read 2 objects from 2 groups');
  assert.strictEqual(objects[0].seq, 0, 'First object seq=0');
  assert.strictEqual(objects[1].seq, 1, 'Second object seq=1');

  console.log('✓ EXPLORE test shows nextGroup() + readJson() pattern works');
});
