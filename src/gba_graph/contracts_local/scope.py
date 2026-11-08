"""Shared scope-frame applicability rules from Doc 00."""
from __future__ import annotations

from datetime import date
from typing import Any
from .predicates import evaluate


def applicability(frame: Any, facts: dict[str, Any], as_of: date) -> tuple[bool | None, list[str], str | None]:
    get = frame.get if isinstance(frame, dict) else lambda k, d=None: getattr(frame, k, d)
    missing: set[str] = set()
    valid_from = get("valid_from")
    valid_to = get("valid_to")
    if isinstance(valid_from, str):
        valid_from = date.fromisoformat(valid_from)
    if isinstance(valid_to, str):
        valid_to = date.fromisoformat(valid_to)
    clauses: list[tuple[str, bool | None]] = []
    clauses.append(("in_force", (valid_from is None or valid_from <= as_of)
                    and (valid_to is None or as_of < valid_to)))
    addressees = get("addressee_classes", []) or []
    if not addressees:
        addressee: bool | None = True
    else:
        presence: list[bool | None] = []
        for actor in addressees:
            key = {"controller": "controller_present", "control_group": "controller_present",
                   "interested_director": "interested_director_involved"}.get(actor)
            if key is None:
                presence.append(True)
            else:
                presence.append(evaluate({"fact": key, "eq": True}, facts, missing))
        addressee = True if True in presence else None if None in presence else False
    clauses.append(("addressee", addressee))
    types = get("transaction_types", []) or []
    clauses.append(("transaction_type", True if not types else evaluate({"fact": "transaction_type", "in": types}, facts, missing)))
    clauses.append(("applies_when", evaluate(get("applies_when"), facts, missing)))
    exceptions = get("exceptions", []) or []
    true_exception = None
    exception_vals = []
    for exception in exceptions:
        value = evaluate(exception.get("when"), facts, missing)
        exception_vals.append(value)
        if value is True and true_exception is None:
            true_exception = str(exception.get("exception_id", ""))
    clauses.append((f"exception:{true_exception}" if true_exception is not None else "exception", False if true_exception is not None else None if None in exception_vals else True))
    non_application = get("non_application")
    clauses.append(("non_application", True if non_application is None else _negate(evaluate(non_application, facts, missing))))
    failed = next((name for name, value in clauses if value is False), None)
    vals = [value for _, value in clauses]
    result = False if False in vals else None if None in vals else True
    ordered_missing = sorted(missing, key=lambda key: (key != "transaction_type", key))
    return result, ordered_missing, failed


def _negate(value: bool | None) -> bool | None:
    return None if value is None else not value
