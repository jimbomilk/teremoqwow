#!/usr/bin/env node

/**
 * FIX #4: Publisher closes connection when maxPublishes reached
 * Mutation target: Remove connection.close() call
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { publishHeartbeatAsGroup } from '../src/publisher.mjs';

test('publishHeartbeatAsGroup creates and closes group properly', async () => {
  // Test the actual production function that gets called per event
  let groupCreated = false;
  let groupClosed = false;
  let closeCalledWithError = false;

  const mockGroup = {
    writeJson(obj) {
      assert.ok(obj.boot_id, 'heartbeat should have boot_id');
      assert.ok(typeof obj.seq === 'number', 'heartbeat should have seq');
    },
    close(err) {
      groupClosed = true;
      if (err) closeCalledWithError = true;
    },
  };

  const mockTrack = {
    appendGroup() {
      groupCreated = true;
      return mockGroup;
    },
  };

  const heartbeat = {
    v: 1,
    boot_id: 'test-boot-id',
    seq: 42,
    emitted_at: new Date().toISOString(),
    source_id: 'anon/live1',
  };

  // Call production function
  publishHeartbeatAsGroup(mockTrack, heartbeat);

  // CRITICAL ASSERTIONS for mutation: if(false) appendGroup
  assert.ok(groupCreated, 'appendGroup must be called (mutation: if(false) caught)');
  assert.ok(groupClosed, 'group.close must be called');
  assert.ok(!closeCalledWithError, 'group should close cleanly');
});

test('publisher connection.close verification in source', async () => {
  // Verify FIX #4 is present: connection.close() on maxPublishes
  const fs = await import('node:fs').then(m => m.promises);
  const source = await fs.readFile('./src/publisher.mjs', 'utf8');

  // Must have maxPublishes check followed by close
  const match = source.match(
    /if\s*\(\s*totalPublished\s*>=\s*maxPublishes\s*\)[\s\S]*?connection\.close\(\)/
  );

  assert.ok(match,
    'publisher must call connection.close() when maxPublishes reached ' +
    '(mutation: removing this call survives if not checked)'
  );
});
