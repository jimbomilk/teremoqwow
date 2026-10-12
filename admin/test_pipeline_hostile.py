"""
Tipos hostiles en Redis (H4) y reloj de observación de fase (H5).

Run: python3 -m pytest admin/test_pipeline_hostile.py -q
"""
from __future__ import annotations

import json

import pytest

import test_pipeline_support as S
from test_pipeline_fakeredis import FakeRedis

import pipeline_api as A

FIXED = S.plus(5000)
STATUS, HISTORY = "/admin/pipeline/status", "/admin/pipeline/history"


@pytest.fixture()
def r():
    return FakeRedis()


@pytest.fixture()
def client(monkeypatch, r):
    monkeypatch.setattr(A, "_now", lambda: FIXED)
    return S.make_client(monkeypatch, r)


HOSTILE = [[], [1, 2], {}, {"a": 1}, 0, 42, 1.5, True, None, "", "x", [[]], {"a": {"b": []}}]
GOOD_EVENT = {"type": "TRANSITION", "phase": "relay", "at": "2026-10-12T12:00:00Z",
              "from_status": "OK", "to_status": "DOWN", "reason": "r"}


def _history(client):
    resp = client.get(HISTORY, headers=S.auth("analyst"))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert S.schema_errors(S.HISTORY_ID, body) == []
    return body


# ── H4: historial ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["type", "phase", "at", "from_status", "to_status", "reason", "actor", "note"])
@pytest.mark.parametrize("bad", HOSTILE, ids=repr)
def test_history_event_with_hostile_field_never_500_and_rest_survives(client, r, field, bad):
    r.lpush("pipeline:history", json.dumps(GOOD_EVENT))
    r.lpush("pipeline:history", json.dumps({**GOOD_EVENT, field: bad}))
    events = _history(client)["events"]
    assert any(e == GOOD_EVENT for e in events), "el evento sano debe sobrevivir"
    assert len(events) <= 2
    for e in events:                      # nada hostil se cuela tal cual
        assert e["phase"] in ("ingest", "relay", "player")


@pytest.mark.parametrize("raw", ["[]", "null", "42", '"s"', "true", "[[]]", "{", "[" * 100000, '{"a":' * 100000])
def test_history_non_object_json_items_are_dropped(client, r, raw):
    r.lpush("pipeline:history", json.dumps(GOOD_EVENT))
    r.lpush("pipeline:history", raw)
    assert _history(client)["events"] == [GOOD_EVENT]


@pytest.mark.parametrize("bad", HOSTILE, ids=repr)
def test_history_filter_phase_param_stays_validated(client, r, bad):
    r.lpush("pipeline:history", json.dumps({**GOOD_EVENT, "phase": bad}))
    assert client.get(HISTORY + "?phase=relay", headers=S.auth("analyst")).status_code == 200


@pytest.mark.parametrize("at", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+23:59"])
def test_extreme_dates_do_not_500_anywhere(client, r, at):
    r.lpush("pipeline:history", json.dumps({**GOOD_EVENT, "at": at}))
    S.seed(r, S.observation("ingest.video", "PASS", S.plus(4990), "x") | {"observed_at": at})
    r.seed("pipeline:phase:ingest:human",
           json.dumps({"status": "VERIFIED", "verified_by": "a", "verified_at": at}))
    r.seed("pipeline:state:v1", json.dumps({"v": 1, "signals": {"ingest.video": {
        "status": "OK", "last_transition_at": at, "last_green_at": at}}, "phases": {}}))
    assert client.get(HISTORY + "?since=" + "2026-01-01T00:00:00Z", headers=S.auth("analyst")).status_code == 200
    resp = client.get(STATUS, headers=S.auth("analyst"))
    assert resp.status_code == 200
    body = resp.get_json()
    assert S.schema_errors(S.SNAPSHOT_ID, body) == []
    assert body["phases"][0]["human"]["status"] == "NOT_VERIFIED"


# ── H4: snapshot con basura en observaciones / estado previo / humano ─────────

def _assert_honest(client):
    resp = client.get(STATUS, headers=S.auth("analyst"))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert S.schema_errors(S.SNAPSHOT_ID, body) == []
    return body


def _no_green(body):
    for p in body["phases"]:
        assert p["transport"]["status"] != "OK"
        assert p["human"]["status"] == "NOT_VERIFIED"
        assert all(s["status"] != "OK" for s in p["signals"])


@pytest.mark.parametrize("bad", HOSTILE, ids=repr)
@pytest.mark.parametrize("field", ["signal", "result", "observed_at", "reason", "metrics"])
def test_observation_hostile_field_never_500_never_green(client, r, field, bad):
    S.seed_all(r, S.plus(4990))
    base = S.observation("ingest.video", "PASS", S.plus(4990), "x", {"bytes": 1})
    r.seed("pipeline:signal:ingest.video:latest", json.dumps({**base, field: bad}))
    body = _assert_honest(client)
    video = body["phases"][0]["signals"][0]
    if field in ("signal", "result", "observed_at") and bad != base[field]:
        assert video["status"] == "UNKNOWN"


@pytest.mark.parametrize("bad", HOSTILE, ids=repr)
def test_persisted_state_hostile_shapes_never_500(client, r, bad):
    S.seed_all(r, S.plus(4990))
    rec = {"status": "OK", "last_transition_at": "2026-10-12T12:00:00Z", "last_green_at": "2026-10-12T12:00:00Z"}
    for state in (
        bad,
        {"v": 1, "signals": bad, "phases": bad},
        {"v": 1, "signals": {"ingest.video": bad}, "phases": {"ingest": bad}},
        {"v": 1, "signals": {"ingest.video": {**rec, "status": bad}}, "phases": {"ingest": {**rec, "status": bad}}},
        {"v": 1, "signals": {"ingest.video": {**rec, "last_green_at": bad, "last_transition_at": bad}},
         "phases": {}},
    ):
        r.seed("pipeline:state:v1", json.dumps(state))
        assert _assert_honest(client)["phases"]


@pytest.mark.parametrize("raw", ["[]", "null", "42", '"s"', "{", "[" * 100000, "\x00", "{\"a\":" * 100000])
def test_persisted_state_non_object_json(client, r, raw):
    S.seed_all(r, S.plus(4990))
    r.seed("pipeline:state:v1", raw)
    assert _assert_honest(client)["phases"]


@pytest.mark.parametrize("field", ["status", "verified_by", "verified_at", "note", "last_revoked_by", "last_revoked_at"])
@pytest.mark.parametrize("bad", HOSTILE, ids=repr)
def test_human_record_hostile_field_never_500_never_false_verified(client, r, field, bad):
    good = {"status": "VERIFIED", "verified_by": "a@x.dev", "verified_at": "2026-10-12T12:00:00Z"}
    r.seed("pipeline:phase:ingest:human", json.dumps({**good, field: bad}))
    body = _assert_honest(client)
    human = body["phases"][0]["human"]
    breaks = field in ("status", "verified_at") or (field == "verified_by" and not (isinstance(bad, str) and bad))
    if breaks:
        assert human["status"] == "NOT_VERIFIED"
    else:
        assert human["status"] == "VERIFIED" and (human.get("note") in (None, bad) if field == "note" else True)


@pytest.mark.parametrize("raw", ["[]", "null", "42", "{", "[" * 100000])
def test_human_non_object_json_is_not_verified(client, r, raw):
    for p in ("ingest", "relay", "player"):
        r.seed(f"pipeline:phase:{p}:human", raw)
    body = _assert_honest(client)
    assert all(p["human"] == {"status": "NOT_VERIFIED"} for p in body["phases"])


@pytest.mark.parametrize("bad", HOSTILE, ids=repr)
def test_hostile_human_record_does_not_break_verification_actions(client, r, bad):
    r.seed("pipeline:phase:ingest:human", json.dumps(bad))
    h = S.auth("operator")
    url = "/admin/pipeline/phases/ingest/verification"
    assert client.post(url, headers=h, json={}).status_code == 201
    r.seed("pipeline:phase:ingest:human", json.dumps(bad))
    assert client.delete(url, headers=h).status_code in (200, 409)


# ── H5: observed_at de la fase = observación MÁS RECIENTE ─────────────────────

def test_phase_observed_at_is_the_most_recent_signal_observation_and_clocks_untouched():
    import pipeline_state as P
    t = S.T0
    obs = {sig: S.observation(sig, "PASS", t.replace(second=sec), "ok")
           for sig, sec in (("ingest.video", 10), ("ingest.audio", 9), ("ingest.data", 8))}
    persisted = {"v": 1, "signals": {}, "phases": {"ingest": {
        "status": "OK", "last_transition_at": "2026-10-12T11:00:00Z", "last_green_at": "2026-10-12T11:30:00Z"}}}
    snap_, new_state, events = P.build_snapshot(obs, {}, persisted, t.replace(second=30))
    tr = snap_["phases"][0]["transport"]
    assert tr["status"] == "OK"
    assert tr["observed_at"] == "2026-10-12T12:00:10Z"           # la MÁS RECIENTE (:10), no la más antigua (:08)
    assert tr["last_transition_at"] == "2026-10-12T11:00:00Z"    # sin cambio de estado: no se reescribe
    assert tr["last_green_at"] == "2026-10-12T12:00:30Z"         # instante de evaluación, no observed_at
    assert new_state["phases"]["ingest"]["last_transition_at"] == "2026-10-12T11:00:00Z"
    assert [e for e in events if e["phase"] == "ingest"] == []
