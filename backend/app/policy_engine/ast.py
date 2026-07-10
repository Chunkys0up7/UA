"""Predicate AST evaluation (specs/07 §4.1–4.2, schemas/rule.schema.json).

Operand resolution order (deterministic, specs/07 §4.1):
1. Decimal-parsable string  -> Decimal literal ("45.000", "80.00")
2. Key in derived_inputs     -> derived value (file-scoped case mapping)
3. Key in evaluation context -> context value (records consumed input)
4. Contains "."              -> MISSING context path (never a silent pass)
5. Otherwise                 -> plain string literal ("TX", "purchase")

A table-lookup miss or missing context path raises MissingInput, which
the engine converts to outcome `refer` + RC-DATA-MISSING (T-POL-7,
specs/07 §4.2).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.policy_engine.result import RuleInput


class MissingInput(Exception):
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"missing context input: {path}")


class Evaluator:
    """Evaluates predicates against a context of {path: (value, lineage_ref)}."""

    def __init__(
        self,
        context: dict[str, tuple[Any, str | None]],
        tables: dict[str, dict] | None = None,
        derived_inputs: dict[str, dict] | None = None,
    ):
        self.context = context
        self.tables = tables or {}
        self.derived_specs = derived_inputs or {}
        self.consumed: dict[str, RuleInput] = {}

    # ------------------------------------------------------------ operands
    def resolve(self, operand: Any) -> Any:
        if isinstance(operand, bool) or isinstance(operand, (int,)):
            return operand
        if isinstance(operand, dict) and "table" in operand:
            return self._table_lookup(operand["table"])
        if isinstance(operand, str):
            try:
                return Decimal(operand)
            except InvalidOperation:
                pass
            if operand in self.derived_specs:
                return self._derived(operand)
            if operand in self.context:
                value, ref = self.context[operand]
                self.consumed[operand] = RuleInput(
                    path=operand, value=str(value), lineage_ref=ref
                )
                return value
            if "." in operand:
                raise MissingInput(operand)
            return operand  # plain string literal, e.g. "TX"
        if isinstance(operand, list):
            return [self.resolve(o) for o in operand]
        raise TypeError(f"unsupported operand: {operand!r}")

    def _derived(self, name: str) -> Any:
        spec = self.derived_specs[name]
        source = self.resolve(spec["map"])
        cases = spec["cases"]
        key = str(source).lower() if isinstance(source, bool) else str(source)
        if key not in cases:
            raise MissingInput(f"derived:{name}[{key}]")
        return cases[key]

    def _table_lookup(self, spec: dict) -> Any:
        table = self.tables.get(spec["from"])
        if table is None:
            raise MissingInput(f"table:{spec['from']}")
        resolved_match = {k: self.resolve(v) for k, v in spec["match"].items()}
        for row in table["rows"]:
            if all(self._eq(row.get(k), v) for k, v in resolved_match.items()):
                return self._coerce(row[spec["select"]])
        raise MissingInput(
            f"table:{spec['from']}[{','.join(f'{k}={v}' for k, v in resolved_match.items())}]"
        )

    @staticmethod
    def _coerce(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return Decimal(value)
            except InvalidOperation:
                return value
        return value

    @staticmethod
    def _eq(a: Any, b: Any) -> bool:
        na, nb = Evaluator._numeric(a), Evaluator._numeric(b)
        if na is not None and nb is not None:
            return na == nb
        return str(a) == str(b)

    @staticmethod
    def _numeric(value: Any) -> Decimal | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, Decimal)):
            return Decimal(value)
        if isinstance(value, str):
            try:
                return Decimal(value)
            except InvalidOperation:
                return None
        return None

    # ------------------------------------------------------------ predicates
    def evaluate(self, predicate: dict) -> bool:
        if len(predicate) != 1:
            raise ValueError(f"predicate must have exactly one operator: {predicate}")
        op, args = next(iter(predicate.items()))
        if op == "and":
            return all(self.evaluate(p) for p in args)
        if op == "or":
            # non-short-circuit would consume more inputs; short-circuit is
            # deterministic because rule JSON order is fixed
            return any(self.evaluate(p) for p in args)
        if op == "not":
            return not self.evaluate(args)
        if op == "absent":
            return args not in self.context
        if op == "present":
            if args in self.context:
                value, ref = self.context[args]
                self.consumed[args] = RuleInput(args, str(value), ref)
                return True
            return False
        if op == "in":
            left = self.resolve(args[0])
            members = [self._coerce(m) if isinstance(m, str) else m for m in args[1]]
            return any(self._eq(left, m) for m in members)
        if op in ("==", "!=", "<", "<=", ">", ">="):
            left, right = self.resolve(args[0]), self.resolve(args[1])
            return self._compare(op, left, right)
        raise ValueError(f"unknown operator: {op}")

    @staticmethod
    def _compare(op: str, left: Any, right: Any) -> bool:
        nl, nr = Evaluator._numeric(left), Evaluator._numeric(right)
        if nl is not None and nr is not None:
            left, right = nl, nr
        elif op in ("<", "<=", ">", ">="):
            raise TypeError(f"ordering comparison on non-numeric: {left!r} {op} {right!r}")
        if op == "==":
            return Evaluator._eq(left, right)
        if op == "!=":
            return not Evaluator._eq(left, right)
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        return left >= right


__all__ = ["Evaluator", "MissingInput"]
