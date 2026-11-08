"""Optional lazy cross-encoder reranker."""
from functools import lru_cache


@lru_cache(maxsize=2)
def _load(model_id: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(model_id, local_files_only=True)


def rerank(query: str, passages: list[str], model_id: str) -> list[tuple[int, float]]:
    if not model_id or not passages:
        return list(enumerate([0.0] * len(passages)))
    scores = _load(model_id).predict([(query, text) for text in passages])
    return sorted(enumerate(float(score) for score in scores), key=lambda item: (-item[1], item[0]))
