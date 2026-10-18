#!/usr/bin/env python3
"""
Test: pipeline_obs.py _ts_valid_meta() rejects missing total_bytes
       derive() never crashes on missing total_bytes

Verifica que cuando observer no incluye total_bytes en su salida,
pipeline_obs clasifica como UNKNOWN (no FAIL), sin excepciones.
"""

import sys
import json
from pathlib import Path

# Add scripts dir to path so we can import pipeline_obs
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR / 'scripts'))

from pipeline_obs import _ts_valid_meta, derive, _session, _unknown

def test_ts_valid_meta_rejects_missing_total_bytes():
    """Test: _ts_valid_meta() rejects TS without total_bytes"""
    print('[TEST] test_ts_valid_meta_rejects_missing_total_bytes')

    # Valid TS with all required fields
    ts_valid = {
        "observer_objects": 5,
        "observer_connected": True,
        "monotonic": True,
        "total_bytes": 1024
    }
    result = _ts_valid_meta(ts_valid)
    assert result is not None, "Should accept valid TS with total_bytes"
    print('[PASS] Valid TS accepted')

    # Invalid TS without total_bytes (critical for derive())
    ts_missing_total_bytes = {
        "observer_objects": 5,
        "observer_connected": True,
        "monotonic": True
        # total_bytes missing!
    }
    result = _ts_valid_meta(ts_missing_total_bytes)
    assert result is None, "Should reject TS missing total_bytes"
    print('[PASS] TS missing total_bytes rejected')

    # Invalid: total_bytes is negative
    ts_negative_bytes = {
        "observer_objects": 5,
        "observer_connected": True,
        "monotonic": True,
        "total_bytes": -1
    }
    result = _ts_valid_meta(ts_negative_bytes)
    assert result is None, "Should reject negative total_bytes"
    print('[PASS] TS with negative total_bytes rejected')

    # Valid: total_bytes can be 0
    ts_zero_bytes = {
        "observer_objects": 5,
        "observer_connected": True,
        "monotonic": True,
        "total_bytes": 0
    }
    result = _ts_valid_meta(ts_zero_bytes)
    assert result is not None, "Should accept total_bytes=0"
    print('[PASS] TS with total_bytes=0 accepted')


def test_derive_no_crash_on_valid_ts():
    """Test: derive() doesn't crash when processing valid observer outputs"""
    print('[TEST] test_derive_no_crash_on_valid_ts')

    # 9 different measurement payloads per requirements
    # Each payload is a complete measurement dict for derive()
    payloads = [
        # 1. Connected, objects, bytes flowing
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 10,
                        "observer_connected": True,
                        "monotonic": True,
                        "total_bytes": 5000,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 2. Connected, zero objects
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 0,
                        "observer_connected": True,
                        "monotonic": True,
                        "total_bytes": 0,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 3. Connected, non-monotonic (dropping packets)
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 5,
                        "observer_connected": True,
                        "monotonic": False,  # <- violation
                        "total_bytes": 1000,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 4. Disconnected, no objects
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 0,
                        "observer_connected": False,
                        "monotonic": True,
                        "total_bytes": 0,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 5. Disconnected, stale objects
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 3,
                        "observer_connected": False,
                        "monotonic": True,
                        "total_bytes": 500,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 6. Connected, large byte count
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 100,
                        "observer_connected": True,
                        "monotonic": True,
                        "total_bytes": 1000000,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 7. Connected, 1 object
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 1,
                        "observer_connected": True,
                        "monotonic": True,
                        "total_bytes": 100,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 8. Connected, moderate load
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 50,
                        "observer_connected": True,
                        "monotonic": True,
                        "total_bytes": 50000,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
        # 9. Disconnected after being connected (edge case)
        {
            "sessions": {
                "anon/live1-meta": {
                    "connected": True,
                    "ts": {
                        "observer_objects": 2,
                        "observer_connected": False,
                        "monotonic": True,
                        "total_bytes": 200,
                        "observer_window_seconds": 20
                    }
                }
            }
        },
    ]

    for i, payload in enumerate(payloads):
        try:
            # derive() should not crash
            result = derive(payload)
            # Verify result is a list
            assert isinstance(result, list), f"derive() should return list, got {type(result)}"
            print(f'  [✓] Payload {i+1}: returned {len(result)} signals')
        except Exception as err:
            print(f'  [✗] Payload {i+1} crashed: {err}')
            raise

    print('[PASS] All 9 payloads processed without crash')


def test_session_returns_unknown_on_invalid_meta():
    """Test: _session() returns ('unknown', reason) when TS validation fails"""
    print('[TEST] test_session_returns_unknown_on_invalid_meta')

    # Session with missing total_bytes in TS
    m = {
        "sessions": {
            "anon/live1-meta": {
                "connected": True,
                "ts": {
                    "observer_objects": 5,
                    "observer_connected": True,
                    "monotonic": True
                    # total_bytes missing!
                }
            }
        }
    }

    kind, detail = _session(m, "anon/live1-meta")
    assert kind == "unknown", f"Should return 'unknown' for invalid TS, got {kind}"
    print(f'[PASS] Invalid TS handled as unknown: {detail}')


def test_derive_classifies_disconnected_as_unknown():
    """Test: derive() returns UNKNOWN for ingest.data when observer disconnects"""
    print('[TEST] test_derive_classifies_disconnected_as_unknown')

    # Observer disconnected
    m = {
        "sessions": {
            "anon/live1-meta": {
                "connected": True,
                "ts": {
                    "observer_objects": 0,
                    "observer_connected": False,  # <- disconnected
                    "monotonic": True,
                    "total_bytes": 0,
                    "observer_window_seconds": 20
                }
            }
        }
    }

    results = derive(m)

    # Find ingest.data signal
    ingest_data = None
    for sig in results:
        if sig.get("signal") == "ingest.data":
            ingest_data = sig
            break

    assert ingest_data is not None, "Missing ingest.data signal"
    result = ingest_data.get("result")
    assert result == "UNKNOWN", f"Disconnected observer should be UNKNOWN, got {result}"
    print(f'[PASS] Disconnected observer → UNKNOWN')


def test_derive_classifies_connected_nonmono_as_fail():
    """Test: derive() returns FAIL for ingest.data when not monotonic"""
    print('[TEST] test_derive_classifies_connected_nonmono_as_fail')

    # Observer connected but non-monotonic
    m = {
        "sessions": {
            "anon/live1-meta": {
                "connected": True,
                "ts": {
                    "observer_objects": 10,
                    "observer_connected": True,
                    "monotonic": False,  # <- not monotonic (packet drop)
                    "total_bytes": 1000,
                    "observer_window_seconds": 20
                }
            }
        }
    }

    results = derive(m)

    # Find ingest.data signal
    ingest_data = None
    for sig in results:
        if sig.get("signal") == "ingest.data":
            ingest_data = sig
            break

    assert ingest_data is not None, "Missing ingest.data signal"
    result = ingest_data.get("result")
    assert result == "FAIL", f"Non-monotonic observer should be FAIL, got {result}"
    print(f'[PASS] Non-monotonic observer → FAIL')


# Run all tests
tests = [
    test_ts_valid_meta_rejects_missing_total_bytes,
    test_derive_no_crash_on_valid_ts,
    test_session_returns_unknown_on_invalid_meta,
    test_derive_classifies_disconnected_as_unknown,
    test_derive_classifies_connected_nonmono_as_fail,
]

def main():
    failed = []
    for test_func in tests:
        try:
            test_func()
        except Exception as err:
            print(f'[FAIL] {test_func.__name__}: {err}')
            import traceback
            traceback.print_exc()
            failed.append(test_func.__name__)

    if failed:
        print(f'\n[FAILED] {len(failed)} test(s): {", ".join(failed)}')
        sys.exit(1)
    else:
        print(f'\n[SUCCESS] All {len(tests)} tests passed')
        sys.exit(0)

if __name__ == '__main__':
    main()
