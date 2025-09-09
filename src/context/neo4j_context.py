from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from . import Query  # 型別註記用
from .query_compiler import QueryCompiler
from typing import TYPE_CHECKING

try:
    from neo4j import GraphDatabase, Driver
except Exception:  # pragma: no cover
    GraphDatabase = None  # type: ignore


if TYPE_CHECKING:
    from neo4j import Driver as Neo4jDriver
else:
    Neo4jDriver = Any  # 避免未安裝時型別錯誤
    
    
class Neo4jContext:
    
    def __init__(self, uri: str, auth: Tuple[str, str], database: Optional[str] = None):
        if GraphDatabase is None:
            raise RuntimeError("neo4j driver not installed. pip install neo4j")
        self._driver: Neo4jDriver = GraphDatabase.driver(uri, auth=auth)
        self._database = database
        self._compiler = QueryCompiler()


    def close(self) -> None:
        self._driver.close()

    def run(self, query: Query, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        cypher, extra = self._compiler.to_cypher(query)
        merged = {**(params or {}), **extra}
        return self._execute(cypher, merged)

    def execute_cypher(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._execute(cypher, params or {})

    def _execute(self, cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        def work(tx):
            result = tx.run(cypher, **params)
            return [r.data() for r in result]
        if self._database:
            with self._driver.session(database=self._database) as s:
                return s.execute_read(work)
        else:
            with self._driver.session() as s:
                return s.execute_read(work)
