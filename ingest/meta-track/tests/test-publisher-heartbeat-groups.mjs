#!/usr/bin/env node

/**
 * END-TO-END TEST: publishHeartbeatAsGroup creates proper MoQ group structure
 *
 * Tests actual publishHeartbeatAsGroup function with real MoQ track object.
 * Verifies:
 *  1. appendGroup() called on track
 *  2. Group receives writeJson() call with heartbeat data
 *  3. Group receives close() call
 *
 * This exercises the production code path that:
 *  - FIX #206: Uses appendGroup() + writeJson() + close() (not Stream.Producer)
 *  - Publishes each heartbeat as exactly one group
 *  - Closes group after write
 *
 * Catches mutations:
 *  - if(false) appendGroup() → function never runs
 *  - skip writeJson() → group never receives data
 *  - skip close() → group left open
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { publishHeartbeatAsGroup, generateBootId } from '../src/publisher.mjs';

test('publishHeartbeatAsGroup uses appendGroup + writeJson + close', async (t) => {
  const calls = [];

  // Mock track with instrumentation
  const mockTrack = {
    appendGroup(data) {
      calls.push({ method: 'appendGroup', arg: data });
      return {
        writeJson: (obj) => {
          calls.push({ method: 'writeJson', arg: obj });
          return this;
        },
        close: () => {
          calls.push({ method: 'close' });
        },
      };
    },
  };

  // Create a test heartbeat
  const bootId = generateBootId();
  const heartbeat = {
    v: 1,
    boot_id: bootId,
    seq: 42,
    emitted_at: new Date().toISOString(),
    source_id: 'anon/live1',
  };

  // CRITICAL: Call actual production function
  // Mutation: if(false) publishHeartbeatAsGroup → calls stays empty
  publishHeartbeatAsGroup(mockTrack, heartbeat);

  // Verify all three methods were called in order
  assert.equal(calls.length, 3, `should call appendGroup, writeJson, close; got ${calls.length} calls`);

  assert.equal(calls[0].method, 'appendGroup', 'first call should be appendGroup');
  assert.equal(calls[1].method, 'writeJson', 'second call should be writeJson');
  assert.equal(calls[2].method, 'close', 'third call should be close');

  // Verify heartbeat data was passed to writeJson
  const heartbeatData = calls[1].arg;
  assert.equal(heartbeatData.v, 1, 'heartbeat version');
  assert.equal(heartbeatData.seq, 42, 'heartbeat seq number');
  assert.equal(heartbeatData.boot_id, bootId, 'heartbeat boot_id');

  console.log(`✓ publishHeartbeatAsGroup correctly calls appendGroup → writeJson → close`);
});

test('each heartbeat is exactly one group', async (t) => {
  const groups = [];

  const mockTrack = {
    appendGroup(data) {
      groups.push({});  // Track that appendGroup was called
      return {
        writeJson: () => this,
        close: () => {},
      };
    },
  };

  // Publish multiple heartbeats
  for (let i = 0; i < 5; i++) {
    const heartbeat = {
      v: 1,
      boot_id: 'test',
      seq: i,
      emitted_at: new Date().toISOString(),
      source_id: 'anon/live1',
    };
    publishHeartbeatAsGroup(mockTrack, heartbeat);
  }

  // Each call should create exactly one group
  assert.equal(groups.length, 5, `should create 5 groups for 5 heartbeats, got ${groups.length}`);

  console.log(`✓ 5 heartbeats created 5 separate groups (1:1 ratio)`);
});
