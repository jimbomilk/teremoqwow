/**
 * RED TEST SIMPLE: Verifica que appendGroup() + writeJson() + close() funciona
 * sin bloquear el event loop
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';

test('RED: appendGroup creates separate groups that can be closed', (t) => {
  // Setup: create a track
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Create two groups
  const group1 = track.appendGroup();
  assert.ok(group1, 'appendGroup() should return a GroupProducer');
  assert.strictEqual(group1.sequence, 0, 'First group should have sequence 0');

  group1.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 0 });
  assert.ok(!group1.isClosed, 'Group should not be closed after writeJson');

  group1.close();
  assert.ok(group1.isClosed, 'Group should be closed after close()');

  // Create second group
  const group2 = track.appendGroup();
  assert.ok(group2, 'appendGroup() should return a GroupProducer');
  assert.strictEqual(group2.sequence, 1, 'Second group should have sequence 1');

  group2.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 1 });
  group2.close();
  assert.ok(group2.isClosed, 'Second group should be closed after close()');

  console.log('✓ RED test passes: appendGroup creates separate groups');
});
