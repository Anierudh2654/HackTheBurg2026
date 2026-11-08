"""Training helpers for reproducible text and optional PyG experiments."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import json
from .dataset import temporal_split, sample_degree_matched_negatives
from .features import node_features, feature_index
from .model_text import TextOnlyModel


def train_text_model(pairs: list[tuple[str, str, str]], labels: list[int], cutoff: date,
                     output_dir: Path) -> dict:
    from joblib import dump
    if not pairs or len(pairs) != len(labels) or len(set(labels)) < 2:
        raise ValueError("training requires aligned positive and negative examples")
    model = TextOnlyModel().fit(pairs, labels)
    output_dir.mkdir(parents=True, exist_ok=True)
    dump(model, output_dir / "model.joblib")
    metadata = {"model_version": "text-only-v1", "kind": "text-only", "trained_on_cutoff": cutoff.isoformat(),
                "features": "hashed text vectors plus relation vector", "training_examples": len(labels)}
    (output_dir / "meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def split_edges(edges, validation_start: date, test_start: date):
    """Expose the fixed temporal split used by training and leakage checks."""
    return temporal_split(edges, validation_start, test_start)


def train_rgcn(model, features, message_edge_index, message_edge_types, positive_edges,
               negative_edges, relation_to_index: dict[str, int], *, epochs: int = 100,
               learning_rate: float = 0.01, seed: int = 0):
    """Train a two-layer RGCN with DistMult scoring on temporally split examples."""
    try:
        import torch
        from torch.nn import functional as torch_f
    except ImportError as exc:
        raise RuntimeError("install the gnn extra to train rgcn-v1") from exc
    if not positive_edges or not negative_edges:
        raise ValueError("RGCN training requires positive and negative edges")
    torch.manual_seed(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    pos_src = torch.tensor([edge[0] for edge in positive_edges], dtype=torch.long)
    pos_dst = torch.tensor([edge[1] for edge in positive_edges], dtype=torch.long)
    pos_rel = torch.tensor([relation_to_index[edge[2]] for edge in positive_edges], dtype=torch.long)
    neg_src = torch.tensor([edge[0] for edge in negative_edges], dtype=torch.long)
    neg_dst = torch.tensor([edge[1] for edge in negative_edges], dtype=torch.long)
    neg_rel = torch.tensor([relation_to_index[edge[2]] for edge in negative_edges], dtype=torch.long)
    edge_index = torch.as_tensor(message_edge_index, dtype=torch.long)
    edge_types = torch.as_tensor(message_edge_types, dtype=torch.long)
    losses = []
    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        embeddings = model.encode(features, edge_index, edge_types)
        pos_score = model.score(embeddings, pos_src, pos_dst, pos_rel)
        neg_score = model.score(embeddings, neg_src, neg_dst, neg_rel)
        scores = torch.cat([pos_score, neg_score])
        labels = torch.cat([torch.ones_like(pos_score), torch.zeros_like(neg_score)])
        loss = torch_f.binary_cross_entropy_with_logits(scores, labels)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
    return model, {"epochs": epochs, "final_loss": losses[-1], "losses": losses}


def train_rgcn_graph(nodes, edges, validation_start: date, test_start: date,
                     output_dir: Path, *, epochs: int = 100, seed: int = 0) -> dict:
    """Train an inductive R-GCN from a separate legal graph export.

    Only audited/high-confidence cites and applies_to relations are eligible positives.
    The serving seed is not read by this routine; callers pass an explicit training graph.
    """
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("install the gnn extra to train rgcn-v1") from exc
    from .model_rgcn import build_model

    eligible = [edge for edge in edges if edge.edge_type in {"cites", "addresses", "applies_to"}
                and (edge.audited or edge.confidence is not None and edge.confidence >= 0.95)]
    splits = temporal_split(eligible, validation_start, test_start)
    if not splits["train"] or not splits["test"]:
        raise ValueError("R-GCN training needs audited train and temporal test edges")
    cutoff = validation_start
    visible_nodes = sorted((node for node in nodes if node.known_from <= cutoff), key=lambda n: n.node_id)
    index = feature_index(visible_nodes)
    train_edges = [edge for edge in splits["train"] if edge.src in index and edge.dst in index]
    train_targets = {(edge.src, edge.dst) for edge in train_edges}
    leakage_relations = {"amends", "next_version", "superseded_by_statute"}
    message = [edge for edge in edges if edge.known_from < validation_start
               and (edge.src, edge.dst) not in train_targets
               and (edge.dst, edge.src) not in train_targets
               and edge.edge_type not in leakage_relations
               and edge.edge_type not in {"cites", "addresses", "applies_to"}
               and edge.src in index and edge.dst in index]
    # With link-prediction targets removed, the training message graph may be empty;
    # feature-only R-GCN encoding remains inductive and valid.
    features = torch.tensor(node_features(visible_nodes, message, cutoff), dtype=torch.float32)
    relation_names = sorted({edge.edge_type for edge in eligible}
                            | {edge.edge_type for edge in message})
    relation_to_index = {name: index for index, name in enumerate(relation_names)}
    # Keep the parallel edge lists aligned after filtering.
    msg_pairs = [(edge, index[edge.src], index[edge.dst]) for edge in message
                 if edge.src in index and edge.dst in index and edge.edge_type in relation_to_index]
    msg_index = [[src for _, src, _ in msg_pairs], [dst for _, _, dst in msg_pairs]]
    msg_types = [relation_to_index[edge.edge_type] for edge, _, _ in msg_pairs]
    type_map = {node.node_id: node.node_type for node in visible_nodes}
    negatives = sample_degree_matched_negatives(train_edges, type_map, 5, seed,
                                                known_true_edges=eligible)
    positives = [(index[edge.src], index[edge.dst], edge.edge_type) for edge in train_edges]
    encoded_negatives = [(index[src], index[dst], relation)
                         for src, dst, relation in negatives if src in index and dst in index]
    if not encoded_negatives:
        raise ValueError("no degree-matched negatives available; provide a larger training slice")
    model = build_model(features.shape[1], len(relation_names), hidden_dim=128)
    model, training = train_rgcn(model, features, msg_index, msg_types, positives, encoded_negatives,
                                 relation_to_index, epochs=epochs, seed=seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), output_dir / "model.pt")
    metadata = {"model_version": "rgcn-v1", "kind": "rgcn", "feature_dim": int(features.shape[1]),
                "hidden_dim": 128, "relations": relation_names, "trained_on_cutoff": cutoff.isoformat(),
                "validation_start": validation_start.isoformat(), "test_start": test_start.isoformat(),
                "eligible_edges": len(eligible), "train_edges": len(train_edges),
                "training": training, "training_graph_only": True,
                "node_id_embeddings": False}
    (output_dir / "meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata
