"""
Portal de Administrador — #147 (Fase 8-K)
Backend API FastAPI-compatible via Flask.
Requiere JWT RS256 con claim role=admin|superadmin.

Módulos: auth/roles, broadcasts, federación, DRM/rights,
         monetización, QoS, seguridad, feature flags.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Optional

import jwt
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins='*')  # dev only

ADMIN_ROLES = {"admin", "superadmin"}
OPERATOR_ROLES = {"admin", "superadmin", "operator"}
ANALYST_ROLES = {"admin", "superadmin", "operator", "analyst"}

# ── Auth ───────────────────────────────────────────────────────────────────────

def _load_public_key() -> str:
    path = os.environ.get("JWT_RS256_PUBLIC_KEY_PATH", "")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read()
    priv_path = os.environ.get("JWT_RS256_PRIVATE_KEY_PATH", "")
    if priv_path and os.path.exists(priv_path):
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, load_pem_private_key,
        )
        with open(priv_path, "rb") as f:
            priv = load_pem_private_key(f.read(), password=None)
        return priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    raise RuntimeError("JWT_RS256_PUBLIC_KEY_PATH no configurado")


def _require_role(*allowed_roles: str):
    """Devuelve (claims, None) o (None, error_response)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, (jsonify({"error": "Autenticación requerida"}), 401)
    try:
        claims = jwt.decode(auth[7:], _load_public_key(), algorithms=["RS256"])
    except Exception:
        return None, (jsonify({"error": "Token inválido o expirado"}), 401)
    if claims.get("role") not in allowed_roles:
        return None, (jsonify({"error": f"Requiere rol: {sorted(allowed_roles)}"}), 403)
    return claims, None


# ── Auditoría ─────────────────────────────────────────────────────────────────

_audit_log: list[dict] = []  # En prod: ClickHouse tabla audit_events


def _audit(claims: dict, action: str, detail: str = "") -> None:
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": claims.get("email", claims.get("sub", "?")),
        "role": claims.get("role"),
        "action": action,
        "detail": detail,
        "ip": request.remote_addr,
    }
    _audit_log.append(entry)
    logger.info("AUDIT %s %s %s", entry["actor"], action, detail)


# ── ClickHouse helper ─────────────────────────────────────────────────────────

def _ch_query(sql: str) -> list[dict]:
    base = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
    db = os.environ.get("CLICKHOUSE_DB", "teremoqwow")
    params = urllib.parse.urlencode({"query": sql, "database": db, "default_format": "JSONEachRow"})
    try:
        with urllib.request.urlopen(f"{base}/?{params}", timeout=5) as r:
            return [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]
    except Exception as exc:
        logger.warning("admin: ClickHouse: %s", exc)
        return []


# ── Redis helper ──────────────────────────────────────────────────────────────

_redis_client = None

def _redis():
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "")
        if url:
            try:
                import redis as _r
                c = _r.Redis.from_url(url, decode_responses=True)
                c.ping()
                _redis_client = c
            except Exception as exc:
                logger.warning("admin: Redis: %s", exc)
    return _redis_client


# ── MÓDULO: Broadcasts ─────────────────────────────────────────────────────────

AUDIO_KBPS_DEFAULT = 128  # mínimo EBU R128 broadcast estéreo


def _h264_level(resolution: str, fps: int) -> str:
    w, h = (int(x) for x in resolution.lower().replace('x','×').replace('×',' ').split()[:2])
    pixels = w * h
    if pixels <= 414720 and fps <= 30:   # ≤720×576
        return "3.0"
    if pixels <= 921600 and fps <= 30:   # ≤1280×720
        return "3.1"
    if pixels <= 2073600 and fps <= 30:  # ≤1920×1080
        return "4.0"
    if pixels <= 2073600 and fps <= 60:
        return "4.2"
    return "5.0"


def _default_broadcast(broadcast_id: str, bitrate_kbps: int = 8140, simulated: bool = False) -> dict:
    audio_kbps = max(AUDIO_KBPS_DEFAULT, int(bitrate_kbps * 0.03))  # al menos 128
    video_kbps = bitrate_kbps - audio_kbps
    return {
        "id": broadcast_id,
        "status": "active",
        "status_reason": "",
        "bitrate_kbps": bitrate_kbps,
        "viewers": 0,
        "uptime_s": 0,
        "encoder": "ffmpeg-testsrc2" + (" (simulado)" if simulated else ""),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "killed": False,
        "simulated": simulated,
        "ingest_type": "synthetic" if simulated else "testsrc2",
        # Video
        "video_codec": "H.264",
        "video_profile": "Main",
        "video_resolution": "1280x720",
        "video_fps": 30,
        "video_kbps": video_kbps,
        "video_level": _h264_level("1280x720", 30),
        # Audio
        "audio_codec": "AAC",
        "audio_kbps": audio_kbps,
        "audio_channels": 2,
        "audio_sample_rate": 48000,
        "audio_tracks": [{"id": "t0", "lang": "es", "label": "Español", "pid": 481, "default": True}],
        "lipsync_ms": 0,
    }

# Estado en memoria (en prod: leer del relay API / ClickHouse)
_broadcasts: dict[str, dict] = {
    "anon/live1": _default_broadcast("anon/live1")
}

_audio_alerts: list[dict] = []
_srt_ports: dict[str, int] = {}  # broadcast_id → puerto SRT asignado
_SRT_PORT_BASE = 9998


def _next_srt_port() -> int:
    used = set(_srt_ports.values())
    port = _SRT_PORT_BASE
    while port in used:
        port += 1
    return port


@app.route("/admin/broadcasts", methods=["GET"])
def list_broadcasts():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify(list(_broadcasts.values())), 200


@app.route("/admin/broadcasts/kill", methods=["POST"])
def kill_broadcast():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    broadcast_id = (request.get_json(silent=True) or {}).get("broadcast_id") or request.args.get("id", "")
    bcast_key = urllib.parse.unquote(broadcast_id)
    if bcast_key not in _broadcasts:
        return jsonify({"error": "broadcast no encontrado"}), 404
    _broadcasts[bcast_key]["status"] = "killed"
    _broadcasts[bcast_key]["killed"] = True
    _audit(claims, "kill_broadcast", bcast_key)
    # En prod: llamar a moq-relay API DELETE /broadcasts/{id}
    logger.info("admin: broadcast %s killed por %s", bcast_key, claims.get("email"))
    return jsonify({"status": "killed", "broadcast": bcast_key}), 200


@app.route("/admin/broadcasts/inject", methods=["POST"])
def inject_broadcast():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    broadcast_id  = body.get("broadcast_id", "anon/live1")
    ingest_type   = body.get("ingest_type", "testsrc2")  # testsrc2 | srt_push | srt_pull
    vcfg = body.get("video", {})
    acfg = body.get("audio", {})
    srt  = body.get("srt", {})

    resolution  = vcfg.get("resolution", "1280x720")
    fps         = int(vcfg.get("fps", 30))
    video_kbps  = int(vcfg.get("kbps", 4000))
    gop         = int(vcfg.get("gop_frames", body.get("gop_frames", 30)))
    profile     = vcfg.get("profile", "main").lower()
    level       = vcfg.get("level") or _h264_level(resolution, fps)
    audio_kbps  = max(AUDIO_KBPS_DEFAULT, int(acfg.get("kbps", AUDIO_KBPS_DEFAULT)))
    channels    = int(acfg.get("channels", 2))
    sample_rate = int(acfg.get("sample_rate", 48000))

    docker_ok    = False
    ffmpeg_cmd   = ""
    srt_endpoint = None

    if ingest_type == "testsrc2":
        vf = f"testsrc2=size={resolution}:rate={fps}"
        af = f"sine=frequency=1000:sample_rate={sample_rate}"
        docker_args = [
            "docker", "run", "-d", "--rm", "--name", "admin-inject",
            "--network", "teremoqwow-e2e",
            "linuxserver/ffmpeg:latest",
            "-re", "-f", "lavfi", "-i", vf,
            "-f", "lavfi", "-i", af,
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-profile:v", profile, "-level", level,
            "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
            "-b:v", f"{video_kbps}k",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-f", "mpegts", "pipe:1",
        ]
        import subprocess
        try:
            result = subprocess.run(docker_args, capture_output=True, text=True, timeout=5)
            docker_ok = result.returncode == 0
        except Exception:
            docker_ok = False

        moq_part = (
            f'docker run --rm -i --network teremoqwow-e2e moqdev/moq:0.12.7 '
            f'--connect tcp://moq-relay:4444/anon --broadcast {broadcast_id} import ts'
        )
        ffmpeg_cmd = (
            f"docker run --rm -i --network teremoqwow-e2e linuxserver/ffmpeg:latest \\\n"
            f"  -re -f lavfi -i '{vf}' \\\n"
            f"  -f lavfi -i '{af}' \\\n"
            f"  -c:v libx264 -preset ultrafast -tune zerolatency \\\n"
            f"  -profile:v {profile} -level {level} -g {gop} -keyint_min {gop} -sc_threshold 0 \\\n"
            f"  -b:v {video_kbps}k -c:a aac -b:a {audio_kbps}k -f mpegts pipe:1 | \\\n"
            f"{moq_part}"
        )

    elif ingest_type == "srt_push":
        port       = int(srt.get("port", _next_srt_port()))
        latency_ms = int(srt.get("latency_ms", 200))
        passphrase = srt.get("passphrase", "")
        pp_part    = f"&passphrase={passphrase}" if passphrase else ""
        srt_url    = f"srt://0.0.0.0:{port}?mode=listener&latency={latency_ms}{pp_part}"
        _srt_ports[broadcast_id] = port
        moq_part   = (
            f'docker run --rm -i --network teremoqwow-e2e moqdev/moq:0.12.7 '
            f'--connect tcp://moq-relay:4444/anon --broadcast {broadcast_id} import ts'
        )
        ffmpeg_cmd = (
            f"# Escucha conexión SRT entrante en 0.0.0.0:{port}\n"
            f"ffmpeg -i '{srt_url}' -c:v copy -c:a copy -f mpegts pipe:1 | \\\n"
            f"{moq_part}"
        )
        host_ip = os.environ.get("HOST_IP", "0.0.0.0")
        srt_endpoint = f"srt://{host_ip}:{port}?streamid={broadcast_id}&latency={latency_ms}"
        docker_ok = False

    elif ingest_type == "srt_pull":
        encoder_host = srt.get("host", "")
        port         = int(srt.get("port", 9998))
        latency_ms   = int(srt.get("latency_ms", 200))
        passphrase   = srt.get("passphrase", "")
        pp_part      = f"&passphrase={passphrase}" if passphrase else ""
        if not encoder_host:
            return jsonify({"error": "srt.host es obligatorio para srt_pull"}), 400
        srt_url  = f"srt://{encoder_host}:{port}?mode=caller&latency={latency_ms}{pp_part}"
        moq_part = (
            f'docker run --rm -i --network teremoqwow-e2e moqdev/moq:0.12.7 '
            f'--connect tcp://moq-relay:4444/anon --broadcast {broadcast_id} import ts'
        )
        ffmpeg_cmd = (
            f"# Conecta al encoder en {encoder_host}:{port}\n"
            f"ffmpeg -i '{srt_url}' -c:v copy -c:a copy -f mpegts pipe:1 | \\\n"
            f"{moq_part}"
        )
        docker_ok = False
    else:
        return jsonify({"error": f"ingest_type desconocido: {ingest_type}"}), 400

    _broadcasts[broadcast_id] = {
        "id": broadcast_id,
        "status": "active",
        "status_reason": "",
        "bitrate_kbps": video_kbps + audio_kbps,
        "viewers": 0,
        "uptime_s": 0,
        "encoder": f"ffmpeg-{ingest_type}",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "killed": False,
        "simulated": not docker_ok and ingest_type == "testsrc2",
        "ingest_type": ingest_type,
        "video_codec": vcfg.get("codec", "H.264"),
        "video_profile": vcfg.get("profile", "Main"),
        "video_level": level,
        "video_resolution": resolution,
        "video_fps": fps,
        "video_kbps": video_kbps,
        "audio_codec": acfg.get("codec", "AAC"),
        "audio_kbps": audio_kbps,
        "audio_channels": channels,
        "audio_sample_rate": sample_rate,
        "audio_tracks": [{"id": "t0", "lang": "es", "label": "Español", "pid": 481, "default": True}],
        "lipsync_ms": 0,
        "srt_port": _srt_ports.get(broadcast_id),
        "srt_endpoint": srt_endpoint,
    }
    _audit(claims, f"inject_broadcast:{ingest_type}", broadcast_id)
    return jsonify({
        "status": "injecting",
        "broadcast": broadcast_id,
        "ingest_type": ingest_type,
        "docker": docker_ok,
        "ffmpeg_cmd": ffmpeg_cmd,
        "srt_endpoint": srt_endpoint,
        "note": (
            "Stream real inyectado" if docker_ok
            else f"Copia el comando ffmpeg_cmd para iniciar la ingesta ({ingest_type})"
        ),
    }), 200


@app.route("/admin/broadcasts/stop-inject", methods=["POST"])
def stop_inject():
    """Para el inyector FFmpeg."""
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    import subprocess
    try:
        subprocess.run(["docker", "rm", "-f", "admin-inject"], capture_output=True, timeout=5)
    except Exception:
        pass
    broadcast_id = (request.get_json(silent=True) or {}).get("broadcast_id", "anon/live1")
    if broadcast_id in _broadcasts:
        _broadcasts[broadcast_id]["status"] = "stopped"
    _audit(claims, "stop_inject", broadcast_id)
    return jsonify({"status": "stopped"}), 200


@app.route("/admin/broadcasts/config", methods=["PATCH"])
def patch_broadcast():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    bcast_key = body.get("broadcast_id", "")
    if bcast_key not in _broadcasts:
        return jsonify({"error": "broadcast no encontrado"}), 404
    for field in ("bitrate_kbps", "gop_frames", "encoder"):
        if field in body:
            _broadcasts[bcast_key][field] = body[field]
    _audit(claims, "patch_broadcast", f"{bcast_key} {body}")
    return jsonify(_broadcasts[bcast_key]), 200


# ── MÓDULO: Audio ─────────────────────────────────────────────────────────────

@app.route("/admin/audio/tracks", methods=["GET"])
def audio_tracks():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    result = [
        {
            "broadcast_id": b["id"],
            "tracks": b.get("audio_tracks", []),
            "codec": b.get("audio_codec", "AAC"),
            "kbps": b.get("audio_kbps", 128),
            "channels": b.get("audio_channels", 2),
            "sample_rate": b.get("audio_sample_rate", 48000),
        }
        for b in _broadcasts.values()
    ]
    return jsonify(result), 200


@app.route("/admin/audio/lipsync", methods=["GET"])
def audio_lipsync():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify([
        {
            "broadcast_id": b["id"],
            "lipsync_ms": b.get("lipsync_ms", 0),
            "within_threshold": abs(b.get("lipsync_ms", 0)) < 40,
            "threshold_ms": 40,
        }
        for b in _broadcasts.values()
    ]), 200


@app.route("/admin/audio/alerts", methods=["GET"])
def audio_alerts_list():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify([a for a in _audio_alerts if not a.get("resolved")]), 200


@app.route("/admin/audio/alerts/simulate", methods=["POST"])
def simulate_audio_alert():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    kind = body.get("kind", "silence")  # silence | clipping | desync
    if kind not in ("silence", "clipping", "desync"):
        return jsonify({"error": "kind debe ser silence|clipping|desync"}), 400
    broadcast_id = body.get("broadcast_id", "anon/live1")
    alert = {
        "id": secrets.token_hex(4),
        "kind": kind,
        "broadcast_id": broadcast_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "simulated": True,
        "resolved": False,
    }
    _audio_alerts.append(alert)
    _audit(claims, f"simulate_audio_alert:{kind}", broadcast_id)
    return jsonify(alert), 201


@app.route("/admin/audio/alerts/resolve", methods=["POST"])
def resolve_audio_alert():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    alert_id = (request.get_json(silent=True) or {}).get("alert_id", "")
    for a in _audio_alerts:
        if a["id"] == alert_id:
            a["resolved"] = True
            return jsonify({"ok": True}), 200
    return jsonify({"error": "not found"}), 404


@app.route("/admin/audio/tracks/add", methods=["POST"])
def add_audio_track():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    bid = body.get("broadcast_id", "anon/live1")
    lang = body.get("lang", "en")[:5]
    label = body.get("label") or lang.upper()
    if bid not in _broadcasts:
        return jsonify({"error": "broadcast no encontrado"}), 404
    existing = _broadcasts[bid].get("audio_tracks", [])
    pid = 481 + len(existing)
    track = {"id": secrets.token_hex(3), "lang": lang, "label": label, "pid": pid, "default": False}
    _broadcasts[bid].setdefault("audio_tracks", []).append(track)
    _audit(claims, "add_audio_track", f"{bid} {lang}")
    return jsonify(track), 201


@app.route("/admin/audio/tracks/remove", methods=["POST"])
def remove_audio_track():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    bid = body.get("broadcast_id", "")
    track_id = body.get("track_id", "")
    if bid not in _broadcasts:
        return jsonify({"error": "broadcast no encontrado"}), 404
    before = len(_broadcasts[bid].get("audio_tracks", []))
    _broadcasts[bid]["audio_tracks"] = [
        t for t in _broadcasts[bid].get("audio_tracks", []) if t["id"] != track_id
    ]
    removed = before - len(_broadcasts[bid]["audio_tracks"])
    _audit(claims, "remove_audio_track", f"{bid} {track_id}")
    return jsonify({"ok": True, "removed": removed}), 200


# ── ISSUE #152 — Presets ───────────────────────────────────────────────────────

_BROADCAST_PRESETS = [
    {
        "id": "sd480",
        "label": "SD 480p",
        "video": {"codec": "H.264", "profile": "Main", "level": "3.0",
                  "resolution": "854x480", "fps": 25, "kbps": 1400, "gop_frames": 50},
        "audio": {"codec": "AAC", "channels": 2, "sample_rate": 48000, "kbps": 128},
        "total_kbps": 1528,
        "use_case": "Distribución SD, bajo ancho de banda",
    },
    {
        "id": "hd720",
        "label": "HD 720p",
        "video": {"codec": "H.264", "profile": "Main", "level": "3.1",
                  "resolution": "1280x720", "fps": 30, "kbps": 4000, "gop_frames": 30},
        "audio": {"codec": "AAC", "channels": 2, "sample_rate": 48000, "kbps": 128},
        "total_kbps": 4128,
        "use_case": "Streaming HD estándar",
    },
    {
        "id": "fhd1080",
        "label": "FHD 1080p",
        "video": {"codec": "H.264", "profile": "High", "level": "4.0",
                  "resolution": "1920x1080", "fps": 30, "kbps": 8000, "gop_frames": 30},
        "audio": {"codec": "AAC", "channels": 2, "sample_rate": 48000, "kbps": 192},
        "total_kbps": 8192,
        "use_case": "Producción broadcast calidad plena",
    },
    {
        "id": "moq_ultralow",
        "label": "MoQ Ultra-Low Latency",
        "video": {"codec": "H.264", "profile": "Main", "level": "3.1",
                  "resolution": "1280x720", "fps": 30, "kbps": 4000, "gop_frames": 15},
        "audio": {"codec": "AAC", "channels": 2, "sample_rate": 48000, "kbps": 128},
        "total_kbps": 4128,
        "use_case": "Optimizado para MoQ <500ms glass-to-glass",
    },
]


@app.route("/admin/broadcasts/presets", methods=["GET"])
def broadcast_presets():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify(_BROADCAST_PRESETS), 200


# ── ISSUE #150 — Create broadcast ─────────────────────────────────────────────

@app.route("/admin/broadcasts/create", methods=["POST"])
def create_broadcast():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    broadcast_id = body.get("broadcast_id", "")
    if not broadcast_id:
        return jsonify({"error": "broadcast_id es obligatorio"}), 400
    if broadcast_id in _broadcasts:
        return jsonify({"error": f"broadcast '{broadcast_id}' ya existe"}), 409

    vcfg = body.get("video", {})
    acfg = body.get("audio", {})

    resolution = vcfg.get("resolution", "1280x720")
    fps        = int(vcfg.get("fps", 30))
    video_kbps = int(vcfg.get("kbps", 4000))
    audio_kbps = max(AUDIO_KBPS_DEFAULT, int(acfg.get("kbps", AUDIO_KBPS_DEFAULT)))

    # Construir tracks con PID MPEG-TS desde 481
    raw_tracks = acfg.get("tracks", [{"lang": "es", "label": "Español"}])
    audio_tracks = [
        {"id": secrets.token_hex(3), "lang": t.get("lang", "es"),
         "label": t.get("label", t.get("lang", "es").upper()),
         "pid": 481 + i, "default": i == 0}
        for i, t in enumerate(raw_tracks)
    ]

    _broadcasts[broadcast_id] = {
        "id": broadcast_id,
        "status": "active",
        "status_reason": "",
        "bitrate_kbps": video_kbps + audio_kbps,
        "viewers": 0,
        "uptime_s": 0,
        "encoder": "synthetic",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "killed": False,
        "simulated": True,
        "ingest_type": "synthetic",
        "description": body.get("description", ""),
        "video_codec": vcfg.get("codec", "H.264"),
        "video_profile": vcfg.get("profile", "Main"),
        "video_level": vcfg.get("level") or _h264_level(resolution, fps),
        "video_resolution": resolution,
        "video_fps": fps,
        "video_kbps": video_kbps,
        "audio_codec": acfg.get("codec", "AAC"),
        "audio_kbps": audio_kbps,
        "audio_channels": int(acfg.get("channels", 2)),
        "audio_sample_rate": int(acfg.get("sample_rate", 48000)),
        "audio_tracks": audio_tracks,
        "lipsync_ms": 0,
    }
    _audit(claims, "create_broadcast", broadcast_id)
    return jsonify(_broadcasts[broadcast_id]), 201


# ── MÓDULO: Federación ─────────────────────────────────────────────────────────

_pending_nodes: list[dict] = []  # nodos pendientes de aprobación
_sim_subscriptions: dict[str, dict] = {}  # suscripciones de prueba


@app.route("/admin/federation/simulate-node", methods=["POST"])
def simulate_node():
    """Genera un nodo externo simulado que aparece como pendiente."""
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    node_id = body.get("node_id", f"sim-relay-{secrets.token_hex(3)}")
    region  = body.get("region", "eu-west-1")
    node = {
        "id": node_id,
        "region": region,
        "endpoint": f"tcp://{node_id}.dev.local:4444",
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "simulated": True,
    }
    _pending_nodes.append(node)
    _audit(claims, "simulate_node", node_id)
    return jsonify({"status": "pending", "node": node}), 201


@app.route("/admin/federation/nodes", methods=["GET"])
def list_nodes():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify({"active": [], "pending": _pending_nodes}), 200


@app.route("/admin/federation/nodes/<node_id>/approve", methods=["POST"])
def approve_node(node_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    _pending_nodes[:] = [n for n in _pending_nodes if n.get("id") != node_id]
    _audit(claims, "approve_node", node_id)
    return jsonify({"status": "approved", "node_id": node_id}), 200


@app.route("/admin/federation/nodes/<node_id>/revoke", methods=["POST"])
def revoke_node(node_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    if r:
        try:
            r.delete(f"federation:jwt:{node_id}")
        except Exception:
            pass
    _audit(claims, "revoke_node", node_id)
    return jsonify({"status": "revoked", "node_id": node_id}), 200


# ── MÓDULO: DRM / Rights ──────────────────────────────────────────────────────

@app.route("/admin/drm/subscriptions/simulate", methods=["POST"])
def simulate_subscription():
    """Crea una suscripción de prueba con max_plays configurable."""
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    sub_id = body.get("subscription_id", f"sim_{secrets.token_hex(4)}")
    max_plays = int(body.get("max_plays", 5))
    r = _redis()
    if r:
        try:
            r.set(f"rights:{sub_id}:plays", 0, ex=3600)
            r.set(f"rights:{sub_id}:max", max_plays, ex=3600)
        except Exception:
            pass
    _sim_subscriptions[sub_id] = {"subscription_id": sub_id, "max_plays": max_plays, "plays_used": 0}
    _audit(claims, "simulate_subscription", sub_id)
    return jsonify({"subscription_id": sub_id, "max_plays": max_plays, "plays_used": 0}), 201


@app.route("/admin/drm/subscriptions/consume", methods=["POST"])
def consume_play():
    """Simula una reproducción: incrementa el contador."""
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    sub_id = (request.get_json(silent=True) or {}).get("subscription_id", "")
    r = _redis()
    if r:
        try:
            plays = r.incr(f"rights:{sub_id}:plays")
            max_plays = int(r.get(f"rights:{sub_id}:max") or 0)
            allowed = plays <= max_plays
            if sub_id in _sim_subscriptions:
                _sim_subscriptions[sub_id]["plays_used"] = plays
            return jsonify({"subscription_id": sub_id, "plays_used": plays,
                            "max_plays": max_plays, "allowed": allowed}), 200
        except Exception:
            pass
    if sub_id in _sim_subscriptions:
        _sim_subscriptions[sub_id]["plays_used"] += 1
        plays = _sim_subscriptions[sub_id]["plays_used"]
        max_plays = _sim_subscriptions[sub_id]["max_plays"]
        return jsonify({"subscription_id": sub_id, "plays_used": plays,
                        "max_plays": max_plays, "allowed": plays <= max_plays}), 200
    return jsonify({"error": "suscripción no encontrada"}), 404


@app.route("/admin/drm/subscriptions/sim-list", methods=["GET"])
def list_sim_subscriptions():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify(list(_sim_subscriptions.values())), 200


@app.route("/admin/drm/subscriptions", methods=["GET"])
def list_subscriptions():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    r = _redis()
    subs = []
    if r:
        try:
            keys = r.keys("rights:*:plays")
            for key in keys[:50]:  # cap 50
                sub_id = key.split(":")[1]
                plays = int(r.get(key) or 0)
                subs.append({"subscription_id": sub_id, "plays_used": plays})
        except Exception:
            pass
    return jsonify(subs), 200


@app.route("/admin/drm/subscriptions/<sub_id>/reset", methods=["POST"])
def reset_subscription(sub_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    if r:
        try:
            r.delete(f"rights:{sub_id}:plays")
        except Exception:
            pass
    _audit(claims, "reset_max_plays", sub_id)
    return jsonify({"status": "reset", "subscription_id": sub_id}), 200


@app.route("/admin/drm/subscriptions/<sub_id>/revoke", methods=["POST"])
def revoke_subscription_jwt(sub_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    if r:
        try:
            # Invalidar tokens activos de este cliente
            r.set(f"revoked:sub:{sub_id}", "1", ex=86400 * 30)
        except Exception:
            pass
    _audit(claims, "revoke_jwt", sub_id)
    return jsonify({"status": "revoked", "subscription_id": sub_id}), 200


# ── MÓDULO: Monetización ──────────────────────────────────────────────────────

@app.route("/admin/monetization/stats", methods=["GET"])
def monetization_stats():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key or stripe_key.startswith("sk_test_replace"):
        return jsonify({
            "mrr_eur": 2900,
            "active_subscriptions": 3,
            "churn_rate_pct": 5.2,
            "dunning_count": 1,
            "source": "mock",
        }), 200
    try:
        import base64
        auth_hdr = base64.b64encode(f"{stripe_key}:".encode()).decode()
        req = urllib.request.Request(
            "https://api.stripe.com/v1/subscriptions?status=active&limit=100",
            headers={"Authorization": f"Basic {auth_hdr}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return jsonify({
            "active_subscriptions": len(data.get("data", [])),
            "source": "stripe",
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/admin/monetization/events", methods=["GET"])
def stripe_events():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    # Mock de últimos eventos Stripe
    return jsonify([
        {"id": f"evt_mock_{i}", "type": "invoice.paid", "created": int(time.time()) - i * 3600,
         "data": {"object": {"amount_paid": 2900, "currency": "eur"}}}
        for i in range(1, 6)
    ]), 200


# ── MÓDULO: QoS ───────────────────────────────────────────────────────────────

_sim_alerts: list[dict] = []  # alertas ficticias inyectadas desde el admin

_ALERT_TEMPLATES = {
    "LipSyncDrift":         {"severity": "critical", "description": "A/V offset simulado: 52ms > 45ms"},
    "BufferBelowThreshold": {"severity": "warning",  "description": "Buffer simulado: 320ms < 500ms"},
    "HighE2ELatency":       {"severity": "warning",  "description": "P95 latencia simulada: 850ms > 700ms"},
    "VideoContinuityError": {"severity": "critical", "description": "Error de continuidad simulado en anon/live1"},
}


@app.route("/admin/qos/alerts/test", methods=["POST"])
def inject_test_alert():
    """Inyecta una alerta ficticia visible en el módulo QoS."""
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    alert_name = (request.get_json(silent=True) or {}).get("alert_name", "LipSyncDrift")
    if alert_name not in _ALERT_TEMPLATES:
        return jsonify({"error": f"alerta desconocida, opciones: {list(_ALERT_TEMPLATES.keys())}"}), 400
    tmpl = _ALERT_TEMPLATES[alert_name]
    alert = {
        "labels":      {"alertname": alert_name, "severity": tmpl["severity"], "source": "simulated"},
        "annotations": {"description": tmpl["description"], "summary": f"[SIM] {alert_name}"},
        "state":       "firing",
        "activeAt":    time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "id":          secrets.token_hex(4),
    }
    _sim_alerts.append(alert)
    _audit(claims, "inject_test_alert", alert_name)
    return jsonify({"status": "fired", "alert": alert}), 201


@app.route("/admin/qos/alerts/resolve", methods=["POST"])
def resolve_test_alert():
    """Elimina una alerta simulada por id."""
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    alert_id = (request.get_json(silent=True) or {}).get("id", "")
    original = len(_sim_alerts)
    _sim_alerts[:] = [a for a in _sim_alerts if a.get("id") != alert_id]
    _audit(claims, "resolve_test_alert", alert_id)
    return jsonify({"resolved": len(_sim_alerts) < original}), 200


@app.route("/admin/qos/alerts", methods=["GET"])
def qos_alerts():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    real_alerts = []
    try:
        with urllib.request.urlopen(f"{prom_url}/api/v1/alerts", timeout=5) as resp:
            data = json.loads(resp.read())
        real_alerts = data.get("data", {}).get("alerts", [])
    except Exception as exc:
        logger.warning("admin: Prometheus: %s", exc)
    all_alerts = real_alerts + _sim_alerts
    return jsonify({"alerts": all_alerts, "count": len(all_alerts), "simulated": len(_sim_alerts)}), 200


@app.route("/admin/qos/latency", methods=["GET"])
def qos_latency():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    rows = _ch_query("""
        SELECT
            namespace,
            quantile(0.95)(toFloat64(timestamp_pts)) AS p95,
            count() AS samples
        FROM teremoqwow.telemetry_events
        WHERE toDateTime(timestamp_pts / 1000) >= now() - INTERVAL 15 MINUTE
        GROUP BY namespace
    """)
    return jsonify(rows if rows else [{"namespace": "anon/live1", "p95": 0, "samples": 0}]), 200


# ── MÓDULO: Seguridad ─────────────────────────────────────────────────────────

@app.route("/admin/security/rate-limit-hits", methods=["GET"])
def rate_limit_hits():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    hits = []
    if r:
        try:
            keys = r.keys("rl:*")
            for key in keys[:50]:
                ip = key.replace("rl:", "")
                count = int(r.get(key) or 0)
                ttl = r.ttl(key)
                hits.append({"ip": ip, "requests": count, "ttl_s": ttl})
        except Exception:
            pass
    hits.sort(key=lambda x: x.get("requests", 0), reverse=True)
    return jsonify(hits), 200


@app.route("/admin/security/rotate-secret", methods=["POST"])
def rotate_secret():
    claims, err = _require_role(*ADMIN_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    secret_type = body.get("type", "")
    if secret_type not in ("webhook", "jwt"):
        return jsonify({"error": "type debe ser 'webhook' o 'jwt'"}), 400
    new_secret = secrets.token_hex(32)
    _audit(claims, f"rotate_secret:{secret_type}", "redacted")
    return jsonify({
        "type": secret_type,
        "new_secret_preview": new_secret[:8] + "...",
        "action": "Actualiza la variable de entorno correspondiente y reinicia el servicio",
        "env_var": "WEBHOOK_SECRET" if secret_type == "webhook" else "JWT_RS256_PRIVATE_KEY_PATH",
    }), 200


# ── MÓDULO: Feature Flags ─────────────────────────────────────────────────────

_feature_flags: dict[str, bool] = {
    "ssai_enabled": False,
    "drm_soft_mode": False,
    "geo_blocking_global": True,
    "maintenance_mode": False,
}


@app.route("/admin/flags", methods=["GET"])
def get_flags():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify(_feature_flags), 200


@app.route("/admin/flags/<flag>", methods=["PATCH"])
def set_flag(flag: str):
    claims, err = _require_role(*ADMIN_ROLES)
    if err: return err
    if flag not in _feature_flags:
        return jsonify({"error": f"flag desconocido: {flag}"}), 404
    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify({"error": "campo 'enabled' requerido"}), 400
    _feature_flags[flag] = bool(body["enabled"])
    _audit(claims, f"set_flag:{flag}", str(body["enabled"]))
    return jsonify({flag: _feature_flags[flag]}), 200


# ── MÓDULO: Auditoría ─────────────────────────────────────────────────────────

@app.route("/admin/audit", methods=["GET"])
def get_audit_log():
    claims, err = _require_role(*ADMIN_ROLES)
    if err: return err
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify(_audit_log[-limit:][::-1]), 200


# ── Health ─────────────────────────────────────────────────────────────────────

@app.route("/admin/monitor/source", methods=["GET"])
def monitor_source():
    """Verifica si el broadcast está publicando intentando fetch del catalog."""
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    broadcast_id = request.args.get("broadcast", "anon/live1")
    relay_host = os.environ.get("MOQ_RELAY_TCP", "localhost:4444")
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--network", "teremoqwow-dev",
             "--network", "teremoqwow-e2e",
             "moqdev/moq:0.12.7",
             "--connect", f"tcp://moq-relay:4444/anon",
             "--broadcast", broadcast_id,
             "fetch", "catalog.json"],
            capture_output=True, text=True, timeout=6
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                catalog = json.loads(result.stdout)
                tracks = list(catalog.get("video", {}).get("renditions", {}).keys()) + \
                         list(catalog.get("audio", {}).get("renditions", {}).keys())
                return jsonify({
                    "broadcasting": True,
                    "broadcast": broadcast_id,
                    "tracks": tracks,
                    "has_clock": "clock" in catalog,
                    "source": "docker",
                }), 200
            except Exception:
                pass
    except Exception:
        pass
    # Sin Docker: inferir del estado en memoria
    bcast = _broadcasts.get(broadcast_id, {})
    active = bcast.get("status") == "active"
    return jsonify({
        "broadcasting": active,
        "broadcast": broadcast_id,
        "tracks": ["0.avc3", "1.aac"] if active else [],
        "has_clock": active,
        "source": "memory",
    }), 200


@app.route("/admin/relay/cert-hash", methods=["GET"])
def relay_cert_hash():
    """Devuelve el SHA-256 del cert TLS del relay para WebTransport."""
    # Sin autenticación: solo hash público del cert, no secreto.
    relay_web = os.environ.get("MOQ_RELAY_WEB", "http://localhost:8090")
    try:
        with urllib.request.urlopen(f"{relay_web}/fingerprint", timeout=2) as resp:
            data = resp.read().decode().strip()
            # El relay devuelve algo como "sha-256:ab12cd..." → extraer hex
            if ":" in data:
                data = data.split(":", 1)[1].replace(":", "").lower()
            return jsonify({"cert_hash": data, "source": "relay"}), 200
    except Exception:
        pass
    # Fallback: leer desde archivo .env.dev-cert generado por renew-dev-certs.sh
    for env_file in ("config/relay/certs/.env.dev-cert", ".env.dev-cert", ".env"):
        try:
            with open(env_file) as f:
                for line in f:
                    if line.startswith("RELAY_CERT_SHA256="):
                        cert_hash = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if cert_hash:
                            return jsonify({"cert_hash": cert_hash, "source": env_file}), 200
        except Exception:
            continue
    return jsonify({"cert_hash": "", "source": "none"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "admin-api", "status": "ok"}), 200


@app.route("/admin/me", methods=["GET"])
def admin_me():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify({k: claims[k] for k in ("sub", "email", "role") if k in claims}), 200


if __name__ == "__main__":
    port = int(os.environ.get("ADMIN_API_PORT", "9004"))
    app.run(host="0.0.0.0", port=port)
