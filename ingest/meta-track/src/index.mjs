#!/usr/bin/env node

const args = process.argv.slice(2);
const command = args[0];

if (command === 'publish') {
  // Run publisher: import and invoke publishHeartbeats()
  import('./publisher.mjs').then(({ publishHeartbeats }) => {
    publishHeartbeats().catch(err => {
      console.error(`[Publisher] Fatal error: ${err.message}`);
      process.exit(1);
    });
    // Graceful shutdown
    process.on('SIGTERM', () => {
      console.error('[Publisher] Received SIGTERM, exiting...');
      process.exit(0);
    });
    process.on('SIGINT', () => {
      console.error('[Publisher] Received SIGINT, exiting...');
      process.exit(0);
    });
  }).catch(err => {
    console.error(`[Publisher] Failed to load module: ${err.message}`);
    process.exit(1);
  });
} else if (command === 'observe') {
  // Run observer: import and invoke observeTrack()
  import('./observer.mjs').then(({ observeTrack }) => {
    observeTrack().catch(err => {
      console.error(`[Observer] Fatal error: ${err.message}`);
      process.exit(1);
    });
  }).catch(err => {
    console.error(`[Observer] Failed to load module: ${err.message}`);
    process.exit(1);
  });
} else {
  console.error('Usage: meta-track <publish|observe> [options]');
  console.error('');
  console.error('Commands:');
  console.error('  publish              Start the heartbeat publisher');
  console.error('  observe --window N   Start the observer (N seconds, default 20)');
  process.exit(1);
}
