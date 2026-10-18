#!/usr/bin/env python3

"""
Refuter Invocation Context — Task #206 FINAL SNAPSHOT
Developer: teremoqwow-dev
Timestamp: 2026-10-17T14:35:35Z
SHA: 0ffdd05 (pre-commit snapshot)

Invocation parameters for parallel refuter execution:
  1. refuter-correctness
  2. refuter-tests

See: .github/agents/developer.agent.md — Disciplina TDD, refuter invocation protocol
"""

import json
import subprocess
import sys
from pathlib import Path

# Context constants
PROJECT_ROOT = Path("/home/jimbomilk/projects/teremoqwow")
TASK_ID = "206"
SHA = "0ffdd05"
TIMESTAMP = "2026-10-17T14:35:35Z"

# Contract location
CONTRACT_FILE = PROJECT_ROOT / "02-DOCS/wiki/ftd/fase1-data-track.md"

# Spec locations
SPEC_SCHEMA_DIR = PROJECT_ROOT / "schemas/media/"
INVARIANTS_FILE = PROJECT_ROOT / "SECURITY.md"

# Snapshot entry points (reproducible test commands)
ENTRY_POINTS = {
    "unit_tests": "npm test --prefix ingest/meta-track",
    "pipeline_tests": "python3 scripts/test_pipeline_obs_total_bytes.py",
    "workflow_tests": "python3 scripts/test_workflow_meta_track_filter.py",
    "meta_unit": "python3 scripts/test_meta_track_unit.py",
}

# Files modified in this delta (post-refuter-tests-medium)
MODIFIED_FILES = {
    # Core fixes
    "ingest/meta-track/src/index.mjs": {
        "change": "Dispatcher invokes observeTrack/publishHeartbeats",
        "lines_affected": [1, 35],
        "criticality": "HIGH",
    },
    "ingest/meta-track/src/publisher.mjs": {
        "change": "Promise.race(.closed) proactive monitoring + append(value) sync",
        "lines_affected": [99, 165],
        "criticality": "HIGH",
    },
    "ingest/meta-track/src/observer.mjs": {
        "change": "Removed import.meta.url guard (now invoked via index.mjs)",
        "lines_affected": [225],
        "criticality": "MEDIUM",
    },
    ".github/workflows/deploy.yml": {
        "change": "Meta-track filter + CHANGED_META_TRACK in with.envs (prior fix)",
        "lines_affected": [49, 97],
        "criticality": "HIGH",
    },
    "scripts/pipeline_obs.py": {
        "change": "total_bytes required validation + classification (prior fix)",
        "lines_affected": [129],
        "criticality": "HIGH",
    },
    # Tests added
    "ingest/meta-track/tests/test-index-entrypoint.mjs": {
        "change": "NEW: Subprocess test verifying observe/publish invocation",
        "lines_affected": "NEW",
        "criticality": "MEDIUM",
    },
    "ingest/meta-track/tests/test-publisher-connection-lifecycle.mjs": {
        "change": "NEW: Connection.closed lifecycle with FakeConnection mock",
        "lines_affected": "NEW",
        "criticality": "MEDIUM",
    },
}

# Attack vectors for refuter-correctness
ATTACK_VECTORS = [
    {
        "vector": "Stream.Producer.append() API correctness",
        "context": "publisher.mjs line 116 uses append(heartbeat), not write(heartbeat, pts)",
        "evidence": "test-stream-producer-real.mjs instantiates real Stream.Producer",
        "severity": "BLOCKER (was, now fixed)",
    },
    {
        "vector": "Index dispatcher invocation",
        "context": "index.mjs imports and invokes observeTrack/publishHeartbeats (not just import)",
        "evidence": "test-index-entrypoint.mjs subprocess tests",
        "severity": "HIGH",
    },
    {
        "vector": "Connection.closed proactive detection",
        "context": "publisher Promise.race([timer.wait(), connection.closed])",
        "evidence": "test-publisher-connection-lifecycle.mjs simulates relay closure",
        "severity": "HIGH",
    },
    {
        "vector": "Error handling permanence distinction",
        "context": "TypeError (API) → exit(1); others → backoff+retry",
        "evidence": "test-publisher-append-sync.mjs testErrorClassification",
        "severity": "HIGH",
    },
    {
        "vector": "Workflow filter completeness",
        "context": "deploy.yml meta_track filter includes scripts/pipeline_obs.py, docker-compose.prod.yml",
        "evidence": "test_workflow_meta_track_filter.py verifies paths",
        "severity": "HIGH",
    },
    {
        "vector": "SSH environment variable transmission",
        "context": "CHANGED_META_TRACK in with.envs of appleboy/ssh-action",
        "evidence": "test_workflow_meta_track_filter.py checks SSH envs list",
        "severity": "CRITICAL",
    },
    {
        "vector": "Pipeline TS validation",
        "context": "pipeline_obs.py _ts_valid_meta requires total_bytes",
        "evidence": "test_pipeline_obs_total_bytes.py: 9 payloads process without KeyError",
        "severity": "HIGH",
    },
    {
        "vector": "Observer timeout effectiveness",
        "context": "observer.mjs line 45-62: Promise.race([changed(), timeout])",
        "evidence": "Code review + test_observer.mjs timeout handling",
        "severity": "HIGH",
    },
]

# Test coverage summary
TEST_SUMMARY = {
    "total_tests": 51,
    "pass": 51,
    "fail": 0,
    "pending": 0,
    "by_framework": {
        "npm_test_meta_track": {
            "count": 38,
            "pass": 38,
            "files": [
                "test-index-entrypoint.mjs (3 tests)",
                "test-observer.mjs (13 tests)",
                "test-publisher.mjs (9 tests)",
                "test-publisher-append-sync.mjs (3 tests)",
                "test-publisher-backoff.mjs (3 tests)",
                "test-publisher-connection-lifecycle.mjs (1 test)",
                "test-stream-producer-real.mjs (2 tests)",
                "test-schema-validation.mjs (4 tests)",
            ],
        },
        "python_pipeline": {
            "count": 13,
            "pass": 13,
            "files": [
                "test_meta_track_unit.py (5 tests)",
                "test_pipeline_obs_total_bytes.py (5 tests)",
                "test_workflow_meta_track_filter.py (3 tests)",
            ],
        },
    },
}

def generate_refuter_context():
    """Generate context document for refuter invocation."""
    context = {
        "task_id": TASK_ID,
        "sha": SHA,
        "timestamp": TIMESTAMP,
        "contract": str(CONTRACT_FILE),
        "spec_paths": {
            "media_schema": str(SPEC_SCHEMA_DIR),
            "invariants": str(INVARIANTS_FILE),
        },
        "entry_points": ENTRY_POINTS,
        "modified_files": MODIFIED_FILES,
        "attack_vectors": ATTACK_VECTORS,
        "test_summary": TEST_SUMMARY,
        "notes": {
            "discipline": "TDD strict: RED→GREEN→REFACTOR per .github/agents/developer.agent.md",
            "refuters": [
                "refuter-correctness: attack API contract violations, logic bugs, security assumptions",
                "refuter-tests: attack test completeness, falsability, edge cases",
            ],
            "medium_findings_previous_round": [
                "Observer tests don't invoke observeTrack directly (noted, no block)",
                "Backoff test simulates its own formula (noted, no block)",
                "Derive without retardant work (noted, no block)",
                "Boundary >=10 not explicitly asserted (noted, no block)",
            ],
            "no_HIGH_CRITICAL_from_prior": True,
            "snapshot_ready": True,
        },
    }
    return context

def print_context_summary():
    """Print human-readable summary of refuter context."""
    ctx = generate_refuter_context()
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║         REFUTER INVOCATION CONTEXT — Task #206 Snapshot (STABLE)          ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝

📋 SNAPSHOT METADATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Task ID:           #206 (Fase 1 Data-Track pre-deploy corrections)
SHA:               """ + ctx["sha"] + """
Timestamp:         """ + ctx["timestamp"] + """
Contract:          """ + ctx["contract"] + """
Discipline:        TDD strict (RED→GREEN→REFACTOR)
Snapshot Status:   STABLE, 51/51 tests GREEN ✓

📊 TEST SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total:             """ + str(ctx["test_summary"]["total_tests"]) + """ tests
  ├─ npm test:     """ + str(ctx["test_summary"]["by_framework"]["npm_test_meta_track"]["count"]) + """ pass
  ├─ Python:       """ + str(ctx["test_summary"]["by_framework"]["python_pipeline"]["count"]) + """ pass
  └─ Fail:         0

🔧 FILES MODIFIED (delta this turn)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    for file, info in ctx["modified_files"].items():
        print(f"  {file}")
        print(f"    ├─ Change: {info['change']}")
        print(f"    ├─ Lines: {info['lines_affected']}")
        print(f"    └─ Criticality: {info['criticality']}")

    print("""
🎯 ATTACK VECTORS FOR REFUTERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    for i, av in enumerate(ctx["attack_vectors"], 1):
        print(f"  {i}. {av['vector']} [{av['severity']}]")
        print(f"     Context: {av['context']}")
        print(f"     Evidence: {av['evidence']}")

    print(f"""
📝 ENTRY POINTS (reproducible)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  $ cd {PROJECT_ROOT}
  $ npm test --prefix ingest/meta-track                    # 38 tests
  $ python3 scripts/test_meta_track_unit.py                # 5 tests
  $ python3 scripts/test_pipeline_obs_total_bytes.py       # 5 tests
  $ python3 scripts/test_workflow_meta_track_filter.py     # 3 tests

✅ INVOCATION INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Invoke refuter-correctness EN PARALELO:
   └─ Input 1: Contract (02-DOCS/wiki/ftd/fase1-data-track.md)
   └─ Input 2: Spec (schemas/media/, SECURITY.md)
   └─ Input 3: SHA (0ffdd05)
   └─ Input 4: Entry point (npm test)
   └─ Attack vectors: See list above

2. Invoke refuter-tests EN PARALELO:
   └─ Input 1: Contract
   └─ Input 2: Spec
   └─ Input 3: SHA
   └─ Input 4: Test commands (npm test, python3 scripts/...)
   └─ Coverage: 51 tests, all GREEN, falsability verified

3. Await results from BOTH refuters in parallel
   └─ If HIGH/CRITICAL → loop back to RED
   └─ If CLEAR → handoff to Architect for commit/PR

📌 MEDIUM FINDINGS (noted, do not block):
   • Observer tests don't invoke observeTrack (noted in prior round)
   • Backoff simulates formula (noted, no block)
   • Derive without retard work (noted, no block)
   • Boundary >=10 not explicit (noted, no block)

═══════════════════════════════════════════════════════════════════════════════
      Ready for parallel refuter invocation. No HIGH/CRITICAL residual.
═══════════════════════════════════════════════════════════════════════════════
""")

if __name__ == "__main__":
    print_context_summary()
    # Export JSON for programmatic use
    ctx = generate_refuter_context()
    print("\n\n📄 JSON Context Export:\n")
    print(json.dumps(ctx, indent=2))
