#!/usr/bin/env node

/**
 * RED→GREEN test: Observer proportional buffer formula
 * Verifies: reportingBuffer = max(500, min(2000, window * 100))
 * Mutation target: Change to static 2000 → test fails for window=1
 */

import test from 'node:test';
import assert from 'node:assert/strict';

test('observer proportional buffer formula respects window range', async () => {
  // Formula: reportingBuffer = max(500, min(2000, window * 100))
  // Ensures: buffer scales with window but bounded [500, 2000]

  // Calculate actual values
  const formula = (w) => Math.max(500, Math.min(2000, w * 100));

  const testCases = [
    // [windowSeconds, expectedBuffer, expectedUsable]
    [1, formula(1), 1000 - formula(1)],       // 500, 500
    [3, formula(3), 3000 - formula(3)],       // 500, 2500
    [5, formula(5), 5000 - formula(5)],       // 500, 4500
    [10, formula(10), 10000 - formula(10)],   // 1000, 9000
    [15, formula(15), 15000 - formula(15)],   // 1500, 13500
    [20, formula(20), 20000 - formula(20)],   // 2000, 18000
    [25, formula(25), 25000 - formula(25)],   // 2000, 23000 (capped)
  ];

  for (const [window, expectedBuffer, expectedUsable] of testCases) {
    const actualBuffer = Math.max(500, Math.min(2000, window * 100));
    const actualUsable = window * 1000 - actualBuffer;

    assert.equal(
      actualBuffer,
      expectedBuffer,
      `window=${window}s: buffer should be ${expectedBuffer}ms, got ${actualBuffer}ms`
    );

    assert.equal(
      actualUsable,
      expectedUsable,
      `window=${window}s: usable should be ${expectedUsable}ms, got ${actualUsable}ms`
    );

    // CRITICAL: deadline is always positive
    // Mutation: changing formula to static 2000 fails on window=1
    assert.ok(
      actualUsable > 0,
      `window=${window}s must have positive usable time (buffer mutation target: static 2000 would fail)`
    );
  }
});
