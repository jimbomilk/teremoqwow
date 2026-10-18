/**
 * RED test: Publisher maxPublishes should close connection before exiting
 * Contract: When maxPublishes is reached, connection.close() is called
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { publishHeartbeats } from '../src/publisher.mjs';

test('publisher should close connection when maxPublishes reached', async () => {
  let closeCalled = false;
  let publishCount = 0;

  const mockConnect = async (options) => {
    return {
      closed: new Promise(() => {}), // never resolves
      close: () => {
        closeCalled = true;
      },
    };
  };

  const mockOrigin = {
    consume: () => ({}),
  };

  const mockTrack = {
    appendGroup: () => ({
      writeJson: () => {
        publishCount++;
      },
      close: () => {},
    }),
  };

  const mockTimer = {
    wait: async () => {
      // Only call timer twice then throw to force exit
      if (publishCount >= 2) {
        throw new Error('Force exit');
      }
    },
  };

  try {
    await publishHeartbeats({
      connect: mockConnect,
      origin: mockOrigin,
      track: mockTrack,
      timer: mockTimer,
      maxPublishes: 2,
    });
  } catch (e) {
    // Expected to throw on force exit
  }

  // CRITICAL: close must have been called when maxPublishes is reached
  // Current code: line 226 breaks WITHOUT calling close first (BUG)
  assert.ok(closeCalled, 'connection.close() should be called on maxPublishes limit');
  assert.equal(publishCount, 2, 'should have published exactly maxPublishes times');
});
