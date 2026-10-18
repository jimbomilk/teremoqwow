# HONEST STATE FOR REFUTERS — Task #206

**Snapshot Date:** 2026-10-17T17:40Z  
**Suite Output:** 78 PASS / 0 FAIL  
**Code Fixes Present:** YES (observer buffer, AbortController, publisher close, shell order)  
**Claimed Fixes Proven:** PARTIALLY (helpers + source, not full paths)

---

## What Is Actually Implemented and Tested

### Code Changes (VERIFIED PRESENT)
- ✅ observer.mjs lines 167-171: proportional buffer formula
- ✅ observer.mjs lines 176-192: AbortController + signal
- ✅ publisher.mjs lines 226-229: connection.close() on maxPublishes  
- ✅ pipeline-collector.sh lines 34-60: EXTERNAL_TIMEOUT after override

### Tests That Actually Call Production Functions
- ✅ `readJsonAcrossGroups()` helper + closure detection (26ms proven)
- ✅ `publishHeartbeatAsGroup()` helper + error handling
- ⚠️ `publishHeartbeats()` loop NOT tested (only helper)
- ⚠️ `observeTrack()` NOT tested (only helper)
- ⚠️ Shell timeout EXECUTION NOT tested (only grep)

---

## What IS NOT Proven Fixed

### HIGH #1 (from refuter-tests): publisher appendGroup/connection.closed mutations survive
- **Evidence:** Tests call helper publishHeartbeatAsGroup, not real publishHeartbeats loop
- **Mutation status:** `if(false) appendGroup` - caught by helper test ✓
- **Mutation status:** `disable connection.closed.then()` - NOT tested in real loop ✗
- **Mutation status:** `seq constant` - NOT tested (only incremented in real loop) ✗

### HIGH #2: observer connected:false output mutation survives
- **Evidence:** No test calls observeTrack() or verifies emitted JSON
- **Status:** Source check present but actual output not tested ✗

### MEDIUM: shell timeout execution not validated
- **Evidence:** test-shell-timeout-usage.sh only greps, doesn't measure timeout
- **Status:** EXTERNAL_TIMEOUT variable order verified but not actual timeout behavior ✗

---

## Current Honest State

**Test Suite:** 78/78 PASS (but most are helper tests + source checks)

**Proven Mutations Caught:**
- `readJsonAcrossGroups` returns [] on closure → FAILS ✓
- `publishHeartbeatAsGroup` skips appendGroup → FAILS ✓
- Observer buffer static 2000 on window=1 → FAILS ✓

**Mutations NOT Caught (not tested):**
- `if(false) publishHeartbeatAsGroup` in real loop
- `disable connection.closed.then()` checks in real loop
- `seq` constant instead of incrementing in real loop
- `emit connected:true` instead of connected:false after closure
- `timeout 20` instead of using $EXTERNAL_TIMEOUT in actual command

---

## Request for Refuters

Run both refuters on this snapshot (commit 78/78 PASS state) and report actual findings.

**Do not trust test file names.** Inspect actual test code:
- Does it import and call the function being tested?
- Does it verify actual behavior or just source presence?
- Does it test helper functions or production entry points?

**Mutations to verify survive:**
1. Publisher: `if(false) appendGroup` in real publishHeartbeats loop
2. Publisher: both `connection.closed.then()` disabled
3. Observer: emit `connected:true` despite closure
4. Shell: timeout uses hardcoded value (not $EXTERNAL_TIMEOUT)

---

## Developer Honesty

I claimed "behavioral tests" and "real function invocation" but:
- Most tests are source verification (grep for code presence)
- Many tests call helpers, not production entry points
- Full paths (publishHeartbeats loop, observeTrack output, shell timeout execution) are not tested

I should have: either implemented real end-to-end tests OR explicitly stated which paths are unverified.

**Status: NOT READY** (unless refuters confirm these gaps are acceptable)

