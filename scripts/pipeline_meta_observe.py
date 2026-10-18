#!/usr/bin/env python3
"""
Procesa salida JSON del observer de meta-track y emite formato TS para pipeline_obs.py.

Entrada: JSON de una línea del observer (observer --window N)
{connected, objects, bytes, first_seq, last_seq, boot_ids, monotonic, window_seconds}

Salida: JSON en formato TS para pipeline_ts_count.py
{
  "total_bytes": bytes,
  "video_bytes": 0,
  "audio_bytes": 0,
  "other_bytes": bytes,   # los objetos de heartbeat son "otros"
  "pmt_seen": connected,
  "video_pids": [],
  "audio_pids": [],
  "monotonic": monotonic  # extensión para ingest.data
}

Criterio de PASS para ingest.data:
- connected: True
- objects >= 10 (en ventana 20s; escala proporcional en test)
- monotonic: True

Si no conectó o salida inválida: stderr con error, json de fallback.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def process_observer_output(line: str) -> dict:
    """Convierte salida del observer a formato TS-like con extensión."""
    try:
        obs = json.loads(line.strip())
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid observer JSON: {e}", file=sys.stderr)
        return {
            "total_bytes": 0,
            "video_bytes": 0,
            "audio_bytes": 0,
            "other_bytes": 0,
            "pmt_seen": False,
            "video_pids": [],
            "audio_pids": [],
            "monotonic": False,
            "observer_connected": False,
            "observer_objects": 0,
            "observer_error": str(e)
        }

    # Validaciones
    if not isinstance(obs, dict):
        print("ERROR: observer output is not a dict", file=sys.stderr)
        return _fallback_ts()

    connected = obs.get("connected", False)
    objects = obs.get("objects", 0)
    bytes_received = obs.get("bytes", 0)
    monotonic = obs.get("monotonic", False)
    window_seconds = obs.get("window_seconds", 20)

    if not isinstance(objects, int) or objects < 0:
        print(f"ERROR: objects is not a non-negative int: {objects}", file=sys.stderr)
        objects = 0

    if not isinstance(bytes_received, int) or bytes_received < 0:
        print(f"ERROR: bytes is not a non-negative int: {bytes_received}", file=sys.stderr)
        bytes_received = 0

    # TS-like output
    return {
        "total_bytes": bytes_received,
        "video_bytes": 0,
        "audio_bytes": 0,
        "other_bytes": bytes_received,  # heartbeat events are "other" (not A/V)
        "pmt_seen": connected,
        "video_pids": [],
        "audio_pids": [],
        "monotonic": monotonic,
        "observer_connected": connected,
        "observer_objects": objects,
        "observer_window_seconds": window_seconds
    }


def _fallback_ts() -> dict:
    """Fallback TS dict with all zeros."""
    return {
        "total_bytes": 0,
        "video_bytes": 0,
        "audio_bytes": 0,
        "other_bytes": 0,
        "pmt_seen": False,
        "video_pids": [],
        "audio_pids": [],
        "monotonic": False,
        "observer_connected": False,
        "observer_objects": 0
    }


def main():
    """Read one line of observer JSON from stdin and emit TS-like JSON."""
    try:
        line = sys.stdin.read()
        if not line.strip():
            print(json.dumps(_fallback_ts()))
            return 0

        ts = process_observer_output(line)
        print(json.dumps(ts))
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(json.dumps(_fallback_ts()))
        return 1


if __name__ == "__main__":
    sys.exit(main())
