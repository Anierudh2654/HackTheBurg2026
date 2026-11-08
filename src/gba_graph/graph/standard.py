"""Deterministic standard-of-review engine."""
from __future__ import annotations

from datetime import date
from typing import Any
from ..contracts_local.models import ConditionStatus, Node, StandardOfReview, StandardResp
from ..contracts_local.predicates import evaluate
from ..contracts_local.scope import applicability
from .store import GraphStore


def _needed(pred: Any, facts: dict[str, Any]) -> list[str]:
    if pred is None:
        return []
    missing: set[str] = set()
    evaluate(pred, facts, missing)
    return sorted(missing)


def _conditions(store: GraphStore, rules: list[Node], facts: dict[str, Any], as_of: date,
                leakage_mode: str) -> list[ConditionStatus]:
    visible_edges = store.visible_edges(as_of, leakage_mode)
    element_ids: set[str] = set()
    for rule in rules:
        for edge in visible_edges:
            if edge.src != rule.node_id:
                continue
            if edge.edge_type == "addresses" and edge.dst.startswith("Element:"):
                element_ids.add(edge.dst)
        for edge in visible_edges:
            if edge.dst != rule.node_id:
                continue
            if edge.edge_type == "satisfies" and edge.src.startswith("ProcessFact:"):
                element_ids.add(edge.dst)
    result: list[ConditionStatus] = []
    for node_id in sorted(element_ids):
        node = store.nodes.get(node_id)
        if node is None or not (leakage_mode == "off" or node.known_from <= as_of):
            continue
        met = evaluate(node.props.get("met_when"), facts, set())
        keys = list(node.props.get("fact_keys", []))
        if met is True:
            status = "met"
        else:
            unmet_pred = node.props.get("unmet_when")
            if unmet_pred is None and all(_fact_known(facts.get(key)) for key in keys):
                unmet = met is False
            else:
                unmet = evaluate(unmet_pred, facts, set()) if unmet_pred is not None else False
            status = "unmet" if unmet is True else "unknown"
        result.append(ConditionStatus(condition_id=node_id, label=node.label, status=status,
                                      fact_keys=keys, spans=[], reason=f"Condition is {status} based on supplied matter facts."))
    return result


def _fact_known(value: Any) -> bool:
    if value is None:
        return False
    return value.get("status") == "known" if isinstance(value, dict) else getattr(value, "status", None) == "known"


def standard_of_review(store: GraphStore, as_of: date, facts: dict[str, Any], leakage_mode: str = "strict") -> StandardResp:
    visible = {n.node_id: n for n in store.visible_nodes(as_of, leakage_mode)}
    rules: list[tuple[Node, str, bool | None, list[str], str | None]] = []
    for node in visible.values():
        prop = "safe_harbor_when" if node.node_type == "Provision" else "bjr_when" if node.node_type == "Holding" else None
        if prop is None or prop not in node.props or node.scope_frame is None:
            continue
        tri, missing, failed = applicability(node.scope_frame, facts, as_of)
        rules.append((node, prop, tri, missing, failed))
    statutes = [r for r in rules if r[0].node_type == "Provision"]
    holdings = _dedupe_holdings([r for r in rules if r[0].node_type == "Holding"])
    all_visible_edges = store.visible_edges(as_of, leakage_mode)
    displaced: set[str] = set()
    for provision in [n for n, _, tri, _, _ in statutes if tri is True]:
        for edge in all_visible_edges:
            if edge.src == provision.node_id and edge.edge_type in {"overrules", "superseded_by_statute"} and edge.dst in visible:
                if evaluate(edge.condition, facts, set()) is True:
                    displaced.add(edge.dst)
    holdings = [r for r in holdings if r[0].node_id not in displaced]

    applicable_statutes = [r for r in statutes if r[2] is True]
    unknown_statutes = [r for r in statutes if r[2] is None]
    examined: list[tuple[Node, str, bool | None, list[str], str | None]]
    readings: list[dict[str, Any]] = []
    if applicable_statutes:
        examined = applicable_statutes
        hvalues: list[bool | None] = []
        for node, prop, *_ in examined:
            hvalues.append(evaluate(node.props[prop], facts, set()))
        result = _combine_outcomes(hvalues, [r[0].node_id for r in examined], facts, examined)
    elif unknown_statutes:
        examined = unknown_statutes + [r for r in holdings if r[2] is not False]
        readings = _readings(examined, facts)
        result = StandardOfReview(value="unknown", safe_harbor="unknown", basis=[r[0].node_id for r in examined], readings=readings)
    else:
        relevant_holdings = [r for r in holdings if r[2] is not False]
        examined = relevant_holdings
        if any(r[2] is None for r in relevant_holdings):
            readings = _readings(relevant_holdings, facts)
            result = StandardOfReview(value="unknown", safe_harbor="unknown", basis=[r[0].node_id for r in relevant_holdings], readings=readings)
        elif relevant_holdings:
            values = [evaluate(node.props[prop], facts, set()) for node, prop, *_ in relevant_holdings]
            result = _combine_outcomes(values, [r[0].node_id for r in relevant_holdings], facts, relevant_holdings)
        else:
            examined = []
            result = StandardOfReview(value="unknown", safe_harbor="unknown", basis=[], readings=[])
    used = [r[0] for r in examined]
    conditions = _conditions(store, used, facts, as_of, leakage_mode)
    return StandardResp(standard=result, conditions=conditions)


def _combine_outcomes(values: list[bool | None], basis: list[str], facts: dict[str, Any], rules) -> StandardOfReview:
    if not values:
        return StandardOfReview(value="unknown", safe_harbor="unknown", basis=basis, readings=[])
    combined = True if True in values else None if None in values else False
    tri = "unknown" if combined is None else "true" if combined else "false"
    standard = "business_judgment" if combined is True else "entire_fairness" if combined is False else "unknown"
    readings = _readings(rules, facts) if combined is None else []
    return StandardOfReview(value=standard, safe_harbor=tri, basis=basis, readings=readings)


def _readings(rules, facts: dict[str, Any]) -> list[dict[str, Any]]:
    readings = []
    for node, prop, tri, applicability_missing, _ in rules:
        if tri is False:
            continue
        outcome_missing = _needed(node.props.get(prop), facts)
        if node.node_type == "Holding":
            would = "business_judgment" if evaluate(node.props[prop], facts, set()) is True else "entire_fairness" if evaluate(node.props[prop], facts, set()) is False else "depends"
        else:
            pred_value = evaluate(node.props[prop], facts, set())
            would = "business_judgment" if pred_value is True else "entire_fairness" if pred_value is False else "depends"
        readings.append({"regime": node.node_id, "applies_if": sorted(applicability_missing),
                         "requires": outcome_missing, "would_yield": would})
    return readings


def _dedupe_holdings(rules):
    """Collapse duplicate MFW rule statements to the latest applicable holding."""
    groups: dict[str, list] = {}
    for rule in rules:
        node, prop = rule[0], rule[1]
        frame_key = None
        if node.scope_frame:
            frame_key = (node.scope_frame.addressee_classes, node.scope_frame.transaction_types,
                         node.scope_frame.applies_when, node.scope_frame.non_application,
                         [(item.exception_id, item.when) for item in node.scope_frame.exceptions],
                         node.scope_frame.jurisdiction)
        key = repr((frame_key, node.props.get(prop)))
        groups.setdefault(key, []).append(rule)
    result = []
    for group in groups.values():
        result.append(max(group, key=lambda rule: (rule[0].valid_from or date.min, rule[0].node_id)))
    return result
