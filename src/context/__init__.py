# AST 定義（中立，不綁 Neo4j）
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

Label = str
Var = str
Prop = Tuple[Var, str]
OrderDir = Literal["ASC", "DESC"]

@dataclass
class Node:
    var: Var
    labels: Sequence[Label] = field(default_factory=tuple)
    def pattern(self) -> str:
        lbl = ":" + ":".join(self.labels) if self.labels else ""
        return f"({self.var}{lbl})"

@dataclass
class Rel:
    from_: Var
    type: Optional[str]
    to: Var
    directed: bool = True
    def pattern(self) -> str:
        t = f":{self.type}" if self.type else ""
        return f"({self.from_})-[{t}]->({self.to})" if self.directed else f"({self.from_})-[{t}]-({self.to})"

# ---- Where Expr ----
class Expr: ...
@dataclass
class Param(Expr): name: str
@dataclass
class Const(Expr): value: Any
@dataclass
class Property(Expr): var: Var; key: str
@dataclass
class Compare(Expr): op: Literal["=","<",">","<=",">=","<>"]; left: Expr; right: Expr
@dataclass
class And(Expr): exprs: Sequence[Expr]
@dataclass
class Or(Expr): exprs: Sequence[Expr]
@dataclass
class Not(Expr): expr: Expr

# ---- Return/Order/Query ----
@dataclass
class RetItem: expr: Expr; alias: Optional[str] = None
@dataclass
class OrderItem: expr: Expr; direction: OrderDir = "ASC"

@dataclass
class Query:
    match: Sequence[Union[Node, Rel]]
    where: Optional[Expr] = None
    returns: Sequence[RetItem] = field(default_factory=list)
    order_by: Sequence[OrderItem] = field(default_factory=list)
    skip: Optional[int] = None
    limit: Optional[int] = None

__all__ = [
    "Node","Rel","Expr","Param","Const","Property","Compare","And","Or","Not",
    "RetItem","OrderItem","Query",
]
