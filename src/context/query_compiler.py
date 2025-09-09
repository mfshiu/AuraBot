from __future__ import annotations
from typing import Any, Dict, List, Tuple, Union

from . import (
    Query, Node, Rel, Expr, Param, Const, Property,
    Compare, And, Or, Not
)

class QueryCompiler:
    def __init__(self) -> None:
        pass

    def to_cypher(self, q: Query) -> Tuple[str, Dict[str, Any]]:
        parts: List[str] = []
        params: Dict[str, Any] = {}

        if q.match:
            pattern_chunks = [self._pattern(m) for m in q.match]
            parts.append("MATCH " + ", ".join(pattern_chunks))

        if q.where is not None:
            where_str, where_params = self._expr(q.where)
            parts.append("WHERE " + where_str)
            params.update(where_params)

        if q.returns:
            ret_chunks: List[str] = []
            for r in q.returns:
                s, p = self._expr(r.expr)
                ret_chunks.append(f"{s} AS {r.alias}" if r.alias else s)
                params.update(p)
            parts.append("RETURN " + ", ".join(ret_chunks))
        else:
            parts.append("RETURN *")

        if q.order_by:
            ord_chunks: List[str] = []
            for o in q.order_by:
                s, p = self._expr(o.expr)
                params.update(p)
                ord_chunks.append(f"{s} {o.direction}")
            parts.append("ORDER BY " + ", ".join(ord_chunks))

        if q.skip is not None:
            parts.append("SKIP $__skip"); params["__skip"] = q.skip
        if q.limit is not None:
            parts.append("LIMIT $__limit"); params["__limit"] = q.limit

        return "\n".join(parts), params

    def _pattern(self, m: Union[Node, Rel]) -> str:
        if isinstance(m, Node): return m.pattern()
        if isinstance(m, Rel):  return m.pattern()
        raise TypeError(f"Unsupported match element: {type(m)}")

    def _expr(self, e: Expr) -> Tuple[str, Dict[str, Any]]:
        if isinstance(e, Param):    return f"${e.name}", {}
        if isinstance(e, Const):
            key = f"__const_{id(e)}"; return f"${key}", {key: e.value}
        if isinstance(e, Property): return f"{e.var}.{e.key}", {}
        if isinstance(e, Compare):
            ls, lp = self._expr(e.left); rs, rp = self._expr(e.right)
            lp.update(rp); return f"{ls} {e.op} {rs}", lp
        if isinstance(e, And):
            chunks, p = [], {}
            for sub in e.exprs:
                s, sp = self._expr(sub); chunks.append(f"({s})"); p.update(sp)
            return " AND ".join(chunks), p
        if isinstance(e, Or):
            chunks, p = [], {}
            for sub in e.exprs:
                s, sp = self._expr(sub); chunks.append(f"({s})"); p.update(sp)
            return " OR ".join(chunks), p
        if isinstance(e, Not):
            s, p = self._expr(e.expr); return f"NOT ({s})", p
        raise TypeError(f"Unsupported expr: {type(e)}")
