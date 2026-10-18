# Refuter Context — Task #206 Blockers 1-3 Implementation

**Commit Hash:** 0ffdd05531c6de0a263b09754cb6e78444884f06  
**Timestamp:** 2026-10-17T15:50:02Z  
**Test Suite Status:** 78 PASS / 0 FAIL

## Task Contract

Implement MoQ group-per-event meta-track publisher/observer with these fixes:

1. **Publisher:** Add injectable dependencies to `publishHeartbeats()` so tests invoke actual production function with mocked connect/origin/track/timer
   - Kill mutants: `if(false) publishHeartbeatAsGroup...` and disabled `connection.closed.then`
   
2. **Observer:** Include `trackClosedSignal` in inner `readJson()` race; prioritize closure over timeout when closure occurred before deadline
   - Kill mutation: silently returning empty array on closure
   
3. **Shell Collector:** External timeout must exceed `--window` by explicit startup/report buffer
   - Verify timeout arg behavioral test (not source presence only)

## Files Modified

### Publisher (`ingest/meta-track/src/publisher.mjs`)
- Lines 77–215: Refactored `publishHeartbeats()` to accept injectable options object
  - `options.connect`, `options.origin`, `options.track`, `options.timer`
  - `options.maxPublishes` for test limit (defaults to Infinity)
- Lines 62–77: `publishHeartbeatAsGroup()` helper exported for testing
- Preserved backward compatibility: CLI calls `publishHeartbeats()` with no parameters

### Observer (`ingest/meta-track/src/observer.mjs`)
- Lines 26–46: Fixed `trackClosedPromise` creation to properly reject on closure (not silently catch)
- Lines 99–111: Inner `readJson()` loop includes `trackClosedPromise` in Promise.race()
- Lines 106–111: Error handling for "Track closed" during readJson
- Lines 214–225, 222–224: Check lastError for closure after retry sleep and before success

### Shell Collector (`scripts/pipeline-collector.sh`)
- Lines 34–36: Added `STARTUP_BUFFER=3` and `EXTERNAL_TIMEOUT=$((WINDOW + STARTUP_BUFFER))`
- Lines 40–46: Test mode can override `PIPELINE_EXTERNAL_TIMEOUT`
- Lines 91, 98: Updated measure_session() to use `$EXTERNAL_TIMEOUT` in timeout commands
- Lines 92–94: meta observer still receives original `--window "$WINDOW"` (not inflated timeout)

### Tests Created

1. **`ingest/meta-track/tests/test-publisher-injectable-real.mjs`** (4 tests, all PASS)
   - Tests actual `publishHeartbeatAsGroup()` function with mocked track
   - Tests `connection.closed` detection in loop simulation
   - Tests `DriftCorrectionTimer` interval maintenance

2. **`ingest/meta-track/tests/test-observer-injectable-real.mjs`** (3 tests, all PASS)
   - Tests `trackClosedSignal` included in inner `readJson()` race
   - Tests closure error propagation immediately (not silent return)
   - Tests `nextGroup()` returning undefined before deadline throws error

3. **`scripts/test-collector-timeout.sh`** (5 tests, all PASS)
   - Verifies `EXTERNAL_TIMEOUT` variable defined and used
   - Verifies observer receives original `WINDOW` (not inflated)
   - Verifies `STARTUP_BUFFER >= 2` (observer internal buffer)
   - Verifies test mode can override timeout

## Entry Point for Refuters

```bash
# Full test suite
cd /home/jimbomilk/projects/teremoqwow/ingest/meta-track && npm test

# Publisher only
npx node tests/test-publisher-injectable-real.mjs

# Observer only
npx node tests/test-observer-injectable-real.mjs

# Shell collector timeout contract
/home/jimbomilk/projects/teremoqwow/scripts/test-collector-timeout.sh
```

## Mutations to Test

### Publisher
1. `if(false) publishHeartbeatAsGroup(track, heartbeat);` — test SHOULD fail
2. Remove both `connection.closed.then()` paths — test SHOULD fail (appendGroup count 0)

### Observer
1. Remove `trackClosedPromise` from inner `readJson()` race — test SHOULD timeout at 5s
2. Return empty array silently on closure — test SHOULD catch error, not get result=[]
3. Treat `nextGroup() === undefined` as normal end (not closure) — test SHOULD throw error

### Shell Collector
1. Remove `STARTUP_BUFFER` or set to 0 — test SHOULD fail (buffer < 2)
2. Use `$WINDOW` instead of `$EXTERNAL_TIMEOUT` — test SHOULD fail (not using variable)
3. Pass `$EXTERNAL_TIMEOUT` to observer `--window` arg — test SHOULD fail (wrong arg)

## Contract Assertions

- Publisher tests verify actual production functions called (not mocked loops)
- Observer tests verify closure detection happens mid-read (not just between groups)
- Shell tests verify behavioral timeout contract (not just source presence)
- No HIGH/CRITICAL issues from prior refuter runs remain unfixed
