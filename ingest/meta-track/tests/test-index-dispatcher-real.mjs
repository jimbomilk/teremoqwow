#!/usr/bin/env node

/**
 * test-index-dispatcher-real.mjs
 *
 * RED: Real invocation tests that fail if dispatcher doesn't call functions
 * Uses mocks for Moq connections but REAL function invocation
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import assert from 'assert';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = join(__dirname, '../../..');

/**
 * Test: observe must call observeTrack and reach connection attempt
 * Falsable: Fails if observeTrack not invoked (no "Connecting" message)
 */
function testObserveDispatcherInvokesRealFunction() {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', [
      join(projectRoot, 'ingest/meta-track/src/index.mjs'),
      'observe',
      '--window', '1'
    ], {
      cwd: projectRoot,
      env: {
        ...process.env,
        MOQ_URL: 'http://localhost:9999/', // invalid URL to timeout quickly
        BROADCAST: 'test/broadcast',
        TRACK: 'test-track',
        NODE_ENV: 'test'
      },
      timeout: 3000
    });

    let stderr = '';
    let hasConnectingMessage = false;

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
      // observeTrack() would emit "[Observer] Connecting..."
      if (data.toString().includes('Connecting')) {
        hasConnectingMessage = true;
      }
    });

    proc.on('close', (code) => {
      // FALSABLE: If no "Connecting" message, observeTrack() was not invoked
      if (!hasConnectingMessage) {
        reject(new Error(
          `[FALSABLE] observeTrack() not invoked: no "Connecting" message found. ` +
          `stderr="${stderr}". ` +
          `If dispatcher just imports without invoking, this test fails.`
        ));
      } else {
        resolve('observeTrack invoked successfully');
      }
    });

    proc.on('error', reject);
  });
}

/**
 * Test: publish must call publishHeartbeats and reach connection attempt
 * Falsable: Fails if publishHeartbeats not invoked (no "[Publisher] Connecting")
 */
function testPublishDispatcherInvokesRealFunction() {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', [
      join(projectRoot, 'ingest/meta-track/src/index.mjs'),
      'publish'
    ], {
      cwd: projectRoot,
      env: {
        ...process.env,
        MOQ_URL: 'http://localhost:9999/', // invalid URL
        BROADCAST: 'anon/live1-meta',
        TRACK: 'heartbeat',
        INTERVAL_MS: '500',
        HEALTH_MARKER_PATH: '/tmp/test-health',
        NODE_ENV: 'test'
      },
      timeout: 2000
    });

    let stderr = '';
    let hasPublisherConnecting = false;

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
      // publishHeartbeats() emits "[Publisher] Connecting..."
      if (data.toString().includes('[Publisher] Connecting')) {
        hasPublisherConnecting = true;
      }
    });

    proc.on('close', (code) => {
      // FALSABLE: If no "[Publisher] Connecting", publishHeartbeats() not invoked
      if (!hasPublisherConnecting) {
        reject(new Error(
          `[FALSABLE] publishHeartbeats() not invoked: no "[Publisher] Connecting" found. ` +
          `stderr="${stderr}". ` +
          `If dispatcher just imports without invoking, this test fails.`
        ));
      } else {
        resolve('publishHeartbeats invoked successfully');
      }
    });

    proc.on('error', reject);
  });
}

// Run tests
async function runTests() {
  let passed = 0;
  let failed = 0;

  console.log('[TEST] testObserveDispatcherInvokesRealFunction');
  try {
    const result = await testObserveDispatcherInvokesRealFunction();
    console.log(`[PASS] ${result}`);
    passed++;
  } catch (err) {
    console.log(`[FAIL] ${err.message}`);
    failed++;
  }

  console.log('[TEST] testPublishDispatcherInvokesRealFunction');
  try {
    const result = await testPublishDispatcherInvokesRealFunction();
    console.log(`[PASS] ${result}`);
    passed++;
  } catch (err) {
    console.log(`[FAIL] ${err.message}`);
    failed++;
  }

  console.log(`\n[SUMMARY] ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

runTests().catch(console.error);
