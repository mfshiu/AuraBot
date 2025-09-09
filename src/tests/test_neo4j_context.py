from typing import Any, Dict, Optional, List

import context.neo4j_context as neo4j_mod
from context.neo4j_context import Neo4jContext
from context import (
    Query, Node, Rel, And, Compare, Property, Param,
    RetItem, OrderItem,
)

# ---------- Fake neo4j driver (typed) ----------
class _FakeRecord:
    def __init__(self, d: Dict[str, Any]) -> None: self._d = d
    def data(self) -> Dict[str, Any]: return self._d

class _FakeResult:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = [_FakeRecord(r) for r in rows]
    def __iter__(self): return iter(self._rows)

class _Tx:
    last_query: str
    last_params: Dict[str, Any]
    def __init__(self) -> None:
        self.last_query = ""
        self.last_params = {}
    def run(self, cypher: str, **params: Any) -> _FakeResult:
        self.last_query = cypher
        self.last_params = dict(params)
        return _FakeResult([{"ok": True, "echo": self.last_params}])

class _Session:
    def __init__(self, tx: _Tx) -> None: self._tx = tx
    def __enter__(self) -> "_Session": return self
    def __exit__(self, exc_type, exc, tb) -> bool: return False
    def execute_read(self, work): return work(self._tx)

class _Driver:
    tx: _Tx
    last_database: Optional[str]
    def __init__(self) -> None:
        self.tx = _Tx()
        self.last_database = None
    def session(self, database: Optional[str] = None) -> _Session:
        self.last_database = database
        return _Session(self.tx)
    def close(self) -> None: ...

class _DummyGraphDB:
    last_driver: Optional[_Driver] = None
    @staticmethod
    def driver(uri: str, auth: tuple[str, str]) -> _Driver:
        _DummyGraphDB.last_driver = _Driver()
        return _DummyGraphDB.last_driver

def _patch_graphdb(monkeypatch):
    monkeypatch.setattr(neo4j_mod, "GraphDatabase", _DummyGraphDB, raising=True)

# ---------- Query fixture ----------
def _sample_query() -> Query:
    return Query(
        match=[
            Node(var="p", labels=["Person"]),
            Rel(from_="p", type="WORKS_AT", to="c", directed=True),
            Node(var="c", labels=["Company"]),
        ],
        where=And([
            Compare("=", Property("c", "name"), Param("company")),
            Compare(">", Property("p", "hiredAt"), Param("hiredAfter")),
        ]),
        returns=[RetItem(Property("p", "name"), alias="name"),
                 RetItem(Property("p", "email"))],
        order_by=[OrderItem(Property("p", "name"), "ASC")],
        skip=0, limit=20,
    )

# ---------- Tests ----------
def test_run_compiles_and_executes(monkeypatch):
    _patch_graphdb(monkeypatch)
    ctx = Neo4jContext("bolt://x", ("neo4j", "pass"))
    q = _sample_query()
    rows = ctx.run(q, {"company": "TSMC", "hiredAfter": "2021-01-01"})
    drv = _DummyGraphDB.last_driver
    assert isinstance(rows, list) and rows[0]["ok"] is True
    assert isinstance(drv, _Driver)

    cy = drv.tx.last_query
    assert "MATCH (p:Person)" in cy and "[:WORKS_AT]->(c)" in cy and "(c:Company)" in cy
    assert "WHERE" in cy and "ORDER BY p.name ASC" in cy
    assert "SKIP $__skip" in cy and "LIMIT $__limit" in cy

    ps = drv.tx.last_params
    assert ps["company"] == "TSMC" and ps["hiredAfter"] == "2021-01-01"
    assert ps["__skip"] == 0 and ps["__limit"] == 20

def test_execute_cypher_escape_hatch(monkeypatch):
    _patch_graphdb(monkeypatch)
    ctx = Neo4jContext("bolt://x", ("neo4j", "pass"))
    _ = ctx.execute_cypher("RETURN $x AS x", {"x": 7})
    tx = _DummyGraphDB.last_driver.tx  # type: ignore[union-attr]
    assert tx.last_query == "RETURN $x AS x"
    assert tx.last_params == {"x": 7}

def test_constructor_raises_when_driver_missing(monkeypatch):
    monkeypatch.setattr(neo4j_mod, "GraphDatabase", None, raising=True)
    import pytest
    with pytest.raises(RuntimeError):
        Neo4jContext("bolt://x", ("neo4j", "pass"))

def test_database_argument_passed(monkeypatch):
    _patch_graphdb(monkeypatch)
    ctx = Neo4jContext("bolt://x", ("neo4j", "pass"), database="neo4j")
    _ = ctx.run(_sample_query(), {"company": "TSMC", "hiredAfter": "2021-01-01"})
    assert _DummyGraphDB.last_driver and _DummyGraphDB.last_driver.last_database == "neo4j"
