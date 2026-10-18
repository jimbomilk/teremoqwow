#!/usr/bin/env python3
"""
Tests para pipeline_meta_observe.py (conversión de salida del observer a TS format).
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SCRIPT_META_OBSERVE = SCRIPT_DIR / "pipeline_meta_observe.py"


def run_meta_observe(observer_json: str) -> dict:
    """Ejecuta pipeline_meta_observe.py con JSON del observer como stdin."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_META_OBSERVE)],
        input=observer_json,
        capture_output=True,
        text=True
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"pipeline_meta_observe.py exited with code {result.returncode}: {result.stderr}")

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"Output is not valid JSON: {result.stdout}") from e


def test_observer_pass_case():
    """Test: observer with connected=true, objects>=10, monotonic=true -> TS with all info."""
    observer_output = json.dumps({
        "connected": True,
        "objects": 15,
        "bytes": 1755,
        "first_seq": 0,
        "last_seq": 14,
        "boot_ids": ["0123456789abcdef"],
        "monotonic": True,
        "window_seconds": 20
    })

    ts = run_meta_observe(observer_output)

    assert ts["total_bytes"] == 1755, f"Expected 1755 bytes, got {ts['total_bytes']}"
    assert ts["other_bytes"] == 1755, "heartbeat bytes should be in other_bytes"
    assert ts["observer_objects"] == 15, "observer_objects should be 15"
    assert ts["monotonic"] is True, "monotonic should be True"
    assert ts["pmt_seen"] is True, "pmt_seen should reflect observer connected"
    print("✓ test_observer_pass_case")


def test_observer_fail_no_objects():
    """Test: observer with connected=true but objects<10 -> TS with objects=0."""
    observer_output = json.dumps({
        "connected": True,
        "objects": 5,
        "bytes": 585,
        "first_seq": 0,
        "last_seq": 4,
        "boot_ids": ["0123456789abcdef"],
        "monotonic": True,
        "window_seconds": 20
    })

    ts = run_meta_observe(observer_output)

    assert ts["observer_objects"] == 5, "observer_objects should be 5"
    assert ts["pmt_seen"] is True, "observer connected"
    assert ts["monotonic"] is True, "still monotonic"
    # pipeline_obs.py will classify this as FAIL because objects < 10
    print("✓ test_observer_fail_no_objects")


def test_observer_fail_not_monotonic():
    """Test: observer with connected=true, objects>=10 but monotonic=false."""
    observer_output = json.dumps({
        "connected": True,
        "objects": 12,
        "bytes": 1404,
        "first_seq": 0,
        "last_seq": 11,
        "boot_ids": ["0123456789abcdef", "fedcba9876543210"],
        "monotonic": False,
        "window_seconds": 20
    })

    ts = run_meta_observe(observer_output)

    assert ts["observer_objects"] == 12
    assert ts["monotonic"] is False, "monotonic should be False"
    assert ts["pmt_seen"] is True
    # pipeline_obs.py will classify this as FAIL because not monotonic
    print("✓ test_observer_fail_not_monotonic")


def test_observer_unknown_no_connection():
    """Test: observer with connected=false."""
    observer_output = json.dumps({
        "connected": False,
        "objects": 0,
        "bytes": 0,
        "first_seq": 0,
        "last_seq": 0,
        "boot_ids": [],
        "monotonic": False,
        "window_seconds": 20
    })

    ts = run_meta_observe(observer_output)

    assert ts["pmt_seen"] is False, "pmt_seen should reflect no connection"
    assert ts["observer_objects"] == 0
    assert ts["total_bytes"] == 0
    # pipeline_obs.py will classify this as UNKNOWN
    print("✓ test_observer_unknown_no_connection")


def test_invalid_json():
    """Test: invalid JSON input -> fallback TS with zeros."""
    invalid_json = "not valid json at all"

    ts = run_meta_observe(invalid_json)

    assert ts["total_bytes"] == 0
    assert ts["observer_objects"] == 0
    assert ts["pmt_seen"] is False
    assert ts["monotonic"] is False
    print("✓ test_invalid_json")


def test_empty_input():
    """Test: empty input -> fallback TS with zeros."""
    ts = run_meta_observe("")

    assert ts["total_bytes"] == 0
    assert ts["pmt_seen"] is False
    print("✓ test_empty_input")


def test_observer_boot_id_changes():
    """Test: observer detects multiple boot_ids (publisher restarted)."""
    observer_output = json.dumps({
        "connected": True,
        "objects": 18,
        "bytes": 2106,
        "first_seq": 0,
        "last_seq": 9,
        "boot_ids": ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"],
        "monotonic": True,
        "window_seconds": 20
    })

    ts = run_meta_observe(observer_output)

    assert ts["observer_objects"] == 18
    assert ts["total_bytes"] == 2106
    # monotonic=true means seq is monotonic PER boot_id
    assert ts["monotonic"] is True
    print("✓ test_observer_boot_id_changes")


def main():
    """Run all tests."""
    tests = [
        test_observer_pass_case,
        test_observer_fail_no_objects,
        test_observer_fail_not_monotonic,
        test_observer_unknown_no_connection,
        test_invalid_json,
        test_empty_input,
        test_observer_boot_id_changes,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"✗ {test.__name__}: {e}", file=sys.stderr)
            return 1

    print(f"\n✓ All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
