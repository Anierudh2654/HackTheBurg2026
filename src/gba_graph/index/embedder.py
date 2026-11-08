"""Lazy sentence-transformer adapter; no download occurs at import time."""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=2)
def _model(model_id: str):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_id, local_files_only=True)


def embed_texts(texts: list[str], model_id: str) -> list[list[float]]:
    if not texts:
        return []
    values = _model(model_id).encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return [[float(value) for value in row] for row in values]
