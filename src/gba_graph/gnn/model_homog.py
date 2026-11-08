"""Optional homogeneous GCN comparison model."""


def build_model(input_dim: int, hidden_dim: int = 128):
    try:
        import torch
        from torch import nn
        from torch_geometric.nn import GCNConv
    except ImportError as exc:
        raise RuntimeError("install the gnn extra to use homog-caselink-v1") from exc

    class HomogeneousGCN(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = GCNConv(input_dim, hidden_dim)
            self.conv2 = GCNConv(hidden_dim, hidden_dim)

        def encode(self, x, edge_index):
            return self.conv2(torch.relu(self.conv1(x, edge_index)), edge_index)

        def score(self, embeddings, src, dst):
            return (embeddings[src] * embeddings[dst]).sum(dim=-1)

    return HomogeneousGCN()
