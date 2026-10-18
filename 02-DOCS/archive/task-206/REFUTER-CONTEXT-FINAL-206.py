"""
Refuter Context for Task #206 — Final Fixes Round

Contract: Task #206 implements MoQ group-per-event meta-track (phase 1-data-track.md)
- Publisher: appendGroup + group.writeJson per heartbeat (injectable for testing)
- Observer: readJsonAcrossGroups with closure detection + reportable structure
- Shell collector: timeout contract with startup buffer

Refuter's task (correctness):
1. Inspect all 4 fixes for semantic correctness and contract alignment
2. Verify no NEW HIGH/CRITICAL issues introduced
3. Check code satisfies prior refuter findings:
   - HIGH#1: publisher appendGroup called per event ✓
   - HIGH#2: publisher connection.closed detected ✓
   - HIGH#3: observer closure during readJson propagated ✓
   - HIGH#4: observer undefined before deadline is error ✓
   - HIGH#5: external timeout > observer window ✓

Code locations:
- ingest/meta-track/src/observer.mjs (lines 167-171, 176-192, 99-111)
- ingest/meta-track/src/publisher.mjs (lines 226-229)
- scripts/pipeline-collector.sh (lines 34-60)

Test mutations to verify:
1. Observer: Change proportional buffer to absolute (old 2000ms) → should fail
2. Observer: Remove AbortController and signal → cleanup not tested but code present
3. Shell: Revert EXTERNAL_TIMEOUT before WINDOW override → test should fail
4. Shell: Change validation glob back to [0-9]* → "1garbage" should be accepted (BAD)
5. Publisher: Remove connection.close() on maxPublishes → test should fail

Refuter must verify:
- FIX #1: Buffer formula max(500, min(2000, window*100)) implemented
- FIX #2: AbortController created, signal passed to connect(), clearTimeout in finally
- FIX #3: EXTERNAL_TIMEOUT calculated AFTER window override, numeric validation strict
- FIX #4: connection.close() called before break on maxPublishes
- No regressions in prior fixes (closure detection still in race, undefined handling)

Entry: npm test (expect 74 PASS / 0 FAIL)
"""
