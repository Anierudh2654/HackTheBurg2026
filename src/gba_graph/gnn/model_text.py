"""Text-only link-prediction model for a CPU-capable baseline comparison."""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from .serve import text_vector


class TextOnlyModel:
    def __init__(self, dimension: int = 256):
        self.dimension = dimension
        self.model = LogisticRegression(max_iter=1000, random_state=0)

    def pair_features(self, src_text: str, dst_text: str, edge_type: str) -> np.ndarray:
        left, right = text_vector(src_text, self.dimension), text_vector(dst_text, self.dimension)
        edge = text_vector(edge_type, 16)
        return np.asarray(left + right + edge, dtype=np.float32)

    def fit(self, pairs: list[tuple[str, str, str]], labels: list[int]) -> "TextOnlyModel":
        self.model.fit(np.stack([self.pair_features(*pair) for pair in pairs]), np.asarray(labels))
        return self

    def predict_proba(self, pairs: list[tuple[str, str, str]]) -> list[float]:
        return self.model.predict_proba(np.stack([self.pair_features(*pair) for pair in pairs]))[:, 1].tolist()
