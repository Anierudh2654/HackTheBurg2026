"""Optional PyTorch Geometric relational GCN link scorer."""
from __future__ import annotations


def build_model(input_dim: int, relation_count: int, hidden_dim: int = 128):
    try:
        import torch
        from torch import nn
        from torch_geometric.nn import RGCNConv
    except ImportError as exc:
        raise RuntimeError("install the gnn extra to use rgcn-v1") from exc

    class RGCNLinkModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = RGCNConv(input_dim, hidden_dim, relation_count)
            self.conv2 = RGCNConv(hidden_dim, hidden_dim, relation_count)
            self.relations = nn.Parameter(torch.empty(relation_count, hidden_dim))
            nn.init.xavier_uniform_(self.relations)

        def encode(self, x, edge_index, edge_type):
            x = torch.relu(self.conv1(x, edge_index, edge_type))
            return self.conv2(x, edge_index, edge_type)

        def score(self, embeddings, src, dst, relation):
            return (embeddings[src] * self.relations[relation] * embeddings[dst]).sum(dim=-1)

    return RGCNLinkModel()
