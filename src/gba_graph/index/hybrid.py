"""Lexical BM25-like and dense-vector hybrid ranking primitives."""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Iterable

TOKEN_RE = re.compile(r"[\w§.]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text)]


def lexical_rank(query: str, documents: Iterable[str], limit: int = 50) -> list[tuple[int, float]]:
    query_tokens = set(tokens(query))
    docs = list(documents)
    lengths = [len(tokens(doc)) for doc in docs]
    avg = (sum(lengths) / len(lengths)) if lengths else 0.0
    scored: list[tuple[int, float]] = []
    for idx, text in enumerate(docs):
        counts = Counter(tokens(text))
        score = 0.0
        for term in query_tokens:
            frequency = counts[term]
            if frequency:
                score += frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * lengths[idx] / (avg or 1)))
        if query.strip('"') and query.startswith('"') and query.endswith('"') and query.strip('"').casefold() in text.casefold():
            score += 2.0
        number_match = re.search(r"\b\d+\s*(?:Del\.|DGCL|§)", query, re.I)
        if number_match and number_match.group(0).casefold() in text.casefold():
            score += 2.0
        if score:
            scored.append((idx, score))
    return sorted(scored, key=lambda pair: (-pair[1], pair[0]))[:limit]


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    na = math.sqrt(sum(a * a for a in left))
    nb = math.sqrt(sum(b * b for b in right))
    return dot / (na * nb) if na and nb else 0.0
