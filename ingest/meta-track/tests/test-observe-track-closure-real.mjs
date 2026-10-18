#!/usr/bin/env node

/**
 * END-TO-END TEST: observeTrack() emits connected:false on track closure
 *
 * Exercises actual observeTrack() function with injected connect/origin.
 * Verifies it emits JSON with connected:false when connection closes during observation.
 *
 * Catches mutation: emit connected:true despite closure
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { observeTrack } from '../src/observer.mjs';

test('observeTrack emits connected:false when connection closes', async (t) => {
  // Mock connection that closes immediately
  const mockConnection = {
    closed: new Promise((resolve) => {
      // Simulate connection closes after 100ms
      setTimeout(() => resolve(new Error('Connection lost')), 100);
    }),
    close() {},
  };

  // Capture emitted result
  let emittedResult = null;
  const onResult = (result) => {
    emittedResult = result;
  };

  // Mock connect that returns our fake connection
  const mockConnect = async () => mockConnection;

  // Mock origin
  const mockOrigin = {
    request: () => ({
      active: {
        peek: () => null,
        changed: () => Promise.resolve(),
      },
    }),
  };

  // Run observeTrack with injected deps
  await observeTrack({
    connect: mockConnect,
    origin: mockOrigin,
    window: 2,  // 2 second observation window
    onResult: onResult,
  });

  // CRITICAL ASSERTION: Must emit connected:false on closure
  // Mutation: emit connected:true despite closure → FAILS HERE ✓
  assert.ok(emittedResult, 'should emit result JSON');
  assert.equal(emittedResult.connected, false,
    `must emit connected:false on closure, got connected:${emittedResult.connected}`);
  assert.equal(emittedResult.window_seconds, 2, 'should use injected window');
});
