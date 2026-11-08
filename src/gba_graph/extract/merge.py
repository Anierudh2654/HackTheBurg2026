"""Merge fact extractions across source documents."""
from __future__ import annotations

from ..contracts_local.models import MatterFact

TIME_VARYING = {"closing_date", "litigation_commenced_on"}


def merge_facts(items: list[MatterFact]) -> list[MatterFact]:
    grouped: dict[str, list[MatterFact]] = {}
    for item in items:
        grouped.setdefault(item.key, []).append(item)
    merged: list[MatterFact] = []
    for key, values in grouped.items():
        known = [value for value in values if value.status == "known"]
        if not known:
            merged.append(values[0].model_copy(update={"status": "unknown", "value": None}))
            continue
        distinct = {repr(value.value) for value in known}
        if len(distinct) == 1:
            best = max(known, key=lambda value: value.confidence or 0.0)
            spans = list({(span.doc_id, span.start, span.end): span for value in known for span in value.spans}.values())
            merged.append(best.model_copy(update={"spans": spans}))
        elif key in TIME_VARYING:
            latest = max(known, key=lambda value: value.reported_date or __import__("datetime").date.min)
            merged.append(latest)
        else:
            merged.append(values[0].model_copy(update={"status": "conflicting", "value": None,
                "spans": [span for value in known for span in value.spans]}))
    return sorted(merged, key=lambda fact: fact.key)
