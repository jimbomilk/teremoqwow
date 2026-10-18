#!/usr/bin/env node

/**
 * H3: Observer detects non-monotonic sequences and reports failure
 * Verifies monotonic:false is emitted when seq decreases or repeats within boot_id
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { observeTrack } from '../src/observer.mjs';

test('H3: Observer reports monotonic:false on duplicate/decreasing seq', async (t) => {
  const results = [];
  const observeWindow = 2;

  const mockOrigin = {
    request: () => {
      let groupSeq = 0;
      const startTime = Date.now();
      const trackDeadline = startTime + (observeWindow * 1000) + 1000;

      const mockTrack = {
        subscribe: () => {
          return {
            ordered: () => {
              return {
                nextGroup: async () => {
                  // Keep emitting groups until deadline
                  if (Date.now() >= trackDeadline) {
                    return undefined;
                  }

                  // First 4 groups: [0, 1, 1, 2] (non-monotonic: duplicate 1)
                  // After that: keep emitting groups to extend track past deadline
                  const groupNum = groupSeq++;

                  if (groupNum < 4) {
                    // Non-monotonic sequence
                    const seqValues = [0, 1, 1, 2];
                    const seq = seqValues[groupNum];

                    return {
                      callCount: 0,
                      readJson: async function() {
                        this.callCount++;
                        if (this.callCount === 1) {
                          return { seq, boot_id: 'boot1' };
                        }
                        return undefined;
                      },
                    };
                  } else {
                    // Extra groups with monotonic sequence to extend track
                    const seq = groupNum;

                    return {
                      callCount: 0,
                      readJson: async function() {
                        this.callCount++;
                        if (this.callCount === 1) {
                          return { seq, boot_id: 'boot1' };
                        }
                        return undefined;
                      },
                    };
                  }
                },
                closed: new Promise(() => {}),
              };
            },
          };
        },
      };

      const mockActive = {
        track: () => mockTrack,
        peek: () => mockActive,
        changed: () => new Promise(() => {}),
      };

      return { active: mockActive };
    },
  };

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

  console.log(`H3 Monotonic Test: Results = ${JSON.stringify(results)}`);

  // CRITICAL ASSERTION
  assert.ok(results.length > 0, 'Should emit result');

  const result = results[0];

  // With non-monotonic sequences [0,1,1,2], observer MUST report monotonic:false
  assert.equal(result.monotonic, false,
    `With duplicate seq [0,1,1,2], monotonic must be false; got ${result.monotonic}`);

  // Should have collected objects (at least the 4 from the non-monotonic sequence)
  assert.ok(result.objects >= 4,
    `Should have collected at least 4 objects; got ${result.objects}`);

  // On success collection (window expired), should be connected:true
  // But monotonic:false indicates data integrity issue
  assert.equal(result.connected, true,
    `Collection window completed, so connected should be true; got ${result.connected}`);

  console.log(`✓ H3: Correctly detected non-monotonic seq [0,1,1,2], monotonic=${result.monotonic}, connected=${result.connected}`);
});
