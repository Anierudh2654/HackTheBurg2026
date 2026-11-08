"""Temporal link-prediction splits and probe-safe message-passing edge selection."""
from datetime import date
import random
from ..contracts_local.models import Edge


def temporal_split(edges: list[Edge], validation_start: date, test_start: date) -> dict[str, list[Edge]]:
    if test_start <= validation_start:
        raise ValueError("test_start must be later than validation_start")
    train, validation, test = [], [], []
    for edge in edges:
        if edge.known_from < validation_start:
            train.append(edge)
        elif edge.known_from < test_start:
            validation.append(edge)
        else:
            test.append(edge)
    return {"train": train, "validation": validation, "test": test}


def message_edges(visible_edges: list[Edge], probe: Edge, as_of: date) -> list[Edge]:
    # Mask every relation between this endpoint pair, including reverse edges.
    # Otherwise a probe such as "limits" can be leaked by an inverse relation.
    return [edge for edge in visible_edges
            if not ((edge.src == probe.src and edge.dst == probe.dst)
                    or (edge.src == probe.dst and edge.dst == probe.src))
            and edge.known_from <= as_of]


def message_edges_for_probes(visible_edges: list[Edge], probes: list[Edge], as_of: date,
                             leakage_relations: set[str] | None = None) -> list[Edge]:
    """Return a shared message graph with probe pairs and configured leak edges masked."""
    pairs = {(edge.src, edge.dst) for edge in probes}
    pairs |= {(dst, src) for src, dst in pairs}
    leakage_relations = leakage_relations or set()
    return [edge for edge in visible_edges
            if edge.known_from <= as_of
            and (edge.src, edge.dst) not in pairs
            and edge.edge_type not in leakage_relations]


def sample_negatives(edges: list[Edge], node_types: dict[str, str], count_per_positive: int = 5,
                     seed: int = 0) -> list[tuple[str, str, str]]:
    if count_per_positive < 0:
        raise ValueError("negative count cannot be negative")
    rng = random.Random(seed)
    true = {(edge.src, edge.dst, edge.edge_type) for edge in edges}
    by_type: dict[str, list[str]] = {}
    for node_id, node_type in node_types.items():
        by_type.setdefault(node_type, []).append(node_id)
    negatives: list[tuple[str, str, str]] = []
    for edge in edges:
        candidates = [node_id for node_id in by_type.get(node_types.get(edge.dst, ""), [])
                      if node_id != edge.dst and (edge.src, node_id, edge.edge_type) not in true]
        rng.shuffle(candidates)
        negatives.extend((edge.src, dst, edge.edge_type) for dst in candidates[:count_per_positive])
    return negatives


def sample_degree_matched_negatives(edges: list[Edge], node_types: dict[str, str],
                                    count_per_positive: int = 5, seed: int = 0,
                                    degree_tolerance: int = 1,
                                    known_true_edges: list[Edge] | None = None) -> list[tuple[str, str, str]]:
    """Sample false edges with destination type and in-degree near the positive's.

    Degrees are computed from the supplied training graph only. This prevents future
    graph structure from leaking into a temporal experiment and reduces easy degree cues.
    A positive edge present anywhere in ``edges`` is never emitted as a negative.
    """
    if count_per_positive < 0 or degree_tolerance < 0:
        raise ValueError("negative count and degree tolerance must be non-negative")
    rng = random.Random(seed)
    true_edges = {(edge.src, edge.dst, edge.edge_type)
                  for edge in (known_true_edges if known_true_edges is not None else edges)}
    in_degree: dict[str, int] = {}
    for edge in edges:
        in_degree[edge.dst] = in_degree.get(edge.dst, 0) + 1
    by_type: dict[str, list[str]] = {}
    for node_id, node_type in node_types.items():
        by_type.setdefault(node_type, []).append(node_id)
    result: list[tuple[str, str, str]] = []
    for edge in edges:
        target_degree = in_degree.get(edge.dst, 0)
        candidates = [node_id for node_id in by_type.get(node_types.get(edge.dst, ""), [])
                      if node_id != edge.dst
                      and abs(in_degree.get(node_id, 0) - target_degree) <= degree_tolerance
                      and (edge.src, node_id, edge.edge_type) not in true_edges]
        rng.shuffle(candidates)
        result.extend((edge.src, dst, edge.edge_type)
                      for dst in candidates[:count_per_positive])
    return result
