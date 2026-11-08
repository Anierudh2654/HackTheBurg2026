"""Temporary copy of Doc 00's three-valued predicate evaluator."""
from __future__ import annotations

from datetime import date
from typing import Any

OPS = ("eq", "ne", "in", "lt", "lte", "gt", "gte")


def validate(pred: dict[str, Any] | None, fact_keys: set[str]) -> None:
    if pred is None:
        return
    if not isinstance(pred, dict) or len(pred) == 0:
        raise ValueError("predicate must be a non-empty object")
    if "const" in pred:
        if len(pred) != 1 or not isinstance(pred["const"], bool):
            raise ValueError("const predicate must contain one boolean")
    elif "all" in pred or "any" in pred:
        op = "all" if "all" in pred else "any"
        if len(pred) != 1 or not isinstance(pred[op], list):
            raise ValueError(f"{op} predicate must contain a list")
        for child in pred[op]:
            validate(child, fact_keys)
    elif "not" in pred:
        if len(pred) != 1:
            raise ValueError("not predicate must contain one child")
        validate(pred["not"], fact_keys)
    elif "fact" in pred:
        operators = [op for op in OPS if op in pred]
        if len(pred) != 2 or len(operators) != 1:
            raise ValueError("fact predicate must contain exactly one comparison")
        if pred["fact"] not in fact_keys:
            raise ValueError(f"unknown fact key: {pred['fact']}")
        if operators[0] == "in" and not isinstance(pred["in"], list):
            raise ValueError("in target must be a list")
    else:
        raise ValueError(f"unsupported predicate: {pred}")


def _value(fact: Any) -> tuple[bool, Any]:
    if fact is None:
        return False, None
    if isinstance(fact, dict):
        return fact.get("status", "known") == "known", fact.get("value")
    status = getattr(fact, "status", "known")
    return status == "known", getattr(fact, "value", None)


def _cmp(op: str, value: Any, target: Any) -> bool:
    if op == "eq":
        return value == target
    if op == "ne":
        return value != target
    if op == "in":
        return value in target
    if value is None:
        return False
    left = date.fromisoformat(value) if isinstance(value, str) and _looks_date(value) else value
    right = date.fromisoformat(target) if isinstance(target, str) and _looks_date(target) else target
    return {"lt": left < right, "lte": left <= right, "gt": left > right, "gte": left >= right}[op]


def _looks_date(value: str) -> bool:
    return len(value) == 10 and value[4:5] == "-" and value[7:8] == "-"


def evaluate(pred: dict[str, Any] | None, facts: dict[str, Any], missing: set[str]) -> bool | None:
    if pred is None:
        return True
    if "const" in pred:
        return pred["const"]
    if "all" in pred:
        vals = [evaluate(p, facts, missing) for p in pred["all"]]
        return False if False in vals else None if None in vals else True
    if "any" in pred:
        vals = [evaluate(p, facts, missing) for p in pred["any"]]
        return True if True in vals else None if None in vals else False
    if "not" in pred:
        val = evaluate(pred["not"], facts, missing)
        return None if val is None else not val
    key = pred["fact"]
    known, value = _value(facts.get(key))
    if not known:
        missing.add(key)
        return None
    op = next(op for op in OPS if op in pred)
    try:
        return _cmp(op, value, pred[op])
    except (TypeError, ValueError):
        return False
