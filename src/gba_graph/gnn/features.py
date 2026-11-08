"""Inductive legal-graph features: text and typed context, never node-ID embeddings."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import math
import re

from ..contracts_local.models import Edge, Node

NODE_TYPES = ("Provision", "Case", "Holding", "Court", "TransactionType", "ActorClass",
              "ProcessFact", "Standard", "Source", "Element")
TEXT_DIM = 256
HASH_DIM = 64


def _bucket(value: str, dimension: int) -> int:
    return int.from_bytes(sha256(value.casefold().encode("utf-8")).digest()[:4], "big") % dimension


def node_features(nodes: list[Node], edges: list[Edge], as_of: date,
                  text_dim: int = TEXT_DIM, hash_dim: int = HASH_DIM) -> list[list[float]]:
    """Encode scope, jurisdiction, validity, treatment, type, and text context inductively."""
    if text_dim < 1 or hash_dim < 1:
        raise ValueError("feature dimensions must be positive")
    active_edges = [edge for edge in edges if edge.known_from <= as_of
                    and (edge.valid_from is None or edge.valid_from <= as_of)
                    and (edge.valid_to is None or as_of <= edge.valid_to)]
    treatment_types = {"follows", "distinguishes", "limits", "overrules",
                       "superseded_by_statute", "next_version", "amends"}
    treated: dict[str, int] = {}
    for edge in active_edges:
        if edge.edge_type in treatment_types:
            treated[edge.dst] = treated.get(edge.dst, 0) + 1
    indegree: dict[str, int] = {}
    outdegree: dict[str, int] = {}
    for edge in active_edges:
        indegree[edge.dst] = indegree.get(edge.dst, 0) + 1
        outdegree[edge.src] = outdegree.get(edge.src, 0) + 1

    rows: list[list[float]] = []
    for node in nodes:
        row = [0.0] * (len(NODE_TYPES) + text_dim + hash_dim + 10)
        if node.node_type in NODE_TYPES:
            row[NODE_TYPES.index(node.node_type)] = 1.0
        text = " ".join((node.label, str(node.props.get("proposition", "")),
                         str(node.props.get("section", "")),
                         str(node.props.get("case_name", "")),
                         str(node.props.get("citation_string", ""))))
        offset = len(NODE_TYPES)
        for token in re.findall(r"[\w.-]+", text.casefold()):
            row[offset + _bucket(token, text_dim)] += 1.0
        # Continuous features: valid interval, known time, reviewed state, current treatment,
        # and log degrees. They are visible only as of the requested date.
        scope = node.scope_frame
        jurisdiction = scope.jurisdiction if scope else str(node.props.get("jurisdiction", ""))
        labels = []
        if scope:
            labels.extend(f"actor:{value}" for value in scope.addressee_classes)
            labels.extend(f"transaction:{value}" for value in scope.transaction_types)
        offset += text_dim
        for label in [f"jurisdiction:{jurisdiction}", *labels]:
            row[offset + _bucket(label, hash_dim)] = 1.0
        offset += hash_dim
        year = as_of.year
        start = (scope.valid_from if scope else node.valid_from)
        end = (scope.valid_to if scope else node.valid_to)
        known_age = max(0, year - node.known_from.year)
        scalar = [
            1.0 if start is None or start <= as_of else 0.0,
            1.0 if end is None or as_of <= end else 0.0,
            max(-1.0, min(1.0, ((start.year if start else 1900) - year) / 200.0)),
            max(-1.0, min(1.0, ((end.year if end else 2200) - year) / 200.0)),
            min(1.0, known_age / 100.0),
            float(bool(node.audited or (scope and scope.audited))),
            min(1.0, math.log1p(treated.get(node.node_id, 0)) / 5.0),
            min(1.0, math.log1p(indegree.get(node.node_id, 0)) / 10.0),
            min(1.0, math.log1p(outdegree.get(node.node_id, 0)) / 10.0),
            1.0 if scope else 0.0,
        ]
        row[offset:] = scalar
        rows.append(row)
    return rows


def feature_index(nodes: list[Node]) -> dict[str, int]:
    """Stable only within a serialized graph; IDs are indexes, never model features."""
    return {node.node_id: index for index, node in enumerate(nodes)}
