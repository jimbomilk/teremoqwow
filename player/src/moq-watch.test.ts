// Tests for _fetchCertHash / fetchCertHash (E1-T4).
// Run with: node player/src/moq-watch.test.ts
// Node 24 strips TypeScript types natively; no extra flags needed.

import { fetchCertHash } from './moq-watch.ts';

let passed = 0;
let failed = 0;

function assert(condition: boolean, msg: string): void {
  if (condition) {
    console.log(`  \u2713 ${msg}`);
    passed++;
  } else {
    console.error(`  \u2717 FAIL: ${msg}`);
    failed++;
  }
}

// test_fetchCertHash_uses_endpoint
console.log('\n=== test_fetchCertHash_uses_endpoint ===');
{
  const mockFetch = async (_url: string) =>
    ({ ok: true, json: async () => ({ cert_hash: 'abc123def456' }) }) as any;
  (globalThis as any).fetch = mockFetch;
  const result = await fetchCertHash(() => null);
  assert(result === 'abc123def456', 'returns hash from /cert-hash endpoint');
}

// test_fetchCertHash_fallback_to_attribute
console.log('\n=== test_fetchCertHash_fallback_to_attribute ===');
{
  const mockFetch = async (_url: string): Promise<never> => { throw new Error('Network error'); };
  (globalThis as any).fetch = mockFetch;
  const result = await fetchCertHash(() => 'fallback-hash-xyz');
  assert(result === 'fallback-hash-xyz', 'falls back to HTML attribute on fetch error');
}

// test_fetchCertHash_empty_graceful
console.log('\n=== test_fetchCertHash_empty_graceful ===');
{
  const mockFetch = async (_url: string) =>
    ({ ok: false, json: async () => ({}) }) as any;
  (globalThis as any).fetch = mockFetch;
  const result = await fetchCertHash(() => null);
  assert(result === null, 'returns null when endpoint empty and no attribute');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
