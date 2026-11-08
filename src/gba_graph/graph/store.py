"""Typed in-process graph repository; persistence boundary for DB adapters."""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Iterable
from ..contracts_local.models import Edge, Node


class GraphStore:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}

    def add_node(self, node: Node) -> None:
        node_type, separator, slug = node.node_id.partition(":")
        if not separator or node_type != node.node_type or not re.fullmatch(r"[a-z0-9][a-z0-9._@-]*", slug):
            raise ValueError(f"invalid graph node id: {node.node_id}")
        existing = self.nodes.get(node.node_id)
        if existing and existing.model_dump(mode="json") != node.model_dump(mode="json"):
            raise ValueError(f"conflicting graph node: {node.node_id}")
        self.nodes[node.node_id] = node

    def add_edge(self, edge: Edge) -> None:
        expected = edge_id(edge.src, edge.dst, edge.edge_type)
        if edge.edge_id != expected:
            raise ValueError(f"edge id mismatch: {edge.edge_id}")
        if edge.src not in self.nodes or edge.dst not in self.nodes:
            raise ValueError(f"edge endpoint missing: {edge.src} -> {edge.dst}")
        existing = self.edges.get(edge.edge_id)
        if existing and existing.model_dump(mode="json") != edge.model_dump(mode="json"):
            raise ValueError(f"conflicting graph edge: {edge.edge_id}")
        self.edges[edge.edge_id] = edge

    def edges_for(self, node_id: str, direction: str = "both", edge_type: str | None = None) -> list[Edge]:
        return sorted((e for e in self.edges.values()
                       if (direction in ("out", "both") and e.src == node_id
                           or direction in ("in", "both") and e.dst == node_id)
                       and (edge_type is None or e.edge_type == edge_type)), key=lambda e: e.edge_id)

    def visible_nodes(self, as_of, mode: str = "strict") -> list[Node]:
        return [n for n in self.nodes.values() if mode == "off" or n.known_from <= as_of]

    def visible_edges(self, as_of, mode: str = "strict") -> list[Edge]:
        visible = {n.node_id for n in self.visible_nodes(as_of, mode)}
        return [e for e in self.edges.values() if e.src in visible and e.dst in visible
                and (mode == "off" or e.known_from <= as_of)]


def edge_id(src: str, dst: str, edge_type: str) -> str:
    return "edge_" + sha256(f"{src}|{dst}|{edge_type}".encode("utf-8")).hexdigest()[:16]


def edges_between(edges: Iterable[Edge], node_id: str) -> list[Edge]:
    return [edge for edge in edges if edge.src == node_id or edge.dst == node_id]
