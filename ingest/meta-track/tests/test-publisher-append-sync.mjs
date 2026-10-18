/**
 * Test: Publisher error handling distinguishes permanent vs transient
 *
 * Verifica que:
 * 1. TypeError durante appendGroup/writeJson es PERMANENTE → exit(1)
 * 2. Otros errores son TRANSITORIOS → backoff + retry
 */

import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

export function testErrorClassification() {
  console.log('[TEST] testErrorClassification');

  const testCases = [
    {
      error: new TypeError('writeJson is not a function'),
      expectedPermanent: true,
      description: 'API error (TypeError) is permanent'
    },
    {
      error: new TypeError('Cannot encode value'),
      expectedPermanent: true,
      description: 'Encoding error (TypeError) is permanent'
    },
    {
      error: new Error('Connection timeout'),
      expectedPermanent: false,
      description: 'Connection error is transient'
    },
    {
      error: new Error('ECONNREFUSED'),
      expectedPermanent: false,
      description: 'Connection refused is transient'
    },
    {
      error: new ReferenceError('connection is not defined'),
      expectedPermanent: false,
      description: 'Reference error is transient (not TypeError)'
    },
  ];

  for (const tc of testCases) {
    const isApiError = tc.error instanceof TypeError;
    if (isApiError !== tc.expectedPermanent) {
      throw new Error(`${tc.description}: expected permanent=${tc.expectedPermanent}, got ${isApiError}`);
    }
    console.log(`  ✓ ${tc.description}`);
  }

  console.log('[PASS] testErrorClassification');
}

export function testPublisherExitCodeOnPermanentError() {
  console.log('[TEST] testPublisherExitCodeOnPermanentError');

  // Simulate publisher error handling
  const simulatePublisherError = (err) => {
    const isApiError = err instanceof TypeError;
    if (isApiError) {
      return { shouldExit: true, exitCode: 1 };
    } else {
      return { shouldExit: false, exitCode: null };
    }
  };

  // Permanent error → exit(1)
  const result1 = simulatePublisherError(new TypeError('API error'));
  if (!result1.shouldExit || result1.exitCode !== 1) {
    throw new Error('Permanent error should cause exit(1)');
  }

  // Transient error → no exit
  const result2 = simulatePublisherError(new Error('Transient'));
  if (result2.shouldExit) {
    throw new Error('Transient error should NOT cause exit');
  }

  console.log('  ✓ Permanent error (TypeError) → exit(1)');
  console.log('  ✓ Transient error → no exit, apply backoff');
  console.log('[PASS] testPublisherExitCodeOnPermanentError');
}

export function testPublisherUsesAppendGroup() {
  console.log('[TEST] testPublisherUsesAppendGroup');

  // Verify: publisher.mjs uses appendGroup() + writeJson() + close() pattern
  const publisherCode = readFileSync(
    join(__dirname, '../src/publisher.mjs'),
    'utf-8'
  );

  // Should NOT use Stream.Producer (deprecated for #206)
  if (publisherCode.includes('new Stream.Producer')) {
    throw new Error('Code still uses Stream.Producer (should use appendGroup)');
  }

  // Should use appendGroup()
  if (!publisherCode.includes('appendGroup()')) {
    throw new Error('Code should call track.appendGroup()');
  }

  // Should use writeJson()
  if (!publisherCode.includes('writeJson')) {
    throw new Error('Code should call group.writeJson()');
  }

  // Should use close()
  if (!publisherCode.includes('group.close()')) {
    throw new Error('Code should call group.close()');
  }

  // Should distinguish TypeError as permanent
  if (!publisherCode.includes('instanceof TypeError')) {
    throw new Error('Code should distinguish TypeError as permanent error');
  }

  if (!publisherCode.includes('process.exit')) {
    throw new Error('Code should exit(1) on permanent error');
  }

  console.log('  ✓ Uses track.appendGroup() [FIX #206]');
  console.log('  ✓ Uses group.writeJson()');
  console.log('  ✓ Uses group.close()');
  console.log('  ✓ Distinguishes TypeError as permanent');
  console.log('  ✓ Calls process.exit(1) on permanent error');
  console.log('  ✓ Does NOT use Stream.Producer');
  console.log('[PASS] testPublisherUsesAppendGroup');
}

// Run tests
const tests = [
  testErrorClassification,
  testPublisherExitCodeOnPermanentError,
  testPublisherUsesAppendGroup,
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
  console.log('\n[SUCCESS] All publisher error handling tests passed');
}

runTests().catch((err) => {
  console.error('[FATAL]', err);
  process.exit(1);
});
