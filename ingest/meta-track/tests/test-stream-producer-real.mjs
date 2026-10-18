/**
 * Test: Stream.Producer.append(value) with fake track
 *
 * Verifica que append() acepta UN argumento y genera timestamp internamente
 */

import { Stream } from '@moq/json';
import * as Moq from '@moq/net';

export function testAppendValueOnly() {
  console.log('[TEST] testAppendValueOnly');

  // Create real origin and track
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test-broadcast'));
  const track = broadcast.createTrack('test-track', {
    timescale: 1000,
    maxAge: 60000,
  });

  const producer = new Stream.Producer({ track });

  // Test append with value only (no pts argument)
  const heartbeat = {
    v: 1,
    boot_id: 'aabbccddeeff0011',
    seq: 1,
    emitted_at: new Date().toISOString(),
    source_id: 'anon/live1',
  };

  try {
    // Should work with one argument only
    producer.append(heartbeat);
    console.log('  ✓ append(value) succeeds (no pts needed)');

    // Try a few more
    for (let i = 2; i <= 5; i++) {
      producer.append({ ...heartbeat, seq: i });
    }
    console.log('  ✓ Multiple appends work');

    producer.finish();
    console.log('  ✓ finish() succeeds');

  } catch (err) {
    throw new Error(`append() failed: ${err.message}`);
  }

  console.log('[PASS] testAppendValueOnly');
}

export function testAppendThrowsOnInvalidValue() {
  console.log('[TEST] testAppendThrowsOnInvalidValue');

  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test2'));
  const track = broadcast.createTrack('data', { timescale: 1000 });
  const producer = new Stream.Producer({ track });

  // Invalid value (not JSON-serializable)
  const circular = {};
  circular.self = circular; // circular reference

  try {
    producer.append(circular);
    throw new Error('Should have thrown on circular reference');
  } catch (err) {
    if (err.message.includes('Should have thrown')) throw err;
    // Expected: encoding error
    console.log('  ✓ append() throws on non-serializable value');
  }

  console.log('[PASS] testAppendThrowsOnInvalidValue');
}

// Run tests
const tests = [
  testAppendValueOnly,
  testAppendThrowsOnInvalidValue,
];

async function runTests() {
  for (const test of tests) {
    try {
      await test();
    } catch (err) {
      console.error(`[FAIL] ${test.name}: ${err.message}`);
      process.exit(1);
    }
  }
  console.log('\n[SUCCESS] All Stream.Producer append() real tests passed');
}

runTests().catch((err) => {
  console.error('[FATAL]', err);
  process.exit(1);
});
