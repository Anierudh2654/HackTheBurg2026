"""Point-in-time graph visibility."""
from datetime import date
from ..contracts_local.models import Edge, Node


def node_visible(node: Node, as_of: date, mode: str = "strict") -> bool:
    return mode == "off" or node.known_from <= as_of


def edge_visible(edge: Edge, as_of: date, visible_node_ids: set[str], mode: str = "strict") -> bool:
    return ((mode == "off" or edge.known_from <= as_of)
            and edge.src in visible_node_ids and edge.dst in visible_node_ids)
