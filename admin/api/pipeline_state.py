"""
Pipeline State — evaluador puro (#214). Sin Flask, sin Redis, sin Docker.

Solo interpreta observaciones de TRANSPORTE (llegada de datos / disponibilidad).
Nunca infiere calidad audiovisual: esa verificación es humana y vive aparte.

Reglas (fuente de verdad: schemas/admin/v1/pipeline-snapshot.json):
  señal   OK = fresca + PASS | DOWN = fresca + FAIL
          UNKNOWN = nunca observada | caducada (freshness STALE) | resultado UNKNOWN
  own     todas OK → OK; todas UNKNOWN → UNKNOWN; ninguna OK y alguna DOWN → DOWN; resto → DEGRADED
  fase    N+1 = BLOCKED si la fase N (estado FINAL) es DOWN/UNKNOWN/BLOCKED.
          DEGRADED aguas arriba NO bloquea; la razón de la fase siguiente lo anota.

Relojes (dos distintos, ambos con el `now` inyectado en la evaluación):
  last_transition_at = instante en que ESTA evaluación detecta un cambio de estado respecto
                       al estado persistido; no se reescribe mientras el estado no cambie.
                       La caducidad (OK→UNKNOWN) se detecta de forma perezosa, en la primera
                       lectura posterior al vencimiento, y ese es el instante registrado.
  last_green_at      = último instante (de evaluación) en que se vio OK. Persistido: sobrevive
                       a caer a DOWN/UNKNOWN/BLOCKED. Con lecturas esporádicas su precisión es
                       la del intervalo entre lecturas (se documenta como límite conocido).
  Se llevan por señal y por fase (la fase usa su estado FINAL, BLOCKED incluido).
  Estado previo implícito = UNKNOWN: ver un estado distinto la primera vez cuenta como cambio.

`build_snapshot` es pura: recibe el estado persistido y devuelve el nuevo + los eventos
TRANSITION a registrar; quien persiste (pipeline_api) lo hace de forma atómica.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

TTL_SECONDS = 1200
FUTURE_TOLERANCE_SECONDS = 60
REASON_MAX = 300

PHASE_ORDER = ("ingest", "relay", "player")
PHASES: dict[str, dict] = {
    "ingest": {"index": 1, "title": "Ingesta de vídeo/audio/data",
               "signals": ["ingest.video", "ingest.audio", "ingest.data"]},
    "relay": {"index": 2, "title": "MoQ + relay",
              "signals": ["relay.public", "relay.announce", "relay.catalog", "relay.tracks"]},
    "player": {"index": 3, "title": "Player + visualización",
               "signals": ["player.http", "player.subscribe"]},
}
VALID_SIGNALS = {s for p in PHASES.values() for s in p["signals"]}

SIGNAL_STATUSES = ("OK", "DOWN", "UNKNOWN")
TRANSPORT_STATUSES = ("OK", "DEGRADED", "DOWN", "BLOCKED", "UNKNOWN")
RESULTS = ("PASS", "FAIL", "UNKNOWN")

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


# ── Tiempo ────────────────────────────────────────────────────────────────────

def parse_rfc3339(value: Any) -> Optional[datetime]:
    """RFC 3339 con zona obligatoria (como `format: date-time`). None si no es válido."""
    if not isinstance(value, str) or not _RFC3339.match(value):
        return None
    try:
        dt = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        return dt.astimezone(timezone.utc)
    except (OverflowError, ValueError):   # p. ej. 0001-01-01T00:00:00+05:00 no cabe en UTC
        return None


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Señales ───────────────────────────────────────────────────────────────────

def sanitize_metrics(metrics: Any) -> Optional[dict]:
    """Solo métricas válidas según pipeline-observation.json; lo demás se descarta."""
    if not isinstance(metrics, dict):
        return None
    out: dict[str, int] = {}
    limits = {"bytes": (0, None), "objects": (0, None), "window_seconds": (1, 3600), "http_status": (100, 599)}
    for key, (lo, hi) in limits.items():
        v = metrics.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, int) and v >= lo and (hi is None or v <= hi):
            out[key] = v
    return out or None


def evaluate_signal(signal: str, obs: Any, now: datetime, ttl: int = TTL_SECONDS) -> dict:
    """→ {status, freshness, observed_at(datetime|None), reason, metrics(dict|None)}."""
    def never(reason: str) -> dict:
        return {"status": "UNKNOWN", "freshness": "NEVER", "observed_at": None,
                "reason": reason, "metrics": None}

    if obs is None:
        return never("nunca observada")
    if not isinstance(obs, dict) or obs.get("signal") != signal or obs.get("result") not in RESULTS:
        return never("observación inválida descartada")
    observed_at = parse_rfc3339(obs.get("observed_at"))
    if observed_at is None:
        return never("observación inválida descartada (observed_at)")

    age = (now - observed_at).total_seconds()
    if age < -FUTURE_TOLERANCE_SECONDS:
        return never(f"observación descartada: observed_at {int(-age)} s en el futuro")

    raw_reason = obs.get("reason")
    reason = raw_reason[:REASON_MAX] if isinstance(raw_reason, str) else ""
    metrics = sanitize_metrics(obs.get("metrics"))

    if age > ttl:
        return {"status": "UNKNOWN", "freshness": "STALE", "observed_at": observed_at,
                "reason": f"observación caducada (hace {int(age)} s, TTL {ttl} s); última: {reason}"[:REASON_MAX],
                "metrics": metrics}
    status = {"PASS": "OK", "FAIL": "DOWN", "UNKNOWN": "UNKNOWN"}[obs["result"]]
    return {"status": status, "freshness": "FRESH", "observed_at": observed_at,
            "reason": reason, "metrics": metrics}


# ── Fases ─────────────────────────────────────────────────────────────────────

def phase_own_status(statuses: list[str]) -> str:
    if all(s == "OK" for s in statuses):
        return "OK"
    if all(s == "UNKNOWN" for s in statuses):
        return "UNKNOWN"
    if "OK" not in statuses and "DOWN" in statuses:
        return "DOWN"
    return "DEGRADED"


def apply_dependencies(owns: list[str]) -> list[tuple[str, Optional[str]]]:
    """own_status por fase (en orden) → [(status final, blocked_by|None)]."""
    out: list[tuple[str, Optional[str]]] = []
    for i, own in enumerate(owns):
        if i > 0 and out[i - 1][0] in ("DOWN", "UNKNOWN", "BLOCKED"):
            out.append(("BLOCKED", PHASE_ORDER[i - 1]))
        else:
            out.append((own, None))
    return out


def _phase_reason(status: str, own: str, blocked_by: Optional[str], upstream: Optional[tuple[str, str]],
                  sigs: list[dict]) -> str:
    def label(s: dict) -> str:
        tag = {"STALE": " (caducada)", "NEVER": " (sin datos)"}.get(s["freshness"], "")
        return f"{s['signal']} {s['status']}{tag}"

    bad = [label(s) for s in sigs if s["status"] != "OK"]
    if own == "OK":
        own_txt = "Todas las señales OK"
    elif own == "DOWN":
        own_txt = "Ninguna señal OK: " + ", ".join(bad)
    elif own == "DEGRADED":
        own_txt = "Señales no OK: " + ", ".join(bad)
    elif any(s["freshness"] == "STALE" for s in sigs):
        own_txt = "Observaciones caducadas, sin dato vigente: " + ", ".join(bad)
    elif all(s["freshness"] == "NEVER" for s in sigs):
        own_txt = "Sin observaciones"
    else:
        own_txt = "Sin resultado concluyente: " + ", ".join(bad)

    if status == "BLOCKED":
        up_status = upstream[1] if upstream else "?"
        return f"Bloqueada: la fase {blocked_by} está {up_status}. Estado propio {own}: {own_txt}"
    if upstream and upstream[1] == "DEGRADED":
        return f"{own_txt}; aguas arriba degradada (upstream {upstream[0]} DEGRADED)"
    return own_txt


# ── Estado persistido ─────────────────────────────────────────────────────────

def empty_persisted() -> dict:
    return {"v": 1, "signals": {}, "phases": {}}


def load_persisted(raw: Any) -> dict:
    """Tolera basura: lo que no tiene la forma esperada se trata como 'sin estado previo'."""
    out = empty_persisted()
    if not isinstance(raw, dict):
        return out
    for section, valid in (("signals", SIGNAL_STATUSES), ("phases", TRANSPORT_STATUSES)):
        items = raw.get(section)
        if not isinstance(items, dict):
            continue
        for key, rec in items.items():
            if not isinstance(rec, dict) or rec.get("status") not in valid:
                continue
            out[section][key] = {
                "status": rec["status"],
                "last_transition_at": rec["last_transition_at"] if parse_rfc3339(rec.get("last_transition_at")) else None,
                "last_green_at": rec["last_green_at"] if parse_rfc3339(rec.get("last_green_at")) else None,
            }
    return out


def _track(prev: Optional[dict], status: str, now_iso: str) -> tuple[dict, bool, str]:
    prev = prev or {}
    prev_status = prev.get("status", "UNKNOWN")
    lt, lg = prev.get("last_transition_at"), prev.get("last_green_at")
    changed = status != prev_status
    if changed:
        lt = now_iso
    if status == "OK":
        lg = now_iso
    return {"status": status, "last_transition_at": lt, "last_green_at": lg}, changed, prev_status


# ── Snapshot ──────────────────────────────────────────────────────────────────

def build_snapshot(
    observations: dict[str, Any],
    humans: Optional[dict[str, dict]],
    persisted: Optional[dict],
    now: datetime,
) -> tuple[dict, dict, list[dict]]:
    """→ (snapshot conforme a pipeline-snapshot.json, nuevo estado persistido, eventos TRANSITION)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    now_iso = to_iso(now)
    prev = load_persisted(persisted)
    humans = humans or {}
    new = empty_persisted()
    events: list[dict] = []

    phase_sigs: dict[str, list[dict]] = {}
    phase_obs: dict[str, Optional[datetime]] = {}
    owns: list[str] = []

    for pid in PHASE_ORDER:
        sigs = []
        for name in PHASES[pid]["signals"]:
            ev = evaluate_signal(name, observations.get(name), now)
            track, _, _ = _track(prev["signals"].get(name), ev["status"], now_iso)
            new["signals"][name] = track
            item = {
                "signal": name,
                "status": ev["status"],
                "freshness": ev["freshness"],
                "ttl_seconds": TTL_SECONDS,
                "reason": ev["reason"],
                "observed_at": to_iso(ev["observed_at"]),
                "last_transition_at": track["last_transition_at"],
                "last_green_at": track["last_green_at"],
            }
            if ev["metrics"]:           # nunca `metrics: null`: se omite la clave
                item["metrics"] = ev["metrics"]
            sigs.append((item, ev["observed_at"]))
        phase_sigs[pid] = [s for s, _ in sigs]
        times = [t for _, t in sigs if t is not None]
        phase_obs[pid] = max(times) if times else None
        owns.append(phase_own_status([s["status"] for s in phase_sigs[pid]]))

    resolved = apply_dependencies(owns)
    phases = []
    prev_final: Optional[tuple[str, str]] = None   # (id de fase previa, estado final)
    for pid, own, (status, blocked_by) in zip(PHASE_ORDER, owns, resolved):
        sigs = phase_sigs[pid]
        reason = _phase_reason(status, own, blocked_by, prev_final, sigs)
        track, changed, from_status = _track(prev["phases"].get(pid), status, now_iso)
        new["phases"][pid] = track
        if changed:
            events.append({"type": "TRANSITION", "phase": pid, "at": now_iso,
                           "from_status": from_status, "to_status": status, "reason": reason})
        transport = {
            "status": status,
            "own_status": own,
            "reason": reason,
            "observed_at": to_iso(phase_obs[pid]),
            "last_transition_at": track["last_transition_at"],
            "last_green_at": track["last_green_at"],
            "stale": any(s["freshness"] in ("STALE", "NEVER") for s in sigs),
        }
        if blocked_by:
            transport["blocked_by"] = blocked_by
        phases.append({
            "id": pid,
            "index": PHASES[pid]["index"],
            "title": PHASES[pid]["title"],
            "transport": transport,
            "human": humans.get(pid) or {"status": "NOT_VERIFIED"},
            "signals": sigs,
        })
        prev_final = (pid, status)

    return {"generated_at": now_iso, "phases": phases}, new, events
