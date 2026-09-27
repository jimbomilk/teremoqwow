/**
 * teremoqwow Player — Phase 0
 * Main entry point for the MoQ-based video player
 */

import './moq-watch';

// Initialize event listeners once DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupListeners);
} else {
  setupListeners();
}

function setupListeners() {
  const player = document.querySelector('moq-watch') as HTMLElement & {
    addEventListener: (event: string, handler: (e: CustomEvent) => void) => void;
  };

  if (!player) {
    console.warn('moq-watch element not found');
    return;
  }

  // Listen for latency updates
  player.addEventListener('moq:latency', (event: CustomEvent) => {
    const { latency_ms, pts_ms, render_ts_ms } = event.detail;
    console.debug('[moq:latency]', {
      latency_ms: latency_ms.toFixed(2),
      pts_ms: pts_ms.toFixed(2),
      render_ts_ms: render_ts_ms.toFixed(2),
    });

    // Update UI statistics (already done in moq-watch, but log for monitoring)
    if (latency_ms > 700) {
      console.warn(`⚠️ Latency exceeds 700ms: ${latency_ms.toFixed(2)}ms`);
    }
  });

  // Listen for errors
  player.addEventListener('moq:error', (event: CustomEvent) => {
    const { message } = event.detail;
    console.error('[moq:error]', message);
  });

  // Listen for status changes
  player.addEventListener('moq:status', (event: CustomEvent) => {
    const { status } = event.detail;
    console.info('[moq:status]', status);
  });

  // Listen for ready event
  player.addEventListener('moq:ready', (event: CustomEvent) => {
    const { track } = event.detail;
    console.info('[moq:ready]', `Playing track: ${track}`);
  });

  console.info('✅ teremoqwow Player Phase 0 initialized');
}
