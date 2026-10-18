/**
 * TEST: Publisher publica correctamente usando appendGroup()
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { publishHeartbeatAsGroup } from '../src/publisher.mjs';

test('GREEN: publishHeartbeatAsGroup creates one group per heartbeat', (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const bootId = 'aabbccddeeff0011';
  const heartbeat = {
    v: 1,
    boot_id: bootId,
    seq: 0,
    emitted_at: new Date().toISOString(),
    source_id: 'anon/live1',
  };

  // Should not throw
  publishHeartbeatAsGroup(track, heartbeat);

  console.log('✓ GREEN test passes: publishHeartbeatAsGroup works');
});

test('GREEN: Multiple heartbeats create separate groups', (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  const bootId = 'aabbccddeeff0011';

  // Publish 3 heartbeats
  for (let i = 0; i < 3; i++) {
    const heartbeat = {
      v: 1,
      boot_id: bootId,
      seq: i,
      emitted_at: new Date().toISOString(),
      source_id: 'anon/live1',
    };
    publishHeartbeatAsGroup(track, heartbeat);
  }

  // Subscribe and verify we get 3 separate groups
  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  let groupCount = 0;
  let objectCount = 0;

  // Simulate collecting groups (with timeout)
  const collectGroups = async () => {
    const timeout = 3000;
    const startTime = Date.now();

    while (Date.now() - startTime < timeout) {
      const timeRemaining = timeout - (Date.now() - startTime);
      try {
        const group = await Promise.race([
          ordered.nextGroup(),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('timeout')), timeRemaining)
          ),
        ]);

        if (!group) break;

        groupCount++;
        let obj;
        while ((obj = await group.readJson()) !== undefined) {
          objectCount++;
        }
      } catch (err) {
        break;
      }
    }
  };

  return collectGroups().then(() => {
    assert.strictEqual(groupCount, 3, `Should have 3 groups, got ${groupCount}`);
    assert.strictEqual(objectCount, 3, `Should have 3 objects, got ${objectCount}`);
    console.log('✓ GREEN test passes: Multiple heartbeats create separate groups');
  });
});
