// Tests for _fetchCertHash / fetchCertHash (E1-T4).
// Run with: node player/src/moq-watch.test.ts
// Node 24 strips TypeScript types natively; no extra flags needed.

import { fetchCertHash, PlayerLogic, HudState, buildShadowHtml, type PlayerState } from './moq-watch.ts';

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

// ============================================================
// E3-T1 — Status overlay
// ============================================================

console.log('\n=== test_status_overlay_initial_state ===');
{
  const logic = new PlayerLogic();
  assert(logic.state === 'connecting', 'initial state is connecting');
  const html = buildShadowHtml(false);
  assert(html.includes('status-connecting'), 'overlay has class status-connecting in HTML');
}

console.log('\n=== test_status_overlay_on_ready ===');
{
  const logic = new PlayerLogic();
  logic.handleReady();
  assert(logic.state === 'live', 'state becomes live after handleReady()');
}

console.log('\n=== test_status_overlay_on_error ===');
{
  const logic = new PlayerLogic();
  logic.handleError(() => setTimeout(() => {}, 99999));
  assert(logic.state === 'error', 'state becomes error after handleError()');
  clearTimeout(logic.reconnectTimer!);
}

console.log('\n=== test_status_overlay_embed_mode ===');
{
  const html = buildShadowHtml(true);
  assert(
    html.includes('status-connecting embed'),
    'overlay HTML contains embed class when isEmbed=true',
  );
}

// ============================================================
// E3-T2 — HUD calidad y latencia
// ============================================================

console.log('\n=== test_hud_updates_on_latency_event ===');
{
  const hud = new HudState();
  hud.onLatency(150);
  assert(hud.latencyText === '150 ms', `latencyText should be '150 ms', got '${hud.latencyText}'`);
}

console.log('\n=== test_hud_warn_color_high_latency ===');
{
  const hud = new HudState();
  hud.onLatency(850);
  assert(hud.latencyWarn === true, 'latencyWarn=true when latency_ms > 700');
}

console.log('\n=== test_hud_updates_on_abr_event ===');
{
  const hud = new HudState();
  hud.onAbr('HD', 4000);
  assert(hud.qualityText === 'HD 4.0 Mbps', `qualityText should be 'HD 4.0 Mbps', got '${hud.qualityText}'`);
}

console.log('\n=== test_hud_visible_in_embed_mode ===');
{
  const html = buildShadowHtml(true);
  assert(html.includes('hud-visible'), 'HUD has class hud-visible in embed mode');
}

// ============================================================
// E3-T3 — Reconexion automatica
// ============================================================

console.log('\n=== test_reconnect_schedules_after_error ===');
{
  const logic = new PlayerLogic();
  logic.handleError(() => setTimeout(() => {}, 99999));
  assert(logic.reconnectAttempt === 1, `reconnectAttempt should be 1, got ${logic.reconnectAttempt}`);
  clearTimeout(logic.reconnectTimer!);
}

console.log('\n=== test_reconnect_resets_on_ready ===');
{
  const logic = new PlayerLogic();
  logic.handleError(() => setTimeout(() => {}, 99999));
  logic.handleReady();
  assert(logic.reconnectAttempt === 0, 'reconnectAttempt resets to 0 after handleReady()');
  assert(logic.reconnectTimer === null, 'reconnectTimer is null after handleReady()');
}

console.log('\n=== test_reconnect_stops_after_max_attempts ===');
{
  const logic = new PlayerLogic();
  const timers: ReturnType<typeof setTimeout>[] = [];
  for (let i = 0; i < logic.BACKOFF_MS.length; i++) {
    logic.handleError((d) => { const t = setTimeout(() => {}, d); timers.push(t); return t; });
  }
  // 6th call should hit the max and set unavailable
  logic.handleError(() => setTimeout(() => {}, 99999));
  assert(logic.state === 'unavailable', `state should be unavailable after ${logic.BACKOFF_MS.length + 1} errors, got '${logic.state}'`);
  timers.forEach(clearTimeout);
}

console.log('\n=== test_cleanup_cancels_reconnect_timer ===');
{
  const logic = new PlayerLogic();
  logic.handleError(() => setTimeout(() => {}, 99999));
  assert(logic.reconnectTimer !== null, 'timer was scheduled');
  logic.cleanup();
  assert(logic.reconnectTimer === null, 'reconnectTimer is null after cleanup()');
}

// ============================================================
// E3-T5 — Token viewer anonimo automatico
// ============================================================

console.log('\n=== test_acquire_token_success ===');
{
  const logic = new PlayerLogic();
  const mockFetch = async (_url: string, _init?: RequestInit): Promise<Response> =>
    ({ ok: true, json: async () => ({ access_token: 'my-jwt-token' }) }) as unknown as Response;
  await logic.acquireToken(mockFetch as typeof fetch);
  assert(logic.viewerToken === 'my-jwt-token', `viewerToken should be 'my-jwt-token', got '${logic.viewerToken}'`);
}

console.log('\n=== test_acquire_token_graceful_failure ===');
{
  const logic = new PlayerLogic();
  const mockFetch = async (): Promise<never> => { throw new Error('network error'); };
  await logic.acquireToken(mockFetch as unknown as typeof fetch);
  assert(logic.viewerToken === null, 'viewerToken stays null on fetch failure');
}

console.log('\n=== test_vote_uses_bearer_token ===');
{
  const logic = new PlayerLogic();
  logic.viewerToken = 'bearer-test-token';
  let capturedHeaders: Record<string, string> | null = null;
  const mockFetch = async (_url: string, init?: RequestInit): Promise<Response> => {
    capturedHeaders = init?.headers as Record<string, string>;
    return { ok: true, json: async () => ({}) } as unknown as Response;
  };
  await logic.submitVote({ option: 'A' }, 'anon/live1', mockFetch as typeof fetch);
  assert(
    capturedHeaders?.['Authorization'] === 'Bearer bearer-test-token',
    'Authorization header is set when viewerToken is present',
  );
}

console.log('\n=== test_vote_without_token_still_submits ===');
{
  const logic = new PlayerLogic();
  // viewerToken is null by default
  let called = false;
  let capturedHeaders: Record<string, string> | null = null;
  const mockFetch = async (_url: string, init?: RequestInit): Promise<Response> => {
    called = true;
    capturedHeaders = init?.headers as Record<string, string>;
    return { ok: true, json: async () => ({}) } as unknown as Response;
  };
  await logic.submitVote({ option: 'B' }, 'anon/live1', mockFetch as typeof fetch);
  assert(called === true, 'fetch was called even without a token');
  assert(
    capturedHeaders?.['Authorization'] === undefined,
    'no Authorization header when viewerToken is null',
  );
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
