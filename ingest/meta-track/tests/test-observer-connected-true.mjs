#!/usr/bin/env node

/**
 * RED TEST for H3: Observer emits connected:true on successful collection
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { observeTrack } from '../src/observer.mjs';

test('H3: Observer emits connected:true when successfully collecting objects', async (t) => {
  const results = [];
  let groupSeq = 0;
  const observeWindow = 2;  // 2 second window

  // Create a mock origin with proper MoQ API
  const mockOrigin = {
    request: () => {
      const mockTrack = {
        subscribe: () => {
          return {
            ordered: () => {
              const startTime = Date.now();
              const trackDeadline = startTime + (observeWindow * 1000) + 1000;  // Track stays open longer than window

              return {
                nextGroup: async () => {
                  // Keep returning groups until deadline
                  if (Date.now() >= trackDeadline) {
                    return undefined;  // Track closed at deadline
                  }

                  // Return a new group with objects
                  const seq = groupSeq++;
                  return {
                    callCount: 0,
                    readJson: async function() {
                      this.callCount++;
                      if (this.callCount === 1) {
                        return { seq, boot_id: 'boot1' };
                      }
                      return undefined;  // Group exhausted
                    },
                  };
                },
                closed: new Promise(() => {}),  // Never resolves
              };
            },
          };
        },
      };

      const mockActive = {
        track: () => mockTrack,
        peek: () => mockActive,  // Return self to indicate active broadcast exists
        changed: () => new Promise(() => {}),  // Never resolves
      };

      return {
        active: mockActive,
      };
    },
  };

  // Mock connect
  const mockConnect = async () => {
    return { close: () => {} };
  };

  const captureResult = (result) => {
    results.push(result);
  };

  try {
    await observeTrack({
      connect: mockConnect,
      origin: mockOrigin,
      window: observeWindow,
      onResult: captureResult,
    });
  } catch (e) {
    console.error(`Observer threw: ${e.message}`);
  }

  console.log(`Results: ${JSON.stringify(results)}`);

  // CRITICAL ASSERTION
  assert.ok(results.length > 0, 'Should emit at least one result');

  const result = results[0];
  console.log(`Result: ${JSON.stringify(result)}`);

  assert.equal(result.connected, true,
    `Should emit connected:true on success; got ${result.connected}`);

  assert.equal(result.monotonic, true,
    `With monotonic sequence [0,1,2,...], monotonic must be true; got ${result.monotonic}`);

  assert.ok(result.objects > 0,
    `Should have collected objects; got ${result.objects}`);
});
