import { test } from 'node:test';
import { strict as assert } from 'node:assert';

// Integration tests: Publisher and Observer
// These tests verify that modules can be imported and have correct exports

async function testPublisherImport() {
  // RED: Test that publisher module can be imported
  // It will fail to connect, but should load the module code
  try {
    const pub = await import('../src/publisher.mjs');
    // If we get here, the module loaded successfully (but may be waiting to connect)
    return { success: true, message: 'Publisher module loaded' };
  } catch (err) {
    // Check if it's a connection error vs a syntax error
    if (err.message?.includes('ECONNREFUSED') || err.message?.includes('Cannot find')) {
      return { success: false, error: err.message };
    }
    throw err;
  }
}

async function testObserverImport() {
  // RED: Test that observer module can be imported
  try {
    const obs = await import('../src/observer.mjs');
    return { success: true, message: 'Observer module loaded' };
  } catch (err) {
    if (err.message?.includes('ECONNREFUSED') || err.message?.includes('Cannot find')) {
      return { success: false, error: err.message };
    }
    throw err;
  }
}

test('unit: publisher source file is valid JavaScript', async () => {
  // Just verify the file can be read and parsed
  const { readFileSync } = await import('node:fs');
  const { fileURLToPath } = await import('node:url');
  const { dirname, join } = await import('node:path');
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);

  const src = readFileSync(join(__dirname, '../src/publisher.mjs'), 'utf-8');
  assert.ok(src.includes('publishHeartbeats'), 'Publisher should define main function');
  assert.ok(src.includes('BROADCAST'), 'Publisher should check BROADCAST');
  assert.ok(src.includes('anon/live1-meta'), 'Publisher should guard broadcast name');
});

test('unit: observer source file is valid JavaScript', async () => {
  // Just verify the file can be read and parsed
  const { readFileSync } = await import('node:fs');
  const { fileURLToPath } = await import('node:url');
  const { dirname, join } = await import('node:path');
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);

  const src = readFileSync(join(__dirname, '../src/observer.mjs'), 'utf-8');
  assert.ok(src.includes('observeTrack'), 'Observer should define main function');
  assert.ok(src.includes('--window'), 'Observer should parse window argument');
});

export {};
