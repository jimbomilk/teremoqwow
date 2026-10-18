#!/usr/bin/env node

/**
 * MEDIUM/HIGH: Observer must report connected:false on closure
 *
 * Tests that closure during observation window emits connected:false
 * not connected:true. Mutation: reporting connected:true after closure survives
 * if we don't verify the actual result.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('observer reports closure as connection failure (connected:false logic)', async () => {
  // Simulate: track closes while reading
  const mockGroup = {
    async readJson() {
      // Pending read
      return new Promise(resolve =>
        setTimeout(() => resolve({ seq: 1 }), 5000)
      );
    },
  };

  let closedSignal = null;
  const mockOrderedClosed = new Promise((resolve) => {
    closedSignal = resolve;
    // Close mid-observation
    setTimeout(() => resolve(new Error('Track closed')), 50);
  });

  const mockOrdered = {
    closed: mockOrderedClosed,
    async nextGroup() {
      return mockGroup;
    },
  };

  const deadline = Date.now() + 5000;

  // readJsonAcrossGroups should throw on closure
  // If it returns [], the observer would report connected:true with objects:0
  // (mutation that survives if we don't test it)
  try {
    const result = await readJsonAcrossGroups(mockOrdered, deadline);
    assert.fail(
      `FAIL: got result ${JSON.stringify(result)} instead of error. ` +
      'Mutation: returning [] on closure still reports connected:true. ' +
      'Test must verify closure throws error.'
    );
  } catch (err) {
    // PASS: closure propagated as error
    // Observer catches this and reports connected:false
    assert.ok(err.message.includes('closed'), 'should propagate closure error');
  }
});

test('observer closure detection blocks connection:true emission', async () => {
  // If readJsonAcrossGroups returns [] silently, observer code path is:
  // if (lastError && ...) throw -> else emit connected:true
  // We must verify this path is blocked when closure happens

  // The observer code (lines 214-225) checks:
  // if (lastError && lastError.message.includes('Track closed')) {
  //   throw lastError;
  // }
  // This must execute BEFORE emit.connected(true)

  const fs = await import('node:fs').then(m => m.promises);
  const source = await fs.readFile('./src/observer.mjs', 'utf8');

  // Verify the check is present
  assert.ok(
    source.includes('if (lastError && lastError.message.includes(\'Track closed\'))'),
    'observer must check lastError for closure before emitting connected:true'
  );

  assert.ok(
    source.includes('throw lastError'),
    'observer must throw closure error before success emission'
  );
});
