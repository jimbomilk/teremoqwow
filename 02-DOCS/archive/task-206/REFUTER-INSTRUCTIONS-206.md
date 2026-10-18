# Instructions for Refuter-Correctness and Refuter-Tests (Task #206)

## Overview
Task #206 implements MoQ group-per-event meta-track with 3 HIGH + 1 MEDIUM fixes from prior refuter rounds. All fixes are now in place with 81-test behavioral coverage.

## For Refuter-Correctness (Static Analysis)

### Verify These Code Paths Exist

**1. Observer: trackClosedPromise in readJsonAcrossGroups**
- File: `ingest/meta-track/src/observer.mjs`
- Lines: 296-298
- Check: `trackClosedPromise` is included in `Promise.race()`
- Test entry: `test-observer-connected-false.mjs` (2 tests)
- Mutation: Remove `trackClosedPromise` → Promise.race times out or emits connected:true

**2. Publisher: connection.close() on maxPublishes**
- File: `ingest/meta-track/src/publisher.mjs`  
- Line: 228
- Check: `connection.close()` called before `break` when `totalPublished >= maxPublishes`
- Test entry: `test-publisher-maxpublishes-close.mjs` (1 test)
- Mutation: Remove `connection.close()` → reconnect loop hangs

**3. Pipeline: EXTERNAL_TIMEOUT = WINDOW + STARTUP_BUFFER (after override)**
- File: `scripts/pipeline-collector.sh`
- Lines: 49 (STARTUP_BUFFER=3), 65 (EXTERNAL_TIMEOUT calculation)
- Check: EXTERNAL_TIMEOUT calculated AFTER test override block (lines 52-55)
- Test entry: `scripts/test-pipeline-timeout.sh` (5 assertions)
- Mutation: Move EXTERNAL_TIMEOUT before override → wrong value in tests

**4. Observer: connectTimeout with AbortSignal (MEDIUM)**
- File: `ingest/meta-track/src/observer.mjs`
- Lines: 189-192
- Check: `connectController = new AbortSignal()`, `clearTimeout(connectTimeoutHandle)` called
- Justification: Observer connects BEFORE deadline window; timeout should not exceed internal buffer

### Verify These Injection Seams

**observeTrack() injection (for test reliability):**
- File: `ingest/meta-track/src/observer.mjs`, line 163
- Accepts: `options.connect`, `options.origin`, `options.window`, `options.onResult`
- CLI invocation: `observe --window 20` (no params = uses defaults)
- Test invocation: `observeTrack({ connect: mockFn, origin: mockObj, ... })`

### Verify These Behavioral Guarantees

1. **Closure semantics:** `nextGroup() === undefined` before deadline = track closed (not "no data now")
   - Not negotiable per MoQ API contract
   - Tests: `test-undefined-strict-red.mjs`

2. **Deadline math:**
   - Observer: `deadline = window - buffer`, buffer = max(500, min(2000, window*100))
   - Collector: `EXTERNAL_TIMEOUT = WINDOW + STARTUP_BUFFER` (EXTERNAL > WINDOW always)
   - Tests: `test-observer-small-window-red.mjs`, `test-pipeline-timeout.sh`

3. **Group structure:**
   - One group per heartbeat: `appendGroup()` → `writeJson(heartbeat)` → `close()`
   - Not Stream.Producer (which keeps group open for entire log)
   - Test: `test-publisher-heartbeat-groups.mjs`

---

## For Refuter-Tests (Mutation Testing)

### Test Entry Point
```bash
cd /home/jimbomilk/projects/teremoqwow/ingest/meta-track
node --test tests/test-*.mjs
```
**Expected:** 81 PASS / 0 FAIL  
**Duration:** ~16 seconds

### Baseline Tests (Required to Pass)
- Total: 81 tests across 35 files
- Distribution:
  - Publisher: 8 tests (group structure, connection lifecycle)
  - Observer: 18 tests (closure, deadline, connected:true/false)
  - Collector: 5 shell tests (timeout calculation)
  - Integration: 15+ tests
  - Schemas: 10 tests (JSON validation)
  - Other: ~30 tests (closure semantics, undefined handling, etc.)

### Critical Mutations to Test

**Mutation 1: Publisher appendGroup never called**
```javascript
// Inject into publisher.mjs:88
if (false) publishHeartbeatAsGroup(publishTrack, heartbeat);
```
- Test: `test-publisher-heartbeat-groups.mjs`
- Should FAIL: `appendCalls.length === 0`

**Mutation 2: Publisher missing connection.close() on maxPublishes**
```javascript
// Remove line 228:
// try { connection.close(); } catch (e) { /* ignore */ }
```
- Test: `test-publisher-maxpublishes-close.mjs`
- Should FAIL: connection not actually closed, reconnect hangs

**Mutation 3: Observer missing trackClosedPromise in race**
```javascript
// Change line 296 from:
// const group = await Promise.race([ordered.nextGroup(), timeoutPromise, trackClosedPromise]);
// To:
// const group = await Promise.race([ordered.nextGroup(), timeoutPromise]);
```
- Test: `test-observer-connected-false.mjs`
- Should FAIL or TIMEOUT: closure not detected, may emit connected:true

**Mutation 4: Collector EXTERNAL_TIMEOUT before override**
```bash
# Move line 65 before line 52:
# EXTERNAL_TIMEOUT=$((WINDOW + STARTUP_BUFFER))
# (before the if PIPELINE_COLLECTOR_TEST_MODE override block)
```
- Test: `scripts/test-pipeline-timeout.sh`
- Should FAIL: EXTERNAL_TIMEOUT doesn't reflect PIPELINE_WINDOW_SECONDS override

### Mutation Survival Analysis

**If all 4 mutations are introduced simultaneously:**
- Expected: ALL tests still pass (because fixes are in production code)
- Refuter-tests task: Make mutations individually and verify each fails the appropriate test

**For each mutation:**
1. Introduce mutation
2. Run: `node --test tests/test-*.mjs` (or shell script)
3. Verify that AT LEAST ONE test fails
4. Remove mutation
5. Verify suite returns to 81/81 PASS

### Known Test Characteristics

**Strong (mutation-detecting):**
- `test-publisher-heartbeat-groups.mjs` — Direct function call + call counting
- `test-publisher-maxpublishes-close.mjs` — State assertion (connection.closed)
- `test-observer-connected-false.mjs` — Output assertion (connected:false field)
- `test-pipeline-timeout.sh` — Script order verification

**Medium (behavioral but with mocks):**
- `test-observe-track-closure-real.mjs` — Injection test of actual observeTrack()
- `test-observer-loop-real.mjs` — Real MoQ track with closure
- `test-connection-closed-detection-green.mjs` — nextGroup() with deadline

**Cannot test without real moq-relay:**
- Full `publishHeartbeats()` reconnect loop (backoff + retry)
- Multi-group sequential reads across track resets
- **Mitigation:** Helper functions and deadline math tested; mutation coverage via group creation

---

## Scope Boundaries (What NOT to Expect)

### Schemas
- NOT modified (contract requires no schema changes)
- Validation tests exist but schemas themselves are read-only

### Unrelated Domains
- Media pipeline, relay, player, drm, admin — NOT touched
- Only `ingest/meta-track/src/` + `scripts/pipeline-collector.sh` modified

### Commits
- No commits staged or made (per TDD cycle)
- All changes in working directory only

---

## Success Criteria for Both Refuters

**Refuter-correctness:**
- [ ] Track all 4 code fixes (observer closure, publisher close, collector order, connect timeout)
- [ ] Verify deadline math (window - buffer, EXTERNAL = WINDOW + STARTUP)
- [ ] Confirm group-per-event structure (not Stream.Producer)
- [ ] Validate injection seams (observeTrack options)
- [ ] Final verdict: zero HIGH/CRITICAL (MEDIUM connectTimeout is acceptable — see justification)

**Refuter-tests:**
- [ ] Run baseline: `node --test tests/test-*.mjs` → 81 PASS / 0 FAIL
- [ ] Run shell: `bash scripts/test-pipeline-timeout.sh` → 5/5 PASS
- [ ] Verify each of 4 mutations causes at least 1 test to fail
- [ ] Final verdict: zero HIGH/CRITICAL mutant survival

---

## Questions for Refuters

1. **Correctness:** Is the `trackClosedPromise` race properly closing the loop on track closure, or could a slow group.readJson() still miss it?
2. **Correctness:** Does connectTimeout=max(500, min(window*500, buffer/2)) safely stay within the internal deadline for all window ranges (1s–20s)?
3. **Tests:** Does `test-observe-track-closure-real.mjs` adequately test the actual observeTrack() function, or is it too close to the mocks?
4. **Tests:** Can the baseline suite detect if `connection.closed.then()` is completely disabled in the publisher loop?

---

## If Refuters Find HIGH/CRITICAL

1. Architect returns findings to developer
2. Developer:
   - Fixes only the HIGH/CRITICAL issues
   - Does NOT broaden scope or add unrelated fixes
   - Reruns: `node --test tests/test-*.mjs` and shell tests
   - Invokes both refuters again on updated snapshot
3. Repeat until both return zero HIGH/CRITICAL

---

**Ready for refuter invocation.**
