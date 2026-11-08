"""Load deterministic illustrative seed graph. All legal content is unaudited."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
import yaml
from ..contracts_local.models import Edge, Node, ScopeFrame
from ..contracts_local.predicates import validate
from .store import GraphStore, edge_id

FACT_KEYS = {
    "transaction_type", "controller_present", "controller_identity", "signing_date", "announcement_date",
    "closing_date", "litigation_commenced_on", "interested_director_involved", "special_committee_formed",
    "committee_all_disinterested", "committee_power_to_say_no", "committee_power_to_negotiate",
    "committee_free_to_select_advisors", "committee_duty_of_care_met", "committee_formed_before_substantive_negotiation",
    "committee_approval_obtained", "mom_condition_in_agreement", "mom_vote_informed", "mom_vote_uncoerced",
    "mom_approval_obtained", "disinterested_stockholder_approval_obtained", "disinterested_director_approval_obtained",
    "deal_value_usd",
}
D = date.fromisoformat


def fact(key: str, value: Any = True) -> dict[str, Any]:
    return {"fact": key, "eq": value}


def all_of(*preds: dict[str, Any]) -> dict[str, Any]:
    return {"all": list(preds)}


def any_of(*preds: dict[str, Any]) -> dict[str, Any]:
    return {"any": list(preds)}


P_COMM = all_of(fact("committee_all_disinterested"), fact("committee_power_to_say_no"),
                fact("committee_power_to_negotiate"), fact("committee_approval_obtained"))
P_COMM_MFW = all_of(P_COMM, fact("committee_formed_before_substantive_negotiation"),
                    fact("committee_free_to_select_advisors"), fact("committee_duty_of_care_met"))
P_STOCK = any_of(fact("disinterested_stockholder_approval_obtained"), fact("mom_approval_obtained"))


def _frame(start: str, types: list[str] | None = None, *, addressees: list[str] | None = None,
           non_application: dict[str, Any] | None = None) -> ScopeFrame:
    return ScopeFrame(valid_from=D(start), transaction_types=types or [], addressee_classes=addressees or [],
                      non_application=non_application, audited=False)


def _node(node_id: str, kind: str, label: str, known: str, *, props=None, frame=None,
          valid_from=None, valid_to=None) -> Node:
    return Node(node_id=node_id, node_type=kind, label=label, props=props or {}, scope_frame=frame,
                valid_from=D(valid_from) if valid_from else None, valid_to=D(valid_to) if valid_to else None,
                known_from=D(known), source_ids=[], origin="seed", audited=False)


def _add_edge(store: GraphStore, src: str, dst: str, kind: str, known: str,
              *, valid_from=None, condition=None) -> None:
    validate(condition, FACT_KEYS)
    edge = Edge(edge_id=edge_id(src, dst, kind), src=src, dst=dst, edge_type=kind,
                known_from=D(known), valid_from=D(valid_from) if valid_from else None,
                condition=condition, origin="seed", audited=False)
    store.add_edge(edge)


def load_seed(store: GraphStore) -> GraphStore:
    node_files = sorted(Path("seed/nodes").glob("*.yaml"))
    edge_files = sorted(Path("seed/edges").glob("*.yaml"))
    if node_files and edge_files:
        for path in node_files:
            records = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            for record in records:
                node = Node.model_validate(record)
                _validate_node_predicates(node)
                store.add_node(node)
        for path in edge_files:
            records = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            for record in records:
                edge = Edge.model_validate(record)
                validate(edge.condition, FACT_KEYS)
                store.add_edge(edge)
        return store
    litigation_not_pre = {"not": {"fact": "litigation_commenced_on", "lte": "2025-02-17"}}
    common = _frame("2025-03-25", addressees=["controller"], non_application={"fact": "litigation_commenced_on", "lte": "2025-02-17"})
    provision_b = "Provision:de.dgcl.144b@2025-03-25"
    provision_c = "Provision:de.dgcl.144c@2025-03-25"
    mfw = "Holding:mfw-2014"
    match = "Holding:match-group-2024"
    nodes = [
        _node(provision_b, "Provision", "DGCL § 144(b), post-amendment", "2025-03-25",
              props={"code": "DGCL", "section": "144(b)", "version_label": "effective 2025-03-25", "safe_harbor_when": any_of(P_COMM, P_STOCK)},
              frame=_frame("2025-03-25", ["other_controller_deal"], addressees=["controller"], non_application=common.non_application), valid_from="2025-03-25"),
        _node(provision_c, "Provision", "DGCL § 144(c), post-amendment", "2025-03-25",
              props={"code": "DGCL", "section": "144(c)", "version_label": "effective 2025-03-25", "safe_harbor_when": all_of(P_COMM, P_STOCK)},
              frame=_frame("2025-03-25", ["going_private"], addressees=["controller"], non_application=common.non_application), valid_from="2025-03-25"),
        _node("Provision:de.dgcl.144@2024-12-01", "Provision", "DGCL § 144, pre-amendment (illustrative)", "2024-12-01",
              props={"code": "DGCL", "section": "144", "version_label": "pre-amendment"},
              frame=_frame("1967-03-01", ["interested_director"], addressees=["interested_director"]), valid_from="1967-03-01", valid_to="2025-03-25"),
        _node("Case:in-re-mfw-shareholders-litigation-2014", "Case", "In re MFW Shareholders Litigation", "2014-06-24",
              props={"case_name": "In re MFW Shareholders Litigation", "decided_on": "2014-06-24", "court_id": "Court:delaware-supreme-court", "citation_string": "67 A.3d 496"}, valid_from="2014-06-24"),
        _node("Case:in-re-match-group-2024", "Case", "In re Match Group, Inc. Derivative Litigation", "2024-04-04",
              props={"case_name": "In re Match Group, Inc. Derivative Litigation", "decided_on": "2024-04-04", "court_id": "Court:delaware-supreme-court", "citation_string": "315 A.3d 446"}, valid_from="2024-04-04"),
        _node(mfw, "Holding", "MFW dual-protection framework (illustrative)", "2014-06-24",
              props={"case_node_id": "Case:in-re-mfw-shareholders-litigation-2014", "proposition": "Business-judgment review when both protections are in place from the outset.", "bjr_when": all_of(P_COMM_MFW, fact("mom_condition_in_agreement"), fact("mom_vote_informed"), fact("mom_vote_uncoerced"), fact("mom_approval_obtained"))},
              frame=_frame("2014-06-24", ["going_private", "other_controller_deal"], addressees=["controller"]), valid_from="2014-06-24"),
        _node(match, "Holding", "Match Group dual protections (illustrative)", "2024-04-04",
              props={"case_node_id": "Case:in-re-match-group-2024", "proposition": "Both protections must be effective for business-judgment review under the holding.", "bjr_when": all_of(P_COMM_MFW, fact("mom_condition_in_agreement"), fact("mom_vote_informed"), fact("mom_vote_uncoerced"), fact("mom_approval_obtained"))},
              frame=_frame("2024-04-04", ["going_private", "other_controller_deal"], addressees=["controller"]), valid_from="2024-04-04"),
    ]
    element_specs = [
        ("committee-approval", "Committee approval", ["committee_approval_obtained"], fact("committee_approval_obtained")),
        ("mom-approval", "Majority-of-the-minority approval", ["mom_approval_obtained"], fact("mom_approval_obtained")),
        ("committee-independence", "Committee independence", ["committee_all_disinterested"], fact("committee_all_disinterested")),
        ("committee-power-to-say-no", "Committee power to say no", ["committee_power_to_say_no"], fact("committee_power_to_say_no")),
        ("committee-power-to-negotiate", "Committee power to negotiate", ["committee_power_to_negotiate"], fact("committee_power_to_negotiate")),
        ("committee-free-to-select-advisors", "Committee free to select advisors", ["committee_free_to_select_advisors"], fact("committee_free_to_select_advisors")),
        ("committee-duty-of-care", "Committee duty of care", ["committee_duty_of_care_met"], fact("committee_duty_of_care_met")),
        ("committee-ab-initio", "Committee formed before substantive negotiation", ["committee_formed_before_substantive_negotiation"], fact("committee_formed_before_substantive_negotiation")),
        ("mom-informed", "Informed stockholder vote", ["mom_vote_informed"], fact("mom_vote_informed")),
        ("mom-uncoerced", "Uncoerced stockholder vote", ["mom_vote_uncoerced"], fact("mom_vote_uncoerced")),
        ("disinterested-stockholder-approval", "Disinterested stockholder approval", ["disinterested_stockholder_approval_obtained"], fact("disinterested_stockholder_approval_obtained")),
    ]
    for slug, label, keys, met in element_specs:
        elements = _node(f"Element:{slug}", "Element", label, "2014-01-01",
                         props={"fact_keys": keys, "met_when": met})
        nodes.append(elements)
        for key in keys:
            nodes.append(_node(f"ProcessFact:{key}", "ProcessFact", key, "2014-01-01", props={"fact_key": key}))
    nodes += [
        _node("Standard:business-judgment", "Standard", "Business judgment", "1900-01-01", props={"value": "business_judgment"}),
        _node("Standard:entire-fairness", "Standard", "Entire fairness", "1900-01-01", props={"value": "entire_fairness"}),
        _node("Court:delaware-supreme-court", "Court", "Supreme Court of Delaware", "1776-01-01", props={"jurisdiction": "US-DE"}),
        _node("Court:delaware-court-of-chancery", "Court", "Delaware Court of Chancery", "1776-01-01", props={"jurisdiction": "US-DE"}),
    ]
    for entry_id, label in [("sec_edgar", "SEC EDGAR"), ("de_code_online", "Delaware Code Online"),
                            ("de_legislature", "Delaware General Assembly"), ("de_courts", "Delaware Courts"),
                            ("courtlistener", "CourtListener")]:
        nodes.append(_node(f"Source:{entry_id}", "Source", label, "2026-11-07", props={"registry_entry_id": entry_id}))
    for node in nodes:
        _validate_node_predicates(node)
        store.add_node(node)
    _add_edge(store, "Provision:de.dgcl.144@2024-12-01", provision_b, "next_version", "2025-03-25", valid_from="2025-03-25")
    _add_edge(store, "Provision:de.dgcl.144@2024-12-01", provision_c, "next_version", "2025-03-25", valid_from="2025-03-25")
    _add_edge(store, "Case:in-re-mfw-shareholders-litigation-2014", "Court:delaware-supreme-court", "published_by", "2014-06-24")
    _add_edge(store, "Case:in-re-match-group-2024", "Court:delaware-supreme-court", "published_by", "2024-04-04")
    _add_edge(store, mfw, "Case:in-re-mfw-shareholders-litigation-2014", "interprets", "2014-06-24")
    _add_edge(store, match, "Case:in-re-match-group-2024", "interprets", "2024-04-04")
    _add_edge(store, provision_b, match, "superseded_by_statute", "2025-03-25", valid_from="2025-03-25", condition=litigation_not_pre)
    _add_edge(store, provision_c, match, "superseded_by_statute", "2025-03-25", valid_from="2025-03-25", condition=litigation_not_pre)
    for authority in [provision_b, provision_c, mfw, match]:
        for slug, _, _, _ in element_specs:
            _add_edge(store, authority, f"Element:{slug}", "addresses", store.nodes[authority].known_from.isoformat())
    for slug, _, keys, _ in element_specs:
        for key in keys:
            _add_edge(store, f"ProcessFact:{key}", f"Element:{slug}", "satisfies", "2014-01-01")
    for source_id in ["Source:sec_edgar", "Source:de_code_online", "Source:de_legislature", "Source:de_courts", "Source:courtlistener"]:
        _add_edge(store, "Court:delaware-supreme-court", source_id, "published_by", "2026-11-07")
    return store


def _validate_node_predicates(node: Node) -> None:
    for predicate_key in ("safe_harbor_when", "bjr_when", "met_when", "unmet_when"):
        if predicate_key in node.props:
            validate(node.props[predicate_key], FACT_KEYS)
    if node.scope_frame:
        validate(node.scope_frame.applies_when, FACT_KEYS)
        validate(node.scope_frame.non_application, FACT_KEYS)
        for exception in node.scope_frame.exceptions:
            validate(exception.when, FACT_KEYS)


def export_seed_yaml(store: GraphStore, root: Path = Path("seed")) -> None:
    nodes_dir, edges_dir, frames_dir = root / "nodes", root / "edges", root / "frames"
    for directory in (nodes_dir, edges_dir, frames_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob("*.yaml"):
            old.unlink()
    node_groups: dict[str, list[dict[str, Any]]] = {}
    edge_groups: dict[str, list[dict[str, Any]]] = {}
    frames: list[dict[str, Any]] = []
    for node in store.nodes.values():
        node_groups.setdefault(node.node_type.lower(), []).append(node.model_dump(mode="json"))
        if node.scope_frame:
            frames.append({"node_id": node.node_id, "scope_frame": node.scope_frame.model_dump(mode="json")})
    for edge in store.edges.values():
        edge_groups.setdefault(edge.edge_type, []).append(edge.model_dump(mode="json"))
    for group, rows in node_groups.items():
        (nodes_dir / f"{group}.yaml").write_text(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True), encoding="utf-8")
    for group, rows in edge_groups.items():
        (edges_dir / f"{group}.yaml").write_text(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (frames_dir / "scope_frames.yaml").write_text(yaml.safe_dump(frames, sort_keys=False, allow_unicode=True), encoding="utf-8")
