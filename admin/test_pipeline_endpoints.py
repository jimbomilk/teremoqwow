"""
Punto 3 — Endpoints /admin/pipeline/* (Flask test client, FakeRedis, JWT RS256 real).

Run: python3 -m pytest admin/test_pipeline_endpoints.py -q
"""
from __future__ import annotations

import json

import jwt as pyjwt
import pytest

import test_pipeline_support as S
from test_pipeline_fakeredis import FakeRedis

import pipeline_api as A

FIXED = S.plus(5000)
STATUS, HISTORY = "/admin/pipeline/status", "/admin/pipeline/history"


def vurl(phase="ingest"):
    return f"/admin/pipeline/phases/{phase}/verification"


@pytest.fixture()
def r():
    return FakeRedis()


@pytest.fixture()
def client(monkeypatch, r):
    monkeypatch.setattr(A, "_now", lambda: FIXED)
    return S.make_client(monkeypatch, r)


@pytest.fixture()
def audit_log():
    import admin_server
    return admin_server._audit_log


def hist(r):
    return [json.loads(x) for x in r.lists.get("pipeline:history", [])]


def human_events(r):
    return [e for e in hist(r) if e["type"].startswith("HUMAN_")]


# ── Auth / roles ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role,status_ok,write_ok", [
    ("analyst", True, False), ("operator", True, True), ("admin", True, True),
    ("superadmin", True, True), ("viewer", False, False), ("", False, False),
])
def test_roles(client, role, status_ok, write_ok):
    h = S.auth(role)
    assert (client.get(STATUS, headers=h).status_code == 200) is status_ok
    assert (client.get(HISTORY, headers=h).status_code == 200) is status_ok
    assert (client.post(vurl(), headers=h, json={}).status_code == 201) is write_ok
    assert (client.delete(vurl(), headers=h).status_code in (200,)) is write_ok


def test_no_token_and_hs256_token_are_401(client):
    for call in (lambda h: client.get(STATUS, headers=h), lambda h: client.post(vurl(), headers=h, json={}),
                 lambda h: client.delete(vurl(), headers=h), lambda h: client.get(HISTORY, headers=h)):
        assert call({}).status_code == 401
    # alg-confusion: HS256 firmado con la clave pública como secreto
    forged = pyjwt.encode({"sub": "x", "role": "admin"}, "secreto-cualquiera-de-32-bytes-minimo!!", algorithm="HS256")
    assert client.get(STATUS, headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.post(vurl(), headers={"Authorization": f"Bearer {forged}"}, json={}).status_code == 401


# ── Identidad y reloj: del servidor, nunca del cliente ────────────────────────

def test_operator_is_email_else_sub_and_timestamp_is_server_clock(client, r):
    resp = client.post(vurl("ingest"), headers=S.auth("operator", email="ana@x.dev"), json={"note": "n"})
    assert resp.status_code == 201
    h = resp.get_json()["human"]
    assert h == {"status": "VERIFIED", "verified_by": "ana@x.dev", "verified_at": S.iso(FIXED), "note": "n"}
    resp = client.post(vurl("relay"), headers=S.auth("operator", email=None, sub="sub-777"), json={})
    assert resp.get_json()["human"]["verified_by"] == "sub-777"
    resp = client.post(vurl("player"), headers=S.auth("operator", email="", sub="sub-888"), json={})
    assert resp.get_json()["human"]["verified_by"] == "sub-888"


@pytest.mark.parametrize("field,value", [
    ("operator", "mallory"), ("verified_by", "mallory"), ("verified_at", "2001-01-01T00:00:00Z"),
    ("email", "mallory@x"), ("actor", "m"), ("phase", "relay"), ("at", "2001-01-01T00:00:00Z"),
])
def test_forbidden_body_fields_are_400_and_nothing_is_written(client, r, audit_log, field, value):
    for method in ("post", "delete"):
        resp = getattr(client, method)(vurl(), headers=S.auth("operator"), json={field: value})
        assert resp.status_code == 400 and resp.get_json()["code"] == "VALIDATION_ERROR"
    assert not r.kv and not r.lists and not audit_log


def test_spoofing_headers_do_not_change_actor(client):
    resp = client.post(vurl(), headers={**S.auth("operator", email="real@x.dev"),
                                        "X-User": "mallory", "X-Forwarded-User": "mallory"}, json={})
    assert resp.get_json()["human"]["verified_by"] == "real@x.dev"


# ── Bodies hostiles: 400, nunca 500 ───────────────────────────────────────────

RAW_BAD = [
    b"{not json", b"\xff\xfe\x00", b"[]", b'"txt"', b"42", b"null", b"true", b'{"note": 5}',
    b'{"note": null}', b'{"note": {"a": 1}}', b'{"note": "' + b"x" * 501 + b'"}',
    b"[" * 200000, b"[" * 5000, b'{"note":"a"}' + b" " * 100000, b'{"note":"a"} {"note":"b"}',
]


@pytest.mark.parametrize("raw", RAW_BAD, ids=lambda b: repr(b[:20]))
@pytest.mark.parametrize("method", ["post", "delete"])
def test_hostile_bodies_never_500(client, r, method, raw):
    if method == "delete":
        client.post(vurl(), headers=S.auth("operator"), json={})
        raw = raw.replace(b'"note"', b'"reason"')
    resp = getattr(client, method)(vurl(), headers=S.auth("operator"), data=raw, content_type="application/json")
    assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["code"] == "VALIDATION_ERROR"


def test_empty_body_and_wrong_content_type_with_valid_json(client):
    assert client.post(vurl("ingest"), headers=S.auth("operator")).status_code == 201
    assert client.post(vurl("relay"), headers=S.auth("operator"), data="  ").status_code == 201
    resp = client.post(vurl("player"), headers=S.auth("operator"), data='{"note":"ok"}', content_type="text/plain")
    assert resp.status_code == 201 and resp.get_json()["human"]["note"] == "ok"


def test_note_limits_exact_500_ok_501_rejected_unicode_counts_chars(client):
    assert client.post(vurl("ingest"), headers=S.auth("operator"), json={"note": "ñ" * 500}).status_code == 201
    assert client.post(vurl("relay"), headers=S.auth("operator"), json={"note": "ñ" * 501}).status_code == 400


# ── 404 phase ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phase", ["nope", "INGEST", "ingest%20", "%20ingest", "ingest;x", "..", "%2e%2e",
                                   "ingest%00", "ingest%0a", "inges\u0442", "player2", "%27%20OR%201=1", "*", "0"])
def test_unknown_or_weird_phase_is_404_phase_not_found(client, r, phase):
    for method in ("post", "delete"):
        resp = getattr(client, method)(f"/admin/pipeline/phases/{phase}/verification",
                                       headers=S.auth("operator"), json={})
        assert resp.status_code == 404, (method, phase, resp.status_code)
        assert resp.get_json()["code"] == "PHASE_NOT_FOUND"
    assert not r.kv and not r.lists


def test_auth_is_checked_before_phase(client):
    assert client.post(vurl("nope"), json={}).status_code == 401
    assert client.post(vurl("nope"), headers=S.auth("analyst"), json={}).status_code == 403


# ── 409 y flujo ───────────────────────────────────────────────────────────────

def test_verify_revoke_flow_and_409s(client, r):
    h = S.auth("operator", email="ana@x.dev")
    assert client.delete(vurl(), headers=h).get_json()["code"] == "NOT_VERIFIED"
    assert client.post(vurl(), headers=h, json={"note": "uno"}).status_code == 201
    dup = client.post(vurl(), headers=h, json={"note": "dos"})
    assert dup.status_code == 409 and dup.get_json()["code"] == "ALREADY_VERIFIED"
    assert json.loads(r.kv["pipeline:phase:ingest:human"])["note"] == "uno"  # el 409 no pisa
    rev = client.delete(vurl(), headers=S.auth("admin", email="boss@x.dev"), json={"reason": "corte"})
    assert rev.status_code == 200
    assert rev.get_json()["human"] == {"status": "NOT_VERIFIED", "last_revoked_by": "boss@x.dev",
                                       "last_revoked_at": S.iso(FIXED)}
    assert client.delete(vurl(), headers=h).status_code == 409
    assert client.post(vurl(), headers=h, json={}).status_code == 201  # se puede volver a verificar
    # otras fases intactas
    snap = client.get(STATUS, headers=S.auth("analyst")).get_json()
    assert {p["id"]: p["human"]["status"] for p in snap["phases"]} == \
        {"ingest": "VERIFIED", "relay": "NOT_VERIFIED", "player": "NOT_VERIFIED"}


def test_human_is_independent_of_transport(client, r):
    S.seed_all(r, FIXED, default="FAIL")
    client.post(vurl("ingest"), headers=S.auth("operator"), json={})
    snap = client.get(STATUS, headers=S.auth("analyst")).get_json()
    ing = snap["phases"][0]
    assert ing["transport"]["status"] == "DOWN" and ing["human"]["status"] == "VERIFIED"
    S.seed_all(r, FIXED, default="PASS")
    snap = client.get(STATUS, headers=S.auth("analyst")).get_json()
    assert snap["phases"][1]["transport"]["status"] == "OK"
    assert snap["phases"][1]["human"]["status"] == "NOT_VERIFIED"  # transporte OK no verifica nada


@pytest.mark.parametrize("raw", ["basura", "[]", '{"status":"VERIFIED"}', '{"status":"VERIFIED","verified_by":3}'])
def test_corrupt_human_record_is_not_verified_never_green(client, r, raw):
    r.seed("pipeline:phase:ingest:human", raw)
    snap = client.get(STATUS, headers=S.auth("analyst")).get_json()
    assert snap["phases"][0]["human"] == {"status": "NOT_VERIFIED"}
    assert S.schema_errors(S.SNAPSHOT_ID, snap) == []
    assert client.delete(vurl(), headers=S.auth("operator")).status_code == 409


def test_concurrent_operation_lock_gives_409_in_progress_not_double_write(client, r):
    r.seed(f"{A.LOCK_HUMAN_PREFIX}ingest", "otro")
    resp = client.post(vurl(), headers=S.auth("operator"), json={})
    assert resp.status_code == 409 and resp.get_json()["code"] == "OPERATION_IN_PROGRESS"
    assert "pipeline:phase:ingest:human" not in r.kv and not hist(r)


# ── Auditoría e historial humano ──────────────────────────────────────────────

def test_audit_called_on_post_and_delete_only_on_success(client, r, audit_log):
    client.post(vurl("relay"), headers=S.auth("operator", email="ana@x.dev"), json={"note": "n"})
    client.post(vurl("relay"), headers=S.auth("operator"), json={})                    # 409: sin audit
    client.delete(vurl("relay"), headers=S.auth("operator", email="bob@x.dev"), json={"reason": "m"})
    client.delete(vurl("relay"), headers=S.auth("operator"))                           # 409: sin audit
    client.get(STATUS, headers=S.auth("analyst"))
    assert [(a["action"], a["actor"]) for a in audit_log] == [
        ("VERIFY_PIPELINE_PHASE", "ana@x.dev"), ("REVOKE_PIPELINE_PHASE_VERIFICATION", "bob@x.dev")]
    assert all("phase=relay" in a["detail"] for a in audit_log)


def test_human_history_events_have_actor_at_note_reason(client, r):
    client.post(vurl("player"), headers=S.auth("operator", email="ana@x.dev"), json={"note": "se ve bien"})
    client.delete(vurl("player"), headers=S.auth("operator", email="bob@x.dev"), json={"reason": "audio roto"})
    client.post(vurl("relay"), headers=S.auth("operator", email="ana@x.dev"), json={})
    ev = human_events(r)  # más reciente primero
    assert ev[0] == {"type": "HUMAN_VERIFIED", "phase": "relay", "at": S.iso(FIXED), "actor": "ana@x.dev"}
    assert ev[1] == {"type": "HUMAN_REVOKED", "phase": "player", "at": S.iso(FIXED), "actor": "bob@x.dev",
                     "reason": "audio roto"}
    assert ev[2] == {"type": "HUMAN_VERIFIED", "phase": "player", "at": S.iso(FIXED), "actor": "ana@x.dev",
                     "note": "se ve bien"}


# ── /history ──────────────────────────────────────────────────────────────────

def _fill(r, n, phase="ingest", start=0):
    for i in range(n):
        r.lpush("pipeline:history", json.dumps({"type": "HUMAN_VERIFIED", "phase": phase,
                                                "at": S.iso(S.plus(start + i)), "actor": f"u{i}"}))


def test_history_default_100_max_500_newest_first(client, r):
    _fill(r, 700)
    b = client.get(HISTORY, headers=S.auth("analyst")).get_json()
    assert b["limit"] == 100 and len(b["events"]) == 100
    assert b["events"][0]["actor"] == "u699" and b["events"][-1]["actor"] == "u600"
    b = client.get(HISTORY + "?limit=500", headers=S.auth("analyst")).get_json()
    assert b["limit"] == 500 and len(b["events"]) == 500
    b = client.get(HISTORY + "?limit=1", headers=S.auth("analyst")).get_json()
    assert len(b["events"]) == 1 and b["retention_max_events"] == 1000


@pytest.mark.parametrize("q", ["limit=0", "limit=-1", "limit=abc", "limit=501", "limit=", "limit=1.5", "limit=%2B5",
                               "limit=%D9%A5", "limit=1e2", "limit=99999999999999999999",
                               "since=ayer", "since=2026-10-12", "since=2026-10-12T12:00:00", "since=", "since=2026-13-45T00:00:00Z",
                               "phase=nope", "phase=", "phase=INGEST", "phase=ingest%00"])
def test_history_invalid_params_400(client, q):
    resp = client.get(f"{HISTORY}?{q}", headers=S.auth("analyst"))
    assert resp.status_code == 400 and resp.get_json()["code"] == "VALIDATION_ERROR", q


def test_history_filters_phase_and_since_inclusive_and_skips_corrupt(client, r):
    _fill(r, 5, "ingest", 0)
    _fill(r, 5, "relay", 100)
    r.lpush("pipeline:history", "basura")
    r.lpush("pipeline:history", json.dumps({"type": "NOPE", "phase": "ingest", "at": S.iso(S.plus(1))}))
    r.lpush("pipeline:history", json.dumps({"type": "TRANSITION", "phase": "ingest", "at": "mañana"}))
    r.lpush("pipeline:history", json.dumps({"type": "TRANSITION", "phase": "ingest", "at": S.iso(S.plus(3)),
                                            "from_status": "OK", "to_status": "DOWN", "reason": "x",
                                            "secreto": "no debe salir"}))
    b = client.get(HISTORY + "?phase=relay", headers=S.auth("analyst")).get_json()
    assert len(b["events"]) == 5 and all(e["phase"] == "relay" for e in b["events"])
    since = S.iso(S.plus(102))
    b = client.get(HISTORY, query_string={"since": since}, headers=S.auth("analyst")).get_json()
    assert {e["actor"] for e in b["events"] if e["phase"] == "relay"} == {"u2", "u3", "u4"}
    assert all(e["at"] >= since for e in b["events"])
    allv = client.get(HISTORY, headers=S.auth("analyst")).get_json()
    assert S.schema_errors(S.HISTORY_ID, allv) == []
    assert all("secreto" not in e for e in allv["events"])
    assert len(allv["events"]) == 11  # 3 corruptos descartados


def test_history_since_accepts_offset_and_compares_instants(client, r):
    _fill(r, 3, "ingest", 0)  # T0, T0+1, T0+2 (UTC)
    # T0+1 expresado con offset +02:00
    since = "2026-10-12T14:00:01+02:00"
    b = client.get(HISTORY, query_string={"since": since}, headers=S.auth("analyst")).get_json()
    assert [e["actor"] for e in b["events"]] == ["u2", "u1"]


def test_retention_exactly_1000_when_inserting_1005_human_events(client, r):
    for i in range(1005):  # 1005 eventos reales: HUMAN_VERIFIED (par) / HUMAN_REVOKED (impar)
        if i % 2 == 0:
            resp = client.post(vurl(), headers=S.auth("operator"), json={"note": f"n{i}"})
            assert resp.status_code == 201
        else:
            resp = client.delete(vurl(), headers=S.auth("operator"), json={"reason": f"r{i}"})
            assert resp.status_code == 200
    events = hist(r)
    assert len(events) == 1000
    assert events[0]["note"] == "n1004"          # el más reciente se conserva
    assert events[-1]["reason"] == "r5"          # se descartaron exactamente los 5 más antiguos (0..4)
    assert client.get(HISTORY + "?limit=500", headers=S.auth("analyst")).get_json()["retention_max_events"] == 1000


# ── Redis ausente / cae a mitad ───────────────────────────────────────────────

def test_no_redis_is_503_with_unknown_status_never_green(monkeypatch):
    c = S.make_client(monkeypatch, None)
    for resp in (c.get(STATUS, headers=S.auth("analyst")), c.get(HISTORY, headers=S.auth("analyst")),
                 c.post(vurl(), headers=S.auth("operator"), json={}), c.delete(vurl(), headers=S.auth("operator"))):
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["code"] == "REDIS_UNAVAILABLE" and body["details"] == {"status": "UNKNOWN"}
        assert "phases" not in body


# ops de status: 0 lock, 1 mget obs, 2 get estado, 3 mget human, 4 EXEC
@pytest.mark.parametrize("k", range(0, 5))
def test_status_redis_dies_mid_operation_503(client, r, k):
    S.seed_all(r, FIXED)
    r.fail_after = k
    resp = client.get(STATUS, headers=S.auth("analyst"))
    assert resp.status_code == 503 and resp.get_json()["details"] == {"status": "UNKNOWN"}


def test_history_redis_dies_503(client, r):
    r.fail_after = 0
    resp = client.get(HISTORY, headers=S.auth("analyst"))
    assert resp.status_code == 503 and resp.get_json()["details"] == {"status": "UNKNOWN"}


# ops de POST: 0 lock, 1 get human, 2 EXEC(set+lpush+ltrim). DELETE igual.
@pytest.mark.parametrize("k", range(0, 3))
def test_post_redis_dies_mid_operation_503_atomic_no_audit(client, r, audit_log, k):
    r.fail_after = k
    resp = client.post(vurl(), headers=S.auth("operator"), json={"note": "n"})
    assert resp.status_code == 503 and resp.get_json()["details"] == {"status": "UNKNOWN"}
    assert "pipeline:phase:ingest:human" not in r.kv and not r.lists.get("pipeline:history")
    assert not audit_log


@pytest.mark.parametrize("k", range(0, 3))
def test_delete_redis_dies_mid_operation_503_keeps_verification(client, r, audit_log, k):
    client.post(vurl(), headers=S.auth("operator"), json={})
    before = r.kv["pipeline:phase:ingest:human"]
    n_audit, n_hist = len(audit_log), len(r.lists["pipeline:history"])
    r.fail_after = k
    resp = client.delete(vurl(), headers=S.auth("operator"), json={"reason": "x"})
    assert resp.status_code == 503 and resp.get_json()["details"] == {"status": "UNKNOWN"}
    assert r.kv["pipeline:phase:ingest:human"] == before
    assert len(audit_log) == n_audit and len(r.lists["pipeline:history"]) == n_hist


def test_failure_releasing_lock_after_success_does_not_turn_success_into_error(client, r):
    r.fail_after = 3  # lock, get, EXEC OK; el delete del lock cae
    assert client.post(vurl(), headers=S.auth("operator"), json={}).status_code == 201
