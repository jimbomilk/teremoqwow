// Run with: node player/src/metrics.test.ts
// Node 24 strips TypeScript types natively; no extra flags needed.
import { CircularBuffer, percentile } from './metrics.ts';

let passed = 0;
let failed = 0;

function assert(condition: boolean, msg: string): void {
  if (condition) {
    console.log(`  ✓ ${msg}`);
    passed++;
  } else {
    console.error(`  ✗ FAIL: ${msg}`);
    failed++;
  }
}

function assertClose(a: number, b: number, msg: string, tol = 0.5): void {
  assert(Math.abs(a - b) <= tol, `${msg} (got ${a.toFixed(2)}, expected ${b})`);
}

// ── RED ─────────────────────────────────────────────────────────────────────
console.log('\n=== RED: percentile undefined → ReferenceError ===');
{
  // Simulate calling the function before it was imported/defined
  const undefinedFn = (globalThis as Record<string, unknown>)['percentileUndefined'];
  try {
    if (typeof undefinedFn !== 'function') {
      throw new ReferenceError('percentileUndefined is not defined');
    }
    (undefinedFn as (...args: unknown[]) => unknown)([100, 200, 300, 400, 500], 0.95);
    assert(false, 'should have thrown ReferenceError');
  } catch (e) {
    assert(e instanceof ReferenceError, `ReferenceError thrown: "${(e as Error).message}"`);
  }
}

// ── GREEN: percentile ────────────────────────────────────────────────────────
console.log('\n=== GREEN: percentile ===');
{
  const arr = [100, 200, 300, 400, 500]; // already sorted ascending
  assertClose(percentile(arr, 0.50), 300, 'p50 of [100,200,300,400,500]');
  // Linear interpolation: 0.95*(5-1)=3.8 → 400 + 100*0.8 = 480
  assertClose(percentile(arr, 0.95), 480, 'p95 of [100,200,300,400,500] (linear interp)');
  assertClose(percentile(arr, 0.00), 100, 'p0 === min');
  assertClose(percentile(arr, 1.00), 500, 'p100 === max');

  assertClose(percentile([42], 0.50), 42, 'p50 of single element');
  assert(percentile([], 0.95) === 0, 'empty array returns 0');

  // Interpolation: [0, 100], p95 → 95
  assertClose(percentile([0, 100], 0.95), 95, 'p95 of [0,100] interpolates to 95');
}

// ── GREEN: CircularBuffer ─────────────────────────────────────────────────────
console.log('\n=== GREEN: CircularBuffer ===');
{
  const buf = new CircularBuffer(60);
  assert(buf.length === 0, 'empty buffer length is 0');
  assert(buf.toArray().length === 0, 'empty toArray() is []');

  for (let i = 0; i < 60; i++) buf.push(i);
  assert(buf.length === 60, 'length === 60 after 60 pushes');
  const arr60 = buf.toArray();
  assert(arr60.length === 60, 'toArray() has 60 elements');
  assert(arr60[0] === 0 && arr60[59] === 59, 'insertion order preserved (oldest first)');

  // Push 10 more — evicts the oldest 10
  for (let i = 60; i < 70; i++) buf.push(i);
  assert(buf.length === 60, 'length stays 60 after 70 pushes (circular)');
  const arr70 = buf.toArray();
  assert(arr70.length === 60, 'toArray() still 60 elements after wrap');
  assert(arr70[0] === 10, `oldest element after wrap is 10 (got ${arr70[0]})`);
  assert(arr70[59] === 69, `newest element is 69 (got ${arr70[59]})`);
}

// ── GREEN: p50/p95 through buffer ────────────────────────────────────────────
console.log('\n=== GREEN: p50/p95 through CircularBuffer ===');
{
  const buf = new CircularBuffer(60);
  // 60 linearly spaced values from 100 to 600
  for (let i = 0; i < 60; i++) buf.push(Math.round(100 + (500 / 59) * i));
  const sorted = buf.toArray().sort((a, b) => a - b);
  const p50 = percentile(sorted, 0.50);
  const p95 = percentile(sorted, 0.95);
  assert(p50 >= 340 && p50 <= 360, `p50 ≈ 350 (got ${p50.toFixed(1)})`);
  assert(p95 >= 570 && p95 <= 600, `p95 ≈ 575 (got ${p95.toFixed(1)})`);
}

// ── Summary ──────────────────────────────────────────────────────────────────
console.log(`\nResults: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
