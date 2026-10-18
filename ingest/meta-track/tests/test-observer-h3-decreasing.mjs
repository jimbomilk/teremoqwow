#!/usr/bin/env node

/**
 * H3 CORRECT: Mutation seqs[i] <= seqs[i-1] -> seqs[i] === seqs[i-1] should FAIL
 * Real decreasing sequence [0,2,1,3,4...] must be detected as non-monotonic
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { observeTrack } from '../src/observer.mjs';

test('H3: Observer detects decreasing seq (not just duplicates)', async (t) => {
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
                  if (Date.now() >= trackDeadline) {
                    return undefined;
                  }

                  const groupNum = groupSeq++;

                  // First 5 groups: decreasing [0,2,1,3,4] (0->2 OK, 2->1 NOT OK, 1->3 OK, 3->4 OK)
                  // Sequence 2->1 is DECREASING, should fail monotonic check
                  const seqValues = [0, 2, 1, 3, 4];

                  if (groupNum < seqValues.length) {
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
                    // Continue with monotonic sequence after
                    const seq = 5 + (groupNum - seqValues.length);
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

  console.log(`H3 Decreasing: ${JSON.stringify(results)}`);

  // CRITICAL ASSERTION
  assert.ok(results.length > 0, 'Should emit result');

  const result = results[0];

  // With decreasing sequence [0,2,1,3,4], 2->1 is a decrease
  // Monotonic check: seqs[i] <= seqs[i-1] means "not increasing" = NOT monotonic
  // If mutation changes to seqs[i] === seqs[i-1], it only catches duplicates
  // The 2->1 decrease would NOT be caught by the mutation

  assert.equal(result.monotonic, false,
    `Decreasing sequence [0,2,1,3,4] must have monotonic:false; got ${result.monotonic}`);

  console.log(`✓ H3: Correctly detected decrease 2->1, monotonic=${result.monotonic}`);
});
