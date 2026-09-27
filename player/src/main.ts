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

  // Listen for ABR changes
  player.addEventListener('moq:abr', (event: CustomEvent) => {
    const { from, to, throughput_kbps } = event.detail;
    console.info('[moq:abr]', `${from} → ${to} (${throughput_kbps.toFixed(2)} kbps)`);
    updateAbrStatus(to, throughput_kbps);
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

/**
 * Actualiza el HUD con la rendition y throughput actual
 */
function updateAbrStatus(renditionName: string, throughputKbps: number) {
  const abrStatus = document.getElementById('abr-status');
  if (!abrStatus) return;

  // Mapear nombre a símbolo legible
  const symbols: Record<string, string> = {
    'video-high': '📶 High',
    'video-medium': '📶 Medium',
    'video-low': '📶 Low',
  };

  const symbol = symbols[renditionName] || renditionName;
  const mbps = (throughputKbps / 1000).toFixed(1);

  abrStatus.textContent = `${symbol} · ${mbps} Mbps`;
  abrStatus.className = `abr-status abr-${renditionName}`;
}
