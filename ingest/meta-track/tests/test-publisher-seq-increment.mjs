#!/usr/bin/env node

/**
 * RED TEST: Publisher real seq increment 0,1,2,3...
 * Will FAIL if seq:seq++ is changed to seq:0 or if seq is not incremented
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { publishHeartbeats } from '../src/publisher.mjs';

test('RED: publishHeartbeats emits actual seq 0,1,2,3... in real loop', async (t) => {
  const captured = [];

  class TrackCapture {
    appendGroup() {
      return {
        writeJson: (obj) => {
          captured.push(obj.seq);
          return this;
        },
        close: () => {},
      };
    }
  }

  let attempts = 0;
  const mockConnect = async () => {
    attempts++;
    if (attempts > 2) throw new Error('Too many connection attempts');
    return {
      closed: new Promise(() => {}),  // Never closes
      close: () => {},
    };
  };

  let waits = 0;
  const mockTimer = {
    wait: async () => {
      waits++;
      if (waits > 10) throw new Error('Too many waits');
    }
  };

  try {
    await publishHeartbeats({
      connect: mockConnect,
      track: new TrackCapture(),
      timer: mockTimer,
      maxPublishes: 5,
    });
  } catch (e) {
    // OK
  }

  // CRITICAL ASSERTION: seq must be [0,1,2,3,4]
  assert.deepEqual(captured, [0, 1, 2, 3, 4],
    `seq must increment: expected [0,1,2,3,4], got [${captured}]`);

  console.log(`✓ Real seq verified: [${captured}]`);
});
