"""
Fake de Redis en memoria para los tests de Pipeline (#214).

`fakeredis` NO está instalado en este entorno, así que se implementa solo lo que
usan pipeline_api / pipeline_ingest: get, mget, set(nx, ex), delete, lpush, ltrim,
lrange, llen, ping y pipeline(transaction). Admite inyección de fallos
(`fail_after`, `fail_ops`) para simular un Redis que cae a mitad de operación.

Los tests de este fichero comprueban el propio fake (si el fake mintiera, todo lo
demás sería ruido).
"""
from __future__ import annotations

import pytest
import redis.exceptions as rexc


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.ops: list[str] = []
        self.fail_ops: set[str] = set()      # nombres de operación que siempre fallan
        self.fail_after: int | None = None   # nº de operaciones OK antes de caer
        self.down = False

    # ── inyección de fallos ───────────────────────────────────────────────
    def _enter(self, op: str) -> None:
        if self.down or op in self.fail_ops:
            raise rexc.ConnectionError(f"fake redis down ({op})")
        if self.fail_after is not None:
            if self.fail_after <= 0:
                raise rexc.ConnectionError(f"fake redis died ({op})")
            self.fail_after -= 1
        self.ops.append(op)

    # ── comandos ──────────────────────────────────────────────────────────
    def ping(self):
        self._enter("ping")
        return True

    def get(self, key):
        self._enter("get")
        return self.kv.get(key)

    def mget(self, keys):
        self._enter("mget")
        return [self.kv.get(k) for k in keys]

    def set(self, key, value, nx=False, ex=None):
        self._enter("set")
        return self._do_set(key, value, nx)

    def _do_set(self, key, value, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = value if isinstance(value, str) else str(value)
        return True

    def delete(self, *keys):
        self._enter("delete")
        return self._do_delete(*keys)

    def _do_delete(self, *keys):
        n = 0
        for k in keys:
            if self.kv.pop(k, None) is not None:
                n += 1
            if self.lists.pop(k, None) is not None:
                n += 1
        return n

    def lpush(self, key, *values):
        self._enter("lpush")
        return self._do_lpush(key, *values)

    def _do_lpush(self, key, *values):
        lst = self.lists.setdefault(key, [])
        for v in values:
            lst.insert(0, v if isinstance(v, str) else str(v))
        return len(lst)

    def ltrim(self, key, start, stop):
        self._enter("ltrim")
        return self._do_ltrim(key, start, stop)

    def _do_ltrim(self, key, start, stop):
        lst = self.lists.get(key, [])
        self.lists[key] = lst[start:stop + 1] if stop >= 0 else lst[start:]
        return True

    def lrange(self, key, start, stop):
        self._enter("lrange")
        lst = self.lists.get(key, [])
        return list(lst[start:stop + 1] if stop >= 0 else lst[start:])

    def llen(self, key):
        self._enter("llen")
        return len(self.lists.get(key, []))

    def pipeline(self, transaction=True):
        return _FakePipeline(self)

    # ── helper de test ────────────────────────────────────────────────────
    def seed(self, key, value):
        """Escribe sin pasar por la inyección de fallos."""
        self.kv[key] = value


class _FakePipeline:
    """MULTI/EXEC simplificado: todo o nada respecto a la inyección de fallos."""

    def __init__(self, r: FakeRedis) -> None:
        self.r = r
        self.queue: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        if name in ("set", "lpush", "ltrim", "delete"):
            def _q(*a, **kw):
                self.queue.append((name, a, kw))
                return self
            return _q
        raise AttributeError(name)

    def execute(self):
        # Pre-comprobación: si algún comando fallaría, no se aplica ninguno (atómico).
        if self.r.down or any(op in self.r.fail_ops for op, _, _ in self.queue):
            raise rexc.ConnectionError("fake redis down (execute)")
        if self.r.fail_after is not None and self.r.fail_after < 1:
            raise rexc.ConnectionError("fake redis died (execute)")
        if self.r.fail_after is not None:
            self.r.fail_after -= 1
        return [getattr(self.r, "_do_" + op)(*a, **{k: v for k, v in kw.items() if k != "ex"})
                for op, a, kw in self.queue]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ── Tests del fake ────────────────────────────────────────────────────────────

def test_fake_set_get_nx():
    r = FakeRedis()
    assert r.set("k", "v", nx=True) is True
    assert r.set("k", "w", nx=True) is None
    assert r.get("k") == "v"


def test_fake_list_semantics_newest_first_and_trim():
    r = FakeRedis()
    for i in range(5):
        r.lpush("l", str(i))
    assert r.lrange("l", 0, 1) == ["4", "3"]
    r.ltrim("l", 0, 2)
    assert r.lrange("l", 0, 999) == ["4", "3", "2"]


def test_fake_failure_injection():
    r = FakeRedis()
    r.fail_after = 1
    r.get("a")
    with pytest.raises(rexc.ConnectionError):
        r.get("a")
    r2 = FakeRedis()
    r2.fail_ops = {"lpush"}
    r2.get("x")
    with pytest.raises(rexc.ConnectionError):
        r2.lpush("l", "v")


def test_fake_pipeline_is_all_or_nothing():
    r = FakeRedis()
    r.fail_ops = {"lpush"}
    p = r.pipeline()
    p.set("a", "1").lpush("l", "x")
    with pytest.raises(rexc.ConnectionError):
        p.execute()
    assert r.kv == {} and r.lists == {}
