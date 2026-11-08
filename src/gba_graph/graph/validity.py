"""Rule in-force and treatment calculation."""
from datetime import date
from ..contracts_local.models import Edge, Node, TreatmentEvent, ValidityResult


TREATMENTS = {"overrules": "overruled", "superseded_by_statute": "superseded", "limits": "limited"}
PRIORITY = {"overruled": 3, "superseded": 2, "limited": 1, "good": 0}


def validity(node: Node, edges: list[Edge], as_of: date) -> ValidityResult:
    if node.props.get("validity_unknown") is True:
        in_force = "unknown"
    else:
        in_force = "true" if ((node.valid_from is None or node.valid_from <= as_of)
                               and (node.valid_to is None or as_of < node.valid_to)) else "false"
    treatments: list[TreatmentEvent] = []
    for edge in edges:
        if edge.dst != node.node_id or edge.edge_type not in TREATMENTS:
            continue
        effective = edge.valid_from or edge.known_from
        if effective <= as_of:
            treatments.append(TreatmentEvent(edge=edge, effective_date=effective, by_node_id=edge.src))
    if in_force == "unknown":
        status = "unknown"
    elif treatments:
        labels = [TREATMENTS[t.edge.edge_type] for t in treatments]
        status = max(labels, key=lambda x: PRIORITY[x])
    else:
        status = "good"
    reasons = [f"in_force={in_force} as of {as_of.isoformat()}"]
    reasons.extend(f"{TREATMENTS[t.edge.edge_type]} by {t.by_node_id} effective {t.effective_date}" for t in treatments)
    return ValidityResult(node_id=node.node_id, as_of=as_of, in_force=in_force,
                          good_law_unconditional=status, treatments=treatments, reasons=reasons)
