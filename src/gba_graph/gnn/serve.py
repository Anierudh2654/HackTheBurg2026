"""Always-available deterministic text-only advisory baseline."""
from __future__ import annotations

from hashlib import sha256
import math
import re
import json
from pathlib import Path
from ..contracts_local.models import Edge, EdgeProbe, EdgeScore, MissingPrediction, Node
from ..index.hybrid import cosine
from ..config import get_settings
from .calibrate import apply_calibrator
from .features import node_features, feature_index


def text_vector(text: str, dimension: int = 256) -> list[float]:
    vector = [0.0] * dimension
    for token in re.findall(r"[\w.-]+", text.casefold()):
        digest = sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    return vector


def score_edge(src: Node, dst: Node, edge_type: str, threshold: float) -> EdgeScore:
    left = f"{src.label} {src.props.get('proposition', '')} {src.props.get('section', '')}"
    right = f"{dst.label} {dst.props.get('proposition', '')} {dst.props.get('section', '')}"
    raw = cosine(text_vector(left), text_vector(right))
    calibrated = 1.0 / (1.0 + math.exp(-6.0 * (raw - 0.35)))
    return EdgeScore(src=src.node_id, dst=dst.node_id, edge_type=edge_type,
                     score_raw=raw, score_calibrated=calibrated, flag=calibrated < threshold)


class GNNScorer:
    """Load the selected model, always retaining the no-training baseline."""
    def __init__(self, model_dir: Path, model_version: str):
        self.model_version = model_version
        self.model = None
        self.rgcn_model = None
        self.relation_to_index = {}
        self.calibrator = None
        if model_version == "baseline-text-v0":
            return
        directory = model_dir / model_version
        meta_path = directory / "meta.json"
        model_path = directory / "model.joblib"
        if not meta_path.exists():
            raise RuntimeError(f"active GNN model artifacts are missing: {model_version}")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("model_version") != model_version:
            raise RuntimeError("model metadata version does not match selected model")
        if metadata.get("kind") == "text-only":
            if not model_path.exists():
                raise RuntimeError(f"active model weights are missing: {model_version}")
            from joblib import load
            self.model = load(model_path)
        elif metadata.get("kind") == "rgcn":
            try:
                import torch
                from .model_rgcn import build_model
                self.relation_to_index = {name: index for index, name in enumerate(metadata["relations"])}
                self.rgcn_model = build_model(int(metadata["feature_dim"]), len(self.relation_to_index),
                                              int(metadata["hidden_dim"]))
                self.rgcn_model.load_state_dict(torch.load(directory / "model.pt", map_location="cpu",
                                                          weights_only=True))
                self.rgcn_model.eval()
            except (ImportError, FileNotFoundError, KeyError, RuntimeError) as exc:
                raise RuntimeError("could not load R-GCN model artifacts") from exc
        else:
            raise RuntimeError("unsupported trained model kind")
        calibrator_path = directory / "calibrator.json"
        if calibrator_path.exists():
            self.calibrator = json.loads(calibrator_path.read_text(encoding="utf-8"))

    def score(self, src: Node, dst: Node, edge_type: str, threshold: float,
              graph_nodes: list[Node] | None = None, graph_edges: list[Edge] | None = None,
              as_of=None) -> EdgeScore:
        if self.model is None:
            if self.rgcn_model is not None:
                if edge_type not in self.relation_to_index:
                    return score_edge(src, dst, edge_type, threshold)
                import torch
                graph_nodes = graph_nodes or [src, dst]
                graph_edges = graph_edges or []
                idx = feature_index(graph_nodes)
                if src.node_id not in idx or dst.node_id not in idx:
                    raise ValueError("probe nodes must be included in the visible graph")
                # Remove all relations between the probed endpoints before building either
                # structural features or message-passing inputs.
                visible = [edge for edge in graph_edges
                           if not ((edge.src == src.node_id and edge.dst == dst.node_id)
                                   or (edge.src == dst.node_id and edge.dst == src.node_id))]
                target_types = {"cites", "addresses", "applies_to"}
                message = [edge for edge in visible if edge.edge_type not in target_types
                           and edge.edge_type not in {"amends", "next_version", "superseded_by_statute"}]
                pairs = [(edge, idx[edge.src], idx[edge.dst]) for edge in message
                         if edge.src in idx and edge.dst in idx and edge.edge_type in self.relation_to_index]
                edge_index = torch.tensor([[a for _, a, _ in pairs], [b for _, _, b in pairs]], dtype=torch.long)
                edge_types = torch.tensor([self.relation_to_index[edge.edge_type] for edge, _, _ in pairs],
                                          dtype=torch.long)
                x = torch.tensor(node_features(graph_nodes, message, as_of or src.known_from),
                                 dtype=torch.float32)
                with torch.no_grad():
                    embeddings = self.rgcn_model.encode(x, edge_index, edge_types)
                    rel = torch.tensor([self.relation_to_index[edge_type]], dtype=torch.long)
                    raw = float(self.rgcn_model.score(embeddings,
                        torch.tensor([idx[src.node_id]]), torch.tensor([idx[dst.node_id]]), rel).item())
                probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, raw))))
                calibrated = apply_calibrator(probability, self.calibrator) if self.calibrator else probability
                return EdgeScore(src=src.node_id, dst=dst.node_id, edge_type=edge_type,
                                 score_raw=raw, score_calibrated=calibrated,
                                 flag=calibrated < threshold)
            return score_edge(src, dst, edge_type, threshold)
        left = f"{src.label} {src.props.get('proposition', '')} {src.props.get('section', '')}"
        right = f"{dst.label} {dst.props.get('proposition', '')} {dst.props.get('section', '')}"
        pair = [(left, right, edge_type)]
        raw = float(self.model.model.decision_function([self.model.pair_features(*pair[0])])[0])
        probability = float(self.model.predict_proba(pair)[0])
        calibrated = apply_calibrator(probability, self.calibrator) if self.calibrator else probability
        return EdgeScore(src=src.node_id, dst=dst.node_id, edge_type=edge_type,
                         score_raw=raw, score_calibrated=calibrated, flag=calibrated < threshold)

    def predict_missing(self, anchors: list[Node], candidates: list[Node], exclude: set[str], top_k: int,
                        threshold: float, graph_nodes: list[Node] | None = None,
                        graph_edges: list[Edge] | None = None, as_of=None) -> list[MissingPrediction]:
        scored: list[MissingPrediction] = []
        for candidate in candidates:
            if candidate.node_id in exclude:
                continue
            links = [self.score(anchor, candidate, "addresses", threshold, graph_nodes,
                                graph_edges, as_of) for anchor in anchors]
            if not links:
                continue
            best = max(links, key=lambda item: item.score_calibrated)
            scored.append(MissingPrediction(node_id=candidate.node_id, score=best.score_calibrated,
                anchor_links=[EdgeProbe(src=item.src, dst=item.dst, edge_type=item.edge_type) for item in links]))
        return sorted(scored, key=lambda item: (-item.score, item.node_id))[:top_k]


def predict_missing(anchors: list[Node], candidates: list[Node], exclude: set[str], top_k: int, threshold: float) -> list[MissingPrediction]:
    return GNNScorer(get_settings().gnn_model_dir, get_settings().gnn_active_model).predict_missing(
        anchors, candidates, exclude, top_k, threshold)
