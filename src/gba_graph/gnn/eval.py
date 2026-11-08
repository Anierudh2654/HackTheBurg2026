"""Temporal link-prediction evaluation helpers."""
from sklearn.metrics import average_precision_score, roc_auc_score


def evaluate_binary(scores: list[float], labels: list[int]) -> dict[str, float | None]:
    if len(scores) != len(labels) or not labels:
        raise ValueError("evaluation requires aligned scores and labels")
    auc = roc_auc_score(labels, scores) if len(set(labels)) == 2 else None
    average_precision = average_precision_score(labels, scores) if any(labels) else None
    ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    positives = {index for index, label in enumerate(labels) if label}
    hits = sum(index in positives for index in ranked[:10]) / min(10, len(labels))
    reciprocal = next((1 / rank for rank, index in enumerate(ranked, 1) if index in positives), 0.0)
    return {"auc": float(auc) if auc is not None else None,
            "average_precision": float(average_precision) if average_precision is not None else None,
            "hits_at_10": hits, "mrr": reciprocal}


def evaluate_by_edge_type(records: list[dict]) -> dict[str, dict[str, float | None]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record["edge_type"], []).append(record)
    return {edge_type: evaluate_binary([item["score"] for item in items], [item["label"] for item in items])
            for edge_type, items in sorted(grouped.items())}


def authority_recall(expected_by_case: dict[str, set[str]], ranked_by_case: dict[str, list[str]], top_k: int) -> float | None:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    totals = [len(authorities) for authorities in expected_by_case.values()]
    if not sum(totals):
        return None
    recovered = sum(len(expected & set(ranked_by_case.get(case_id, [])[:top_k]))
                    for case_id, expected in expected_by_case.items())
    return recovered / sum(totals)
