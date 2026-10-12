"""
Punto 1 — Contrato: TODAS las respuestas reales de la app (Flask test client) se
validan con jsonschema contra schemas/admin/v1 + schemas/common/v1 (registry por $id).

Si el schema y el código discrepan, manda el schema (no se edita).
Run: python3 -m pytest admin/test_pipeline_contract.py -q
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator

import test_pipeline_support as S
from test_pipeline_fakeredis import FakeRedis


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture()
def r():
    return FakeRedis()


@pytest.fixture()
def client(monkeypatch, r):
    return S.make_client(monkeypatch, r)


def assert_valid(schema_id, instance):
    errs = S.schema_errors(schema_id, instance)
    assert not errs, f"{schema_id.rsplit('/', 1)[-1]} inválido: {errs}\n{json.dumps(instance, indent=1)[:1500]}"


def assert_error(resp, status, code):
    assert resp.status_code == status, resp.get_data(as_text=True)
    body = resp.get_json()
    assert_valid(S.ERROR_ID, body)
    assert body["code"] == code
    return body


# ── El propio harness de contrato ─────────────────────────────────────────────

def test_all_schema_files_load_by_id_and_are_valid_schemas():
    schemas = S.load_schemas()
    files = list((S.REPO / "schemas" / "admin" / "v1").glob("*.json")) + \
        list((S.REPO / "schemas" / "common" / "v1").glob("*.json"))
    assert len(schemas) == len(files) >= 6  # ningún $id duplicado/omitido
    for sid, doc in schemas.items():
        Draft202012Validator.check_schema(doc)
    # el $ref cruzado snapshot → observation#/properties/signal|metrics resuelve
    assert S.validator(S.SNAPSHOT_ID) is not None


def test_harness_can_fail_snapshot_with_metrics_null_and_bad_timestamp():
    """Si el validador no rechaza esto, los tests de contrato no prueban nada."""
    good_signal = {
        "signal": "ingest.video", "status": "OK", "freshness": "FRESH", "ttl_seconds": 1200,
        "reason": "x", "observed_at": "2026-10-12T12:00:00Z",
    }

    def snap(sig):
        ph = lambda i, pid: {  # noqa: E731
            "id": pid, "index": i, "title": "t", "human": {"status": "NOT_VERIFIED"}, "signals": [sig],
            "transport": {"status": "OK", "own_status": "OK", "reason": "", "observed_at": None,
                          "last_transition_at": None, "last_green_at": None, "stale": False},
        }
        return {"generated_at": "2026-10-12T12:00:00Z",
                "phases": [ph(1, "ingest"), ph(2, "relay"), ph(3, "player")]}

    assert S.schema_errors(S.SNAPSHOT_ID, snap(good_signal)) == []
    assert S.schema_errors(S.SNAPSHOT_ID, snap({**good_signal, "metrics": None}))
    assert S.schema_errors(S.SNAPSHOT_ID, snap({**good_signal, "observed_at": "ayer"}))
    assert S.schema_errors(S.SNAPSHOT_ID, snap({**good_signal, "extra": 1}))


# ── GET /status ───────────────────────────────────────────────────────────────

def test_status_empty_redis_conforms(client):
    resp = client.get("/admin/pipeline/status", headers=S.auth("analyst"))
    assert resp.status_code == 200
    assert_valid(S.SNAPSHOT_ID, resp.get_json())


def test_status_real_today_conforms_and_has_no_null_metrics(client, r):
    now = _now()
    S.seed_all(r, now, {"ingest.data": "FAIL"})
    S.seed(r, S.observation("ingest.video", "PASS", now, "ok",
                            {"bytes": 1000, "objects": 3, "window_seconds": 10}))
    S.seed(r, S.observation("player.http", "PASS", now, "ok", {"http_status": 200}))
    resp = client.get("/admin/pipeline/status", headers=S.auth("analyst"))
    snap = resp.get_json()
    assert_valid(S.SNAPSHOT_ID, snap)
    for ph in snap["phases"]:
        for sig in ph["signals"]:
            if sig["signal"] not in ("ingest.video", "player.http"):
                assert "metrics" not in sig  # se omite, nunca null
    assert "null" not in json.dumps([s.get("metrics") for p in snap["phases"] for s in p["signals"]
                                     if "metrics" in s])


def test_status_all_stale_conforms(client, r):
    S.seed_all(r, datetime(2020, 1, 1, tzinfo=timezone.utc))
    snap = client.get("/admin/pipeline/status", headers=S.auth("analyst")).get_json()
    assert_valid(S.SNAPSHOT_ID, snap)


def test_status_with_human_verified_and_revoked_conforms(client, r):
    S.seed_all(r, _now())
    assert client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"),
                       json={"note": "visto OK"}).status_code == 201
    assert client.post("/admin/pipeline/phases/relay/verification", headers=S.auth("operator"),
                       json={}).status_code == 201
    assert client.delete("/admin/pipeline/phases/relay/verification", headers=S.auth("operator"),
                         json={"reason": "corte"}).status_code == 200
    snap = client.get("/admin/pipeline/status", headers=S.auth("analyst")).get_json()
    assert_valid(S.SNAPSHOT_ID, snap)
    humans = {p["id"]: p["human"] for p in snap["phases"]}
    assert humans["ingest"]["status"] == "VERIFIED" and humans["ingest"]["verified_by"] == "ops@teremoqwow.dev"
    assert humans["relay"]["status"] == "NOT_VERIFIED" and "last_revoked_at" in humans["relay"]


# ── GET /history ──────────────────────────────────────────────────────────────

def test_history_empty_conforms(client):
    resp = client.get("/admin/pipeline/history", headers=S.auth("analyst"))
    assert resp.status_code == 200
    body = resp.get_json()
    assert_valid(S.HISTORY_ID, body)
    assert body == {"events": [], "limit": 100, "retention_max_events": 1000}


def test_history_with_all_event_types_conforms(client, r):
    S.seed_all(r, _now(), {"ingest.data": "FAIL"})
    client.get("/admin/pipeline/status", headers=S.auth("analyst"))  # genera TRANSITION
    client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"), json={"note": "n"})
    client.delete("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"), json={"reason": "m"})
    body = client.get("/admin/pipeline/history?limit=500", headers=S.auth("analyst")).get_json()
    assert_valid(S.HISTORY_ID, body)
    types = {e["type"] for e in body["events"]}
    assert types == {"TRANSITION", "HUMAN_VERIFIED", "HUMAN_REVOKED"}


# ── POST / DELETE verification ────────────────────────────────────────────────

HUMAN_REF = {"$ref": f"{S.SNAPSHOT_ID}#/$defs/humanVerification"}


def _human_errors(h):
    return [e.message for e in Draft202012Validator(
        HUMAN_REF, registry=S._REGISTRY, format_checker=S._format_checker).iter_errors(h)]


def test_post_and_delete_responses_conform(client):
    resp = client.post("/admin/pipeline/phases/player/verification", headers=S.auth("admin"),
                       json={"note": "ok"})
    assert resp.status_code == 201
    b = resp.get_json()
    assert set(b) == {"phase", "human"} and b["phase"] == "player"
    assert _human_errors(b["human"]) == [] and b["human"]["status"] == "VERIFIED"

    resp = client.delete("/admin/pipeline/phases/player/verification", headers=S.auth("admin"),
                         json={"reason": "x"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert set(b) == {"phase", "human"}
    assert _human_errors(b["human"]) == [] and b["human"]["status"] == "NOT_VERIFIED"


BAD_BODIES = [
    {"operator": "mallory"}, {"verified_by": "mallory"}, {"verified_at": "2020-01-01T00:00:00Z"},
    {"note": "x", "extra": 1}, {"note": 5}, {"note": "x" * 501}, {"note": None}, {"note": ["a"]},
    [], ["note"], "texto", 42, None,
]


@pytest.mark.parametrize("body", BAD_BODIES, ids=lambda b: repr(b)[:30])
def test_post_bad_bodies_are_400_validation_error_and_schema_agrees(client, body):
    # el schema también los rechaza (si no, el test estaría contradiciendo al contrato)
    verify_branch = S._SCHEMAS[S.COMMAND_ID]["anyOf"][0]
    assert not Draft202012Validator(verify_branch).is_valid(body)
    resp = client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"),
                       data=json.dumps(body), content_type="application/json")
    assert_error(resp, 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("body", [{"note": "ok"}, {"note": ""}, {"note": "x" * 500}, {}])
def test_post_good_bodies_are_201_and_schema_agrees(client, body):
    assert Draft202012Validator(S._SCHEMAS[S.COMMAND_ID]["anyOf"][0]).is_valid(body)
    resp = client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"),
                       data=json.dumps(body), content_type="application/json")
    assert resp.status_code == 201


@pytest.mark.parametrize("body", [{"operator": "m"}, {"note": "x"}, {"reason": 3}, {"reason": "x" * 501}, []])
def test_delete_bad_bodies_are_400(client, body):
    client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"), json={})
    resp = client.delete("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"),
                         data=json.dumps(body), content_type="application/json")
    assert_error(resp, 400, "VALIDATION_ERROR")


# ── Errores contra common/v1/error.json ───────────────────────────────────────

def test_error_401_403_conform_to_error_schema(client):
    assert_error(client.get("/admin/pipeline/status"), 401, "UNAUTHORIZED")
    assert_error(client.get("/admin/pipeline/status", headers={"Authorization": "Bearer basura"}), 401, "UNAUTHORIZED")
    assert_error(client.get("/admin/pipeline/status", headers=S.auth("viewer")), 403, "FORBIDDEN")
    assert_error(client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("analyst"), json={}),
                 403, "FORBIDDEN")
    assert_error(client.delete("/admin/pipeline/phases/ingest/verification", headers=S.auth("analyst")),
                 403, "FORBIDDEN")


def test_error_404_409_conform(client):
    assert_error(client.post("/admin/pipeline/phases/nope/verification", headers=S.auth("operator"), json={}),
                 404, "PHASE_NOT_FOUND")
    assert_error(client.delete("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator")),
                 409, "NOT_VERIFIED")
    client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"), json={})
    assert_error(client.post("/admin/pipeline/phases/ingest/verification", headers=S.auth("operator"), json={}),
                 409, "ALREADY_VERIFIED")


def test_error_400_history_conform(client):
    for q in ("limit=0", "limit=-1", "limit=abc", "limit=501", "since=ayer", "phase=nope"):
        assert_error(client.get(f"/admin/pipeline/history?{q}", headers=S.auth("analyst")), 400, "VALIDATION_ERROR")


def test_error_503_without_redis_conform_and_status_unknown(monkeypatch):
    client = S.make_client(monkeypatch, None)
    for method, url, kw in [
        ("get", "/admin/pipeline/status", {}),
        ("get", "/admin/pipeline/history", {}),
        ("post", "/admin/pipeline/phases/ingest/verification", {"json": {}}),
        ("delete", "/admin/pipeline/phases/ingest/verification", {}),
    ]:
        resp = getattr(client, method)(url, headers=S.auth("operator"), **kw)
        body = assert_error(resp, 503, "REDIS_UNAVAILABLE")
        assert body["details"]["status"] == "UNKNOWN"
