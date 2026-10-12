"""
Punto 2 — Semántica de estado (pipeline_state + persistencia Redis vía pipeline_api).

Todo se construye SOLO con observaciones inyectadas en Redis (FakeRedis); nada hardcodeado
verde. Los relojes son inyectados (`now`), dos evaluaciones con relojes distintos.

Run: python3 -m pytest admin/test_pipeline_state.py -q
"""
from __future__ import annotations

import itertools
import json
from datetime import timedelta

import pytest

import test_pipeline_support as S
from test_pipeline_fakeredis import FakeRedis

import pipeline_api as A
import pipeline_state as P

T0 = S.T0


def snap(r, now):
    s = A.get_snapshot(r, now)
    assert S.schema_errors(S.SNAPSHOT_ID, s) == [], "snapshot fuera de contrato"
    return s


def ph(s, pid):
    return next(p for p in s["phases"] if p["id"] == pid)


def sg(s, name):
    return next(x for p in s["phases"] for x in p["signals"] if x["signal"] == name)


def events(r):
    return [json.loads(x) for x in r.lrange("pipeline:history", 0, 999)]


# ── Forma ─────────────────────────────────────────────────────────────────────

def test_always_three_phases_in_order_with_index_1_to_3():
    for seeded in (False, True):
        r = FakeRedis()
        if seeded:
            S.seed_all(r, T0)
        s = snap(r, T0)
        assert [p["id"] for p in s["phases"]] == ["ingest", "relay", "player"]
        assert [p["index"] for p in s["phases"]] == [1, 2, 3]
        assert [len(p["signals"]) for p in s["phases"]] == [3, 4, 2]
        assert [x["signal"] for x in ph(s, "relay")["signals"]] == \
            ["relay.public", "relay.announce", "relay.catalog", "relay.tracks"]
        assert s["generated_at"] == S.iso(T0)


def test_snapshot_never_emits_metrics_null():
    r = FakeRedis()
    S.seed_all(r, T0)
    s = snap(r, T0)
    assert all("metrics" not in x for p in s["phases"] for x in p["signals"])
    S.seed(r, S.observation("ingest.video", "PASS", T0, "ok", {"bytes": 5, "objects": 0}))
    s = snap(r, T0)
    assert sg(s, "ingest.video")["metrics"] == {"bytes": 5, "objects": 0}
    assert "None" not in repr([x.get("metrics", {}) for p in s["phases"] for x in p["signals"]])


# ── Tablas de verdad (oráculo independiente escrito desde el schema) ──────────

def _oracle_own(statuses):
    if all(s == "OK" for s in statuses):
        return "OK"
    if all(s == "UNKNOWN" for s in statuses):
        return "UNKNOWN"
    if "OK" not in statuses and "DOWN" in statuses:
        return "DOWN"
    return "DEGRADED"


@pytest.mark.parametrize("n", [2, 3, 4])
def test_own_status_truth_table(n):
    for combo in itertools.product(["OK", "DOWN", "UNKNOWN"], repeat=n):
        assert P.phase_own_status(list(combo)) == _oracle_own(list(combo)), combo


def test_dependency_truth_table():
    owns = ["OK", "DEGRADED", "DOWN", "UNKNOWN"]
    for combo in itertools.product(owns, repeat=3):
        got = P.apply_dependencies(list(combo))
        finals = []
        for i, own in enumerate(combo):
            if i > 0 and finals[i - 1] in ("DOWN", "UNKNOWN", "BLOCKED"):
                finals.append("BLOCKED")
                assert got[i] == ("BLOCKED", ["ingest", "relay"][i - 1]), combo
            else:
                finals.append(own)
                assert got[i] == (own, None), combo


# ── (a) real de hoy ───────────────────────────────────────────────────────────

def test_a_real_today_ingest_degraded_relay_player_evaluated_not_blocked():
    r = FakeRedis()
    S.seed_all(r, T0, {"ingest.data": "FAIL"})
    s = snap(r, T0)
    ing, rel, pla = ph(s, "ingest"), ph(s, "relay"), ph(s, "player")
    assert ing["transport"]["status"] == "DEGRADED" == ing["transport"]["own_status"]
    assert [x["status"] for x in ing["signals"]] == ["OK", "OK", "DOWN"]
    assert rel["transport"]["status"] == "OK" and "blocked_by" not in rel["transport"]
    assert pla["transport"]["status"] == "OK" and "blocked_by" not in pla["transport"]
    reason = rel["transport"]["reason"].lower()
    assert "aguas arriba" in reason and "degradada" in reason and "ingest" in reason
    assert ing["transport"]["stale"] is False
    # la señal que falla aparece en el motivo de la fase (hechos de transporte)
    assert "ingest.data" in ing["transport"]["reason"]


# ── (b) sin observaciones ─────────────────────────────────────────────────────

def test_b_no_observations_ingest_unknown_never_downstream_blocked():
    r = FakeRedis()
    s = snap(r, T0)
    ing, rel, pla = ph(s, "ingest"), ph(s, "relay"), ph(s, "player")
    assert ing["transport"]["status"] == "UNKNOWN"
    assert all(x["freshness"] == "NEVER" and x["status"] == "UNKNOWN" and x["observed_at"] is None
               for x in ing["signals"])
    assert ing["transport"]["stale"] is True and ing["transport"]["observed_at"] is None
    assert rel["transport"]["status"] == "BLOCKED" and rel["transport"]["blocked_by"] == "ingest"
    assert rel["transport"]["own_status"] == "UNKNOWN"
    assert pla["transport"]["status"] == "BLOCKED" and pla["transport"]["blocked_by"] == "relay"
    assert len(rel["signals"]) == 4 and len(pla["signals"]) == 2


def test_b_blocked_keeps_own_status_and_real_signals():
    r = FakeRedis()
    S.seed_all(r, T0, {"ingest.video": "FAIL", "ingest.audio": "FAIL", "ingest.data": "FAIL"})
    S.seed(r, S.observation("relay.public", "FAIL", T0, "caído"))
    s = snap(r, T0)
    assert ph(s, "ingest")["transport"]["status"] == "DOWN"
    rel = ph(s, "relay")["transport"]
    assert rel["status"] == "BLOCKED" and rel["blocked_by"] == "ingest"
    assert rel["own_status"] == "DEGRADED"  # 3 PASS + 1 FAIL: calculado con señales propias
    assert [x["status"] for x in ph(s, "relay")["signals"]] == ["DOWN", "OK", "OK", "OK"]
    # player: el relay está BLOCKED → player BLOCKED por relay (aunque su own sea OK)
    pla = ph(s, "player")["transport"]
    assert pla["status"] == "BLOCKED" and pla["blocked_by"] == "relay" and pla["own_status"] == "OK"


# ── (c) caducadas ─────────────────────────────────────────────────────────────

def test_c_all_stale_is_unknown_not_down_and_distinguishable_from_fail():
    r = FakeRedis()
    S.seed_all(r, T0)
    s = snap(r, S.plus(1201))
    for p in s["phases"]:
        assert p["transport"]["status"] != "OK"
        assert p["transport"]["status"] != "DOWN" and p["transport"]["own_status"] == "UNKNOWN"
        assert p["transport"]["stale"] is True
        assert all(x["status"] == "UNKNOWN" and x["freshness"] == "STALE" for x in p["signals"])
        assert all(x["observed_at"] == S.iso(T0) for x in p["signals"])
    assert ph(s, "ingest")["transport"]["status"] == "UNKNOWN"
    assert "caducada" in ph(s, "ingest")["transport"]["reason"].lower()

    r2 = FakeRedis()
    S.seed_all(r2, S.plus(1201), default="FAIL")
    s2 = snap(r2, S.plus(1201))
    assert ph(s2, "ingest")["transport"]["status"] == "DOWN"
    assert ph(s2, "ingest")["transport"]["stale"] is False
    assert ph(s, "ingest")["transport"]["reason"] != ph(s2, "ingest")["transport"]["reason"]


def test_c_ttl_boundary_1200_fresh_1201_stale():
    r = FakeRedis()
    S.seed_all(r, T0)
    assert sg(snap(r, S.plus(1200)), "ingest.video")["freshness"] == "FRESH"
    assert sg(snap(r, S.plus(1201)), "ingest.video")["freshness"] == "STALE"
    assert sg(snap(r, S.plus(1200)), "ingest.video")["ttl_seconds"] == 1200


def test_c_mixed_fail_stale_pass_follow_schema_rules():
    r = FakeRedis()
    S.seed(r, S.observation("ingest.video", "PASS", S.plus(1000)))
    S.seed(r, S.observation("ingest.audio", "FAIL", S.plus(1000)))
    S.seed(r, S.observation("ingest.data", "PASS", T0))  # caducada en now=1201
    s = snap(r, S.plus(1201))
    assert [x["status"] for x in ph(s, "ingest")["signals"]] == ["OK", "DOWN", "UNKNOWN"]
    assert ph(s, "ingest")["transport"]["status"] == "DEGRADED"  # alguna OK y alguna no OK
    r = FakeRedis()
    S.seed(r, S.observation("ingest.audio", "FAIL", S.plus(1000)))
    S.seed(r, S.observation("ingest.data", "PASS", T0))
    s = snap(r, S.plus(1201))
    assert ph(s, "ingest")["transport"]["status"] == "DOWN"  # ninguna OK y alguna DOWN


# ── (d) FAIL fresco ───────────────────────────────────────────────────────────

def test_d_fresh_fail_is_down_not_stale():
    r = FakeRedis()
    S.seed_all(r, T0, {"ingest.video": "FAIL", "ingest.audio": "FAIL", "ingest.data": "FAIL"})
    s = snap(r, S.plus(30))
    assert all(x["status"] == "DOWN" and x["freshness"] == "FRESH" for x in ph(s, "ingest")["signals"])
    assert ph(s, "ingest")["transport"]["status"] == "DOWN"
    assert ph(s, "ingest")["transport"]["stale"] is False


# ── (e) result UNKNOWN ────────────────────────────────────────────────────────

def test_e_result_unknown_is_unknown_fresh_not_stale_not_down():
    r = FakeRedis()
    S.seed_all(r, T0, default="UNKNOWN")
    s = snap(r, T0)
    x = sg(s, "ingest.video")
    assert x["status"] == "UNKNOWN" and x["freshness"] == "FRESH" and x["observed_at"] == S.iso(T0)
    assert ph(s, "ingest")["transport"]["status"] == "UNKNOWN"
    assert ph(s, "ingest")["transport"]["stale"] is False
    assert ph(s, "relay")["transport"]["status"] == "BLOCKED"


# ── (f) futuro ────────────────────────────────────────────────────────────────

def test_f_future_observation_beyond_60s_is_not_trusted_and_within_60s_is_fresh():
    r = FakeRedis()
    S.seed(r, S.observation("ingest.video", "PASS", S.plus(61)))
    S.seed(r, S.observation("ingest.audio", "PASS", S.plus(60)))
    s = snap(r, T0)
    assert sg(s, "ingest.video")["status"] == "UNKNOWN" and sg(s, "ingest.video")["freshness"] != "FRESH"
    assert sg(s, "ingest.audio")["status"] == "OK" and sg(s, "ingest.audio")["freshness"] == "FRESH"


# ── Observaciones corruptas en Redis (defensa en profundidad) ─────────────────

@pytest.mark.parametrize("raw", [
    "no es json", "[]", "null", "42", '{"signal":"ingest.video"}',
    json.dumps({"signal": "ingest.video", "result": "MAYBE", "observed_at": "2026-10-12T12:00:00Z", "reason": "x"}),
    json.dumps({"signal": "ingest.video", "result": "PASS", "observed_at": "basura", "reason": "x"}),
    json.dumps({"signal": "ingest.video", "result": "PASS", "observed_at": "2026-10-12T12:00:00", "reason": "x"}),
    json.dumps({"signal": "ingest.video", "result": "PASS", "observed_at": 12345, "reason": "x"}),
])
def test_corrupt_observation_is_unknown_never_ok_and_snapshot_still_valid(raw):
    r = FakeRedis()
    r.seed("pipeline:signal:ingest.video:latest", raw)
    s = snap(r, T0)
    assert sg(s, "ingest.video")["status"] == "UNKNOWN"


def test_invalid_metrics_in_redis_are_dropped_not_propagated():
    r = FakeRedis()
    o = S.observation("ingest.video", "PASS", T0, "x",
                      {"bytes": -1, "objects": True, "window_seconds": 0, "http_status": 99, "evil": 1})
    S.seed(r, o)
    s = snap(r, T0)  # valida contra schema (no additionalProperties, no bool, etc.)
    assert "metrics" not in sg(s, "ingest.video")


# ── last_transition_at / last_green_at (señal y fase) ─────────────────────────

def test_transition_is_detection_instant_and_not_rewritten_on_unchanged_calls():
    r = FakeRedis()
    S.seed_all(r, T0)
    s0 = snap(r, T0)
    assert sg(s0, "ingest.video")["last_transition_at"] == S.iso(T0)
    assert ph(s0, "ingest")["transport"]["last_transition_at"] == S.iso(T0)
    # nueva medición fresca, mismo estado, 60 s después
    S.seed_all(r, S.plus(60))
    s1 = snap(r, S.plus(60))
    assert sg(s1, "ingest.video")["last_transition_at"] == S.iso(T0), "no se reescribe sin cambio"
    assert ph(s1, "ingest")["transport"]["last_transition_at"] == S.iso(T0)
    s2 = snap(r, S.plus(90))
    assert sg(s2, "ingest.video")["last_transition_at"] == S.iso(T0)


def test_transition_uses_injected_now_not_observed_at_or_wall_clock():
    r = FakeRedis()
    S.seed_all(r, T0)
    snap(r, S.plus(10))                       # detectado a T0+10
    s = snap(r, S.plus(20))
    assert sg(s, "ingest.video")["last_transition_at"] == S.iso(S.plus(10))
    assert sg(s, "ingest.video")["observed_at"] == S.iso(T0)


def test_last_green_survives_down_and_unknown_per_signal_and_per_phase():
    r = FakeRedis()
    S.seed_all(r, T0)
    snap(r, T0)
    snap(r, S.plus(60))                       # último instante OK visto: T0+60
    # ingest.video cae a FAIL en T0+120
    S.seed(r, S.observation("ingest.video", "FAIL", S.plus(120), "sin datos"))
    S.seed(r, S.observation("ingest.audio", "PASS", S.plus(120)))
    S.seed(r, S.observation("ingest.data", "PASS", S.plus(120)))
    s = snap(r, S.plus(120))
    v = sg(s, "ingest.video")
    assert v["status"] == "DOWN"
    assert v["last_transition_at"] == S.iso(S.plus(120))
    assert v["last_green_at"] == S.iso(S.plus(60)), "sobrevive a caer a DOWN"
    a = sg(s, "ingest.audio")
    assert a["status"] == "OK" and a["last_green_at"] == S.iso(S.plus(120)) \
        and a["last_transition_at"] == S.iso(T0)
    t = ph(s, "ingest")["transport"]
    assert t["status"] == "DEGRADED"
    assert t["last_transition_at"] == S.iso(S.plus(120)) and t["last_green_at"] == S.iso(S.plus(60))
    # todo caduca → UNKNOWN: sigue conservando el último verde
    s = snap(r, S.plus(120 + 1201))
    t = ph(s, "ingest")["transport"]
    assert t["status"] == "UNKNOWN"
    assert t["last_transition_at"] == S.iso(S.plus(120 + 1201))
    assert t["last_green_at"] == S.iso(S.plus(60))
    assert sg(s, "ingest.audio")["last_green_at"] == S.iso(S.plus(120))
    assert sg(s, "ingest.video")["last_green_at"] == S.iso(S.plus(60))


def test_never_green_signal_has_null_green_and_null_transition():
    r = FakeRedis()
    s = snap(r, T0)
    x = sg(s, "ingest.video")
    assert x["last_green_at"] is None and x["last_transition_at"] is None
    assert ph(s, "ingest")["transport"]["last_green_at"] is None


def test_state_is_persisted_in_redis_not_in_process():
    r = FakeRedis()
    S.seed_all(r, T0)
    snap(r, T0)
    clone = FakeRedis()
    clone.kv, clone.lists = dict(r.kv), {k: list(v) for k, v in r.lists.items()}
    S.seed_all(clone, S.plus(60))
    s = snap(clone, S.plus(60))
    assert sg(s, "ingest.video")["last_transition_at"] == S.iso(T0)
    assert len(events(clone)) == 3  # sin duplicados al reconstruir desde Redis


# ── Historial: perezoso, sin duplicados ───────────────────────────────────────

def test_transition_events_recorded_once_with_from_to_and_server_clock():
    r = FakeRedis()
    S.seed_all(r, T0)
    snap(r, T0)
    ev = events(r)
    assert {(e["phase"], e["from_status"], e["to_status"]) for e in ev} == \
        {("ingest", "UNKNOWN", "OK"), ("relay", "UNKNOWN", "OK"), ("player", "UNKNOWN", "OK")}
    assert all(e["type"] == "TRANSITION" and e["at"] == S.iso(T0) and e["reason"] for e in ev)
    for _ in range(3):
        snap(r, T0)
        snap(r, S.plus(5))
    assert len(events(r)) == 3


def test_expiry_transitions_are_lazy_on_read_and_not_duplicated():
    r = FakeRedis()
    S.seed_all(r, T0)
    snap(r, T0)
    assert len(events(r)) == 3
    # nadie lee durante 2000 s; la primera lectura detecta la caducidad
    snap(r, S.plus(2000))
    new = events(r)[:-3]
    got = {(e["phase"], e["from_status"], e["to_status"]) for e in new}
    assert got == {("ingest", "OK", "UNKNOWN"), ("relay", "OK", "BLOCKED"), ("player", "OK", "BLOCKED")}
    assert all(e["at"] == S.iso(S.plus(2000)) for e in new)
    n = len(events(r))
    for k in range(1, 5):
        snap(r, S.plus(2000 + 30 * k))
    assert len(events(r)) == n, "lecturas repetidas sin cambio no duplican"


def test_blocked_transition_when_upstream_goes_down_and_back():
    r = FakeRedis()
    S.seed_all(r, T0)
    snap(r, T0)
    S.seed_all(r, S.plus(60), default="PASS", results={s: "FAIL" for s in S.ALL_SIGNALS if s.startswith("ingest")})
    snap(r, S.plus(60))
    top = [(e["phase"], e["from_status"], e["to_status"]) for e in events(r)[:3]]
    assert ("ingest", "OK", "DOWN") in top and ("relay", "OK", "BLOCKED") in top
    S.seed_all(r, S.plus(120))
    s = snap(r, S.plus(120))
    assert ph(s, "relay")["transport"]["status"] == "OK"
    assert ph(s, "relay")["transport"]["last_transition_at"] == S.iso(S.plus(120))
    assert ph(s, "relay")["transport"]["last_green_at"] == S.iso(S.plus(120))


def test_history_retention_is_exactly_1000_events():
    r = FakeRedis()
    # alterna OK/DOWN en 1005 ciclos para generar muchos eventos
    for i in range(1005):
        res = "PASS" if i % 2 == 0 else "FAIL"
        S.seed_all(r, S.plus(i * 10), default=res)
        snap(r, S.plus(i * 10))
    assert len(r.lists["pipeline:history"]) == 1000
    newest = json.loads(r.lists["pipeline:history"][0])
    assert newest["at"] == S.iso(S.plus(1004 * 10))


# ── Concurrencia y fallos de Redis ────────────────────────────────────────────

def test_lock_held_by_another_worker_means_read_only_evaluation():
    r = FakeRedis()
    S.seed_all(r, T0)
    r.seed(A.LOCK_STATE_KEY, "otro-worker")
    s = snap(r, T0)
    assert ph(s, "ingest")["transport"]["status"] == "OK"
    assert A.STATE_KEY not in r.kv and "pipeline:history" not in r.lists


# operaciones de get_snapshot: 0 lock, 1 mget obs, 2 get estado, 3 mget human, 4 EXEC(estado+eventos)
@pytest.mark.parametrize("k", range(0, 5))
def test_redis_dying_mid_operation_raises_unavailable_and_persists_nothing_partial(k):
    r = FakeRedis()
    S.seed_all(r, T0)
    r.fail_after = k
    try:
        A.get_snapshot(r, T0)
    except A.RedisUnavailable:
        pass
    else:
        pytest.fail(f"con fail_after={k} debió caer (se necesitan más operaciones)")
    r.fail_after = None
    r.down = False
    # coherencia: o hay estado Y eventos, o ninguno de los dos
    has_state, has_ev = A.STATE_KEY in r.kv, bool(r.lists.get("pipeline:history"))
    assert has_state == has_ev
    r.kv.pop(A.LOCK_STATE_KEY, None)


def test_redis_exception_types_other_than_connection_error_are_also_unavailable():
    class Boom(FakeRedis):
        def mget(self, keys):
            raise RuntimeError("boom")
    with pytest.raises(A.RedisUnavailable):
        A.get_snapshot(Boom(), T0)
