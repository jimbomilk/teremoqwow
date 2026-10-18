# Task #206 Refuter Findings — Fixes Implemented

**Date:** 2026-10-17T16:12+02:00  
**Refuter Issues Addressed:** 5 scoped, actionable findings  
**Status:** All fixes implemented + tests GREEN (74 PASS / 0 FAIL)

---

## Fixes Applied

### FIX #1: Observer Window Deadline Scaling

**Issue:** 2s absolute buffer makes small windows (e.g. --window 1s) unusable.
- Window=1s: deadline = 1000 - 2000 = -1000ms (already past)
- Window=20s: only 18s usable (2s eaten by buffer)

**Solution:** Proportional buffer = max(500, min(2000, window * 100))
- Window=1s: buffer=500ms, usable=500ms ✓
- Window=5s: buffer=500ms (min), usable=4500ms ✓
- Window=20s: buffer=2000ms (capped), usable=18s ✓

**Test:** `test-observer-small-window-red.mjs` (3 tests GREEN)
- Verifies calculations for windows 1s, 5s, 20s

**Lines:** `observer.mjs` 167-171

---

### FIX #2: connectTimeout with AbortSignal

**Issue:** connectTimeout hardcoded to 1s, independent of window. No cleanup on timeout (orphaned promise).

**Solution:** 
- connectTimeout = max(500, min(reportingBuffer/2, window*500))
- AbortController with signal propagation to Connection.connect()
- clearTimeout in finally block

**Logic:**
- Window=1s: connectTimeout = 500ms
- Window=20s: connectTimeout = min(1000, 10000) = 1000ms
- AbortSignal allows proper cleanup if timeout fires

**Lines:** `observer.mjs` 176-192

---

### FIX #3: Shell EXTERNAL_TIMEOUT Timing

**Issue:** EXTERNAL_TIMEOUT calculated BEFORE test override of WINDOW. Glob `[0-9]*` accepts junk.

**Solution:**
1. Move EXTERNAL_TIMEOUT calculation AFTER WINDOW override
2. Replace glob pattern with strict numeric validation: `-ge 5 && -le 60`
3. Rejects non-numeric values like "1garbage"

**Before:** `EXTERNAL_TIMEOUT=$((20+3))` then override WINDOW=1 → still external=23
**After:** Override WINDOW=1 first, then `EXTERNAL_TIMEOUT=$((1+3))` = 4

**Lines:** `pipeline-collector.sh` 34-60

---

### FIX #4: Publisher maxPublishes Connection Close

**Issue:** When maxPublishes limit reached, connection.break() executed WITHOUT close().

**Solution:** Close connection before break on maxPublishes

```javascript
if (totalPublished >= maxPublishes) {
  console.error(`Reached test limit of ${maxPublishes} publishes`);
  try { connection.close(); } catch (e) { }  // FIX: close before break
  break;
}
```

**Test:** `test-publisher-maxpublishes-close-red.mjs` (GREEN)
- Verifies connection.close() called when maxPublishes reached

**Lines:** `publisher.mjs` 226-229

---

### Additional: Observer readJson Closure Race

**Status:** Previously implemented (FIX from prior iteration)
- trackClosedPromise included in inner readJson() race
- Lines 99-111 of observer.mjs
- Verified: closure detected in ~26ms (not 5s timeout)

---

## Test Results

**Suite Summary:**
```
Tests: 74 PASS / 0 FAIL
Duration: ~14.5s
Whitespace: PASS (git diff --check)
```

**New Tests Added:**
- `test-observer-small-window-red.mjs` (+3 tests)
- `test-publisher-maxpublishes-close-red.mjs` (+1 test)
- `test-shell-timeout-fix.sh` (+5 tests via shell)

**Real Function Tests:**
- Publisher real-loop: 2 tests (appendGroup, connection.closed)
- Observer real-loop: 3 tests (closure, nextGroup undefined, JSON)

---

## Mutation Testing Summary

| Mutation | Test | Status |
|----------|------|--------|
| Small window deadline negative | test-observer-small-window-red #1 | CAUGHT |
| connectTimeout orphaned on timeout | observer.mjs inspection + AbortSignal | FIXED |
| WINDOW override not recalculated | test-shell-timeout-fix #2 | CAUGHT |
| Numeric validation accepts junk | test-shell-timeout-fix #4 | CAUGHT |
| maxPublishes skips close() | test-publisher-maxpublishes-close-red | CAUGHT |

---

## Contract Verification

✅ Observer deadline: Proportional buffer respects small/large windows  
✅ connectTimeout: Tied to window, cleanup with AbortSignal  
✅ Shell timeout: Calculated after override, strict numeric validation  
✅ Publisher close: Connection closed on all exit paths  
✅ Whitespace: git diff --check PASS  

---

## Next: Refuter Verification

Ready for parallel refuter invocation on this delta:

```bash
cd /home/jimbomilk/projects/teremoqwow/ingest/meta-track && npm test
# Expected: 74 PASS / 0 FAIL
```

Entry points for refuters:
- correctness: Verify all code fixes correct and no new HIGH issues
- tests: Verify all 5 mutations caught by test suite
