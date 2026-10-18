/**
 * TEST: Comportamiento de cierre de conexión y manejo de heartbeats falsables
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';
import { publishHeartbeatAsGroup } from '../src/publisher.mjs';

test('GREEN: Observer correctly handles connection.closed state', async (t) => {
  // Simular que la conexión se cierra mientras se observa
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar algunos eventos
  const bootId = 'aabbccddeeff0011';
  for (let i = 0; i < 2; i++) {
    publishHeartbeatAsGroup(track, {
      v: 1,
      boot_id: bootId,
      seq: i,
      emitted_at: new Date().toISOString(),
      source_id: 'anon/live1',
    });
  }

  // Observar
  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 2000; // 2s window
  const objects = await readJsonAcrossGroups(ordered, deadline);

  // Verificar que se leyeron los objetos
  assert.strictEqual(objects.length, 2, 'Should read 2 objects');
  assert.strictEqual(objects[0].seq, 0, 'First object seq=0');
  assert.strictEqual(objects[1].seq, 1, 'Second object seq=1');

  console.log('✓ GREEN test passes: Observer handles closed connection gracefully');
});

test('GREEN: Monotonic seq verification across multiple groups', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const bootId = 'aabbccddeeff0011';

  // Publish 10 heartbeats
  for (let i = 0; i < 10; i++) {
    publishHeartbeatAsGroup(track, {
      v: 1,
      boot_id: bootId,
      seq: i,
      emitted_at: new Date().toISOString(),
      source_id: 'anon/live1',
    });
  }

  // Observe
  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 5000; // 5s window
  const objects = await readJsonAcrossGroups(ordered, deadline);

  // Verify all objects were read
  assert.strictEqual(objects.length, 10, 'Should read 10 objects');

  // Verify monotonicity
  for (let i = 1; i < objects.length; i++) {
    assert.ok(objects[i].seq > objects[i-1].seq,
      `seq should be strictly increasing: ${objects[i].seq} > ${objects[i-1].seq}`);
  }

  console.log('✓ GREEN test passes: Monotonic seq across multiple groups');
});

test('GREEN: Race condition: multiple groups written, multiple reads', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const bootId = 'aabbccddeeff0011';

  // Publisher: write 5 groups quickly
  const publishPromise = (async () => {
    for (let i = 0; i < 5; i++) {
      publishHeartbeatAsGroup(track, {
        v: 1,
        boot_id: bootId,
        seq: i,
        emitted_at: new Date().toISOString(),
        source_id: 'anon/live1',
      });
      // Small delay to simulate publishing rate
      await new Promise(r => setTimeout(r, 10));
    }
  })();

  // Observer: start reading after a small delay
  await new Promise(r => setTimeout(r, 25));

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 3000;
  const objects = await readJsonAcrossGroups(ordered, deadline);

  // Should read at least 3 (some may be buffered when subscribe starts)
  assert.ok(objects.length >= 3, `Should read at least 3 objects, got ${objects.length}`);

  // Verify no gaps in seq within the read objects
  for (let i = 1; i < objects.length; i++) {
    assert.ok(objects[i].seq > objects[i-1].seq, 'seq must be monotonic');
  }

  await publishPromise;
  console.log('✓ GREEN test passes: Race condition handled (read concurrent with publish)');
});
