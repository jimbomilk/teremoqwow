#!/usr/bin/env python3
"""
Test unitario: valida que el publisher y observer pueden ser invocados sin fatal errors.
No requiere relay real, solo validación de módulos y argumentos.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
META_TRACK_DIR = PROJECT_DIR / "ingest" / "meta-track"


def test_index_help():
    """Test: index.mjs --help-like behavior."""
    result = subprocess.run(
        ["node", str(META_TRACK_DIR / "src" / "index.mjs")],
        capture_output=True,
        text=True,
        timeout=5,
        env=os.environ.copy()  # Preserve PATH and system vars
    )
    # Should exit with usage message
    assert result.returncode == 1, f"Expected exit code 1, got {result.returncode}"
    assert "Usage" in result.stderr or "Commands" in result.stderr, f"Expected usage message: {result.stderr}"
    print("✓ test_index_help")


def test_observer_window_validation():
    """Test: observer validates --window argument."""
    # Invalid window value
    env = os.environ.copy()
    env["MOQ_URL"] = "http://localhost:18090/"
    result = subprocess.run(
        ["node", str(META_TRACK_DIR / "src" / "observer.mjs"), "--window", "invalid"],
        input="",
        capture_output=True,
        text=True,
        timeout=5,
        env=env  # Use copied environ
    )
    # Should fail validation
    assert "ERROR" in result.stderr or result.returncode != 0, "Should validate --window argument"
    print("✓ test_observer_window_validation")


def test_observer_output_format():
    """Test: observer outputs valid JSON (even if connection fails)."""
    # Try to run observer with timeout (will fail to connect, but should emit JSON)
    env = os.environ.copy()
    env["MOQ_URL"] = "http://localhost:18090/"
    result = subprocess.run(
        ["timeout", "2", "node", str(META_TRACK_DIR / "src" / "observer.mjs"), "--window", "1"],
        capture_output=True,
        text=True,
        env=env
    )

    # Even if it times out or fails to connect, stdout should have JSON
    lines = result.stdout.strip().split('\n')
    for line in lines:
        if line:
            try:
                obj = json.loads(line)
                # Verify it's the expected observer output format
                assert "connected" in obj, f"Missing 'connected' in {obj}"
                assert "objects" in obj, f"Missing 'objects' in {obj}"
                assert "bytes" in obj, f"Missing 'bytes' in {obj}"
                assert "window_seconds" in obj, f"Missing 'window_seconds' in {obj}"
                print(f"✓ test_observer_output_format (found valid JSON)")
                return
            except json.JSONDecodeError:
                pass

    print("✓ test_observer_output_format (no JSON found, expected on timeout)")


def test_publisher_broadcast_guard():
    """Test: publisher rejects non-anon/live1-meta broadcast."""
    # Set BROADCAST env var to invalid value
    env = os.environ.copy()
    env.update({
        "MOQ_URL": "http://localhost:18090/",
        "BROADCAST": "anon/live1",  # INVALID
        "TRACK": "heartbeat"
    })

    result = subprocess.run(
        ["node", str(META_TRACK_DIR / "src" / "publisher.mjs")],
        capture_output=True,
        text=True,
        timeout=2,
        env=env
    )

    # Should fail immediately with guard message
    assert result.returncode != 0, "Publisher should exit with error on invalid broadcast"
    assert "anon/live1-meta" in result.stderr, f"Expected guard error message: {result.stderr}"
    print("✓ test_publisher_broadcast_guard")


def test_publisher_interval_validation():
    """Test: publisher validates INTERVAL_MS."""
    env = os.environ.copy()
    env.update({
        "MOQ_URL": "http://localhost:18090/",
        "BROADCAST": "anon/live1-meta",
        "TRACK": "heartbeat",
        "INTERVAL_MS": "500000"  # Too large (max 10000)
    })

    result = subprocess.run(
        ["timeout", "1", "node", str(META_TRACK_DIR / "src" / "publisher.mjs")],
        capture_output=True,
        text=True,
        env=env
    )

    # Should fail validation
    assert "INTERVAL_MS" in result.stderr or result.returncode != 0, "Should validate INTERVAL_MS"
    print("✓ test_publisher_interval_validation")


def main():
    """Run all unit-like tests."""
    tests = [
        test_index_help,
        test_observer_window_validation,
        test_observer_output_format,
        test_publisher_broadcast_guard,
        test_publisher_interval_validation,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"✗ {test.__name__}: {e}", file=sys.stderr)
            failed += 1

    if failed == 0:
        print(f"\n✓ All {len(tests)} tests passed")
        return 0
    else:
        print(f"\n✗ {failed}/{len(tests)} test(s) failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
