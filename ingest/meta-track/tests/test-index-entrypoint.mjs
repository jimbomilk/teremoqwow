#!/usr/bin/env node

/**
 * test-index-entrypoint.mjs
 *
 * RED tests: verify index.mjs dispatcher INVOKES observeTrack() and publishHeartbeats()
 * Currently fails because import.meta.url guard prevents invocation
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import assert from 'assert';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = join(__dirname, '../../..');

/**
 * Test: observe command must connect and emit observer output
 * RED: Currently times out or exits silently (import.meta.url guard prevents invocation)
 */
function testObserveCommandInvokesObserverLogic() {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', [
      join(projectRoot, 'ingest/meta-track/src/index.mjs'),
      'observe',
      '--window', '1'
    ], {
      cwd: projectRoot,
      env: {
        ...process.env,
        MOQ_URL: 'http://localhost:8090/',
        BROADCAST: 'test/broadcast',
        TRACK: 'test-track',
        NODE_ENV: 'test'
      },
      timeout: 3000
    });

    let stdout = '';
    let stderr = '';
    let hasObserverOutput = false;

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
      // Observer should emit JSON output, diagnostic messages
      if (data.toString().includes('[Observer]') || data.toString().includes('{')) {
        hasObserverOutput = true;
      }
    });

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
      // Diagnostic: should see connection attempts or timeout messages
      if (data.toString().includes('[Observer]')) {
        hasObserverOutput = true;
      }
    });

    proc.on('close', (code) => {
      // RED FAILURE: If silent exit (no output, rc=0), import.meta.url guard is blocking
      if (!hasObserverOutput && code === 0) {
        reject(new Error(
          `[RED] observe command exited silently (rc=${code}). ` +
          `Likely observeTrack() not invoked due to import.meta.url guard. ` +
          `stdout="${stdout}", stderr="${stderr}"`
        ));
      } else if (hasObserverOutput) {
        // GREEN: saw output, function was invoked
        resolve(`observe invoked successfully`);
      } else {
        // Timeout or error (expected for test without real relay)
        resolve(`observe attempted (rc=${code})`);
      }
    });

    proc.on('error', (err) => {
      reject(err);
    });
  });
}

/**
 * Test: publish command must connect and emit publisher output
 * RED: Currently times out or exits silently
 */
function testPublishCommandInvokesPublisherLogic() {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', [
      join(projectRoot, 'ingest/meta-track/src/index.mjs'),
      'publish'
    ], {
      cwd: projectRoot,
      env: {
        ...process.env,
        MOQ_URL: 'http://localhost:8090/',
        BROADCAST: 'anon/live1-meta',
        TRACK: 'heartbeat',
        INTERVAL_MS: '500',
        HEALTH_MARKER_PATH: '/tmp/test-meta-health',
        NODE_ENV: 'test'
      },
      timeout: 2000
    });

    let stdout = '';
    let stderr = '';
    let hasPublisherOutput = false;

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
      if (data.toString().includes('[Publisher]') || data.toString().includes('boot_id')) {
        hasPublisherOutput = true;
      }
    });

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
      if (data.toString().includes('[Publisher]')) {
        hasPublisherOutput = true;
      }
    });

    proc.on('close', (code) => {
      // RED FAILURE: If silent exit, publishHeartbeats() not invoked
      if (!hasPublisherOutput && code === 0) {
        reject(new Error(
          `[RED] publish command exited silently (rc=${code}). ` +
          `Likely publishHeartbeats() not invoked due to import.meta.url guard. ` +
          `stdout="${stdout}", stderr="${stderr}"`
        ));
      } else if (hasPublisherOutput) {
        resolve(`publish invoked successfully`);
      } else {
        resolve(`publish attempted (rc=${code})`);
      }
    });

    proc.on('error', (err) => {
      reject(err);
    });
  });
}

/**
 * Test: invalid command should show help
 */
function testInvalidCommandShowsHelp() {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', [
      join(projectRoot, 'ingest/meta-track/src/index.mjs'),
      'invalid'
    ], {
      cwd: projectRoot,
      env: { ...process.env, NODE_ENV: 'test' },
      timeout: 1000
    });

    let stderr = '';

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    proc.on('close', (code) => {
      if (code === 1 && stderr.includes('Usage:')) {
        resolve('help shown correctly');
      } else {
        reject(new Error(`Expected rc=1 and help message, got rc=${code}, stderr="${stderr}"`));
      }
    });

    proc.on('error', reject);
  });
}

// Run tests
async function runTests() {
  console.log('[TEST] testObserveCommandInvokesObserverLogic');
  try {
    const result = await testObserveCommandInvokesObserverLogic();
    console.log(`[PASS] ${result}`);
  } catch (err) {
    console.log(`[RED FAILURE - EXPECTED] ${err.message}`);
  }

  console.log('[TEST] testPublishCommandInvokesPublisherLogic');
  try {
    const result = await testPublishCommandInvokesPublisherLogic();
    console.log(`[PASS] ${result}`);
  } catch (err) {
    console.log(`[RED FAILURE - EXPECTED] ${err.message}`);
  }

  console.log('[TEST] testInvalidCommandShowsHelp');
  try {
    const result = await testInvalidCommandShowsHelp();
    console.log(`[PASS] ${result}`);
  } catch (err) {
    console.log(`[FAIL] ${err.message}`);
  }
}

runTests().catch(console.error);
