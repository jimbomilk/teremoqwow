// Tests for OverlayEngine — E4-T5
// Run with: node player/src/overlay-engine.test.ts
// Node 24 strips TypeScript types natively; no extra flags needed.

import { OverlayEngine, type OverlayZone } from './overlay-engine.ts';

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

// ── Minimal DOM stubs for Node environment ────────────────────────────────────

function makeMockStyle(): any {
  const store: Record<string, string> = {};
  return new Proxy(store, {
    get(_t, k) { return store[k as string] ?? ''; },
    set(_t, k, v) { store[k as string] = String(v); return true; },
  });
}

function makeMockElement(tag: string): any {
  const children: any[] = [];
  const attrs: Record<string, string> = {};
  const listeners: Record<string, Function[]> = {};
  const el: any = {
    tagName: tag.toUpperCase(),
    style: makeMockStyle(),
    _children: children,
    appendChild(child: any) { children.push(child); },
    remove() { /* noop */ },
    setAttribute(k: string, v: string) { attrs[k] = v; },
    getAttribute(k: string): string | null { return attrs[k] ?? null; },
    addEventListener(type: string, fn: Function, _opts?: any) {
      listeners[type] = listeners[type] ?? [];
      listeners[type].push(fn);
    },
    _listeners: listeners,
    _attrs: attrs,
  };
  if (tag === 'iframe') {
    el.src = '';
    el.contentWindow = { postMessage: () => {} };
  }
  return el;
}

function makeMockRoot(): any {
  const children: any[] = [];
  return {
    _children: children,
    appendChild(child: any) { children.push(child); },
  };
}

(globalThis as any).document = {
  createElement(tag: string) { return makeMockElement(tag); },
};

// ── Tests ─────────────────────────────────────────────────────────────────────

console.log('\n=== test_overlay_engine_publish_adds_active ===');
{
  const engine = new OverlayEngine(makeMockRoot(), '/overlays/templates');
  await engine.publish({ id: 'ov1', template_id: 'lower-third', zone: 'bottom-left', duration_ms: 0, data: {} });
  assert(engine.activeCount() === 1, 'activeCount is 1 after one publish');
  assert(engine.activeIds().includes('ov1'), 'activeIds includes ov1');
}

console.log('\n=== test_overlay_engine_unpublish_removes_active ===');
{
  const engine = new OverlayEngine(makeMockRoot(), '/overlays/templates');
  await engine.publish({ id: 'ov2', template_id: 'logo-corner', zone: 'top-right', duration_ms: 0, data: {} });
  assert(engine.activeCount() === 1, 'activeCount is 1 before unpublish');
  engine.unpublish('ov2');
  assert(engine.activeCount() === 0, 'activeCount is 0 after unpublish');
}

console.log('\n=== test_overlay_engine_zone_conflict_replaces_previous ===');
{
  const engine = new OverlayEngine(makeMockRoot(), '/overlays/templates');
  await engine.publish({ id: 'ov-a', template_id: 'logo-corner', zone: 'top-left', duration_ms: 0, data: {} });
  assert(engine.activeCount() === 1, 'one overlay before conflict');
  await engine.publish({ id: 'ov-b', template_id: 'banner-bottom', zone: 'top-left', duration_ms: 0, data: {} });
  assert(engine.activeCount() === 1, 'still one overlay after zone conflict');
  assert(engine.activeIds().includes('ov-b'), 'new overlay ov-b is active');
  assert(!engine.activeIds().includes('ov-a'), 'old overlay ov-a was removed');
}

console.log('\n=== test_overlay_engine_clear_all_removes_all ===');
{
  const engine = new OverlayEngine(makeMockRoot(), '/overlays/templates');
  await engine.publish({ id: 'x1', template_id: 'lower-third', zone: 'bottom-left', duration_ms: 0, data: {} });
  await engine.publish({ id: 'x2', template_id: 'logo-corner', zone: 'top-right', duration_ms: 0, data: {} });
  await engine.publish({ id: 'x3', template_id: 'ticker-news', zone: 'bottom-bar', duration_ms: 0, data: {} });
  assert(engine.activeCount() === 3, 'three overlays active before clearAll');
  engine.clearAll();
  assert(engine.activeCount() === 0, 'no overlays active after clearAll');
}

console.log('\n=== test_overlay_engine_duration_auto_dismiss ===');
{
  const engine = new OverlayEngine(makeMockRoot(), '/overlays/templates');

  // Capture setTimeout calls to control timer
  let dismissCallback: (() => void) | null = null;
  let dismissDelay: number | null = null;
  const origSetTimeout = globalThis.setTimeout;
  (globalThis as any).setTimeout = (fn: () => void, delay: number) => {
    // Only capture the first call (the dismiss timer in publish)
    if (dismissCallback === null) {
      dismissCallback = fn;
      dismissDelay = delay;
    }
    return 0 as any;
  };

  await engine.publish({ id: 'timed', template_id: 'ad-countdown', zone: 'center', duration_ms: 5000, data: {} });

  (globalThis as any).setTimeout = origSetTimeout;

  assert(engine.activeCount() === 1, 'overlay is active after publish');
  assert(dismissDelay === 5000, `dismiss timer set to 5000ms, got ${dismissDelay}`);

  // Simulate timer firing
  dismissCallback!();

  assert(engine.activeCount() === 0, 'overlay auto-dismissed after timer fires');
}

// ─────────────────────────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
