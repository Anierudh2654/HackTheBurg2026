"""Metrics for typed legal-edge prediction and tagged failure-pattern replay."""
from __future__ import annotations

from collections import defaultdict
import random
from typing import Any

from sklearn.metrics import average_precision_score, roc_auc_score


def link_prediction_metrics(labels: list[int], scores: list[float], *, k: int = 10) -> dict[str, Any]:
    if len(labels) != len(scores) or not labels:
        raise ValueError("labels and scores must be non-empty and aligned")
    result: dict[str, Any] = {"n": len(labels), "positives": int(sum(labels))}
    result["auc"] = float(roc_auc_score(labels, scores)) if len(set(labels)) > 1 else None
    result["average_precision"] = float(average_precision_score(labels, scores)) if sum(labels) else None
    ranked = sorted(zip(scores, labels), reverse=True)
    result[f"hits@{k}"] = int(any(label == 1 for _, label in ranked[:k]))
    reciprocal_rank = next((1.0 / rank for rank, (_, label) in enumerate(ranked, 1) if label), 0.0)
    result["mrr"] = reciprocal_rank
    return result


def tagged_error_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize detector outcomes by reviewed failure type and coverage status.

    Expected item keys: failure_type, expected_flag, predicted_flag, covered.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        required = {"failure_type", "expected_flag", "predicted_flag", "covered"}
        if not required.issubset(item):
            raise ValueError(f"benchmark item missing fields: {sorted(required - set(item))}")
        groups[str(item["failure_type"])].append(item)
    report: dict[str, Any] = {"n": len(items), "by_failure_type": {}}
    for failure_type, group in sorted(groups.items()):
        expected = [bool(row["expected_flag"]) for row in group]
        predicted = [bool(row["predicted_flag"]) for row in group]
        bad = sum(expected)
        misses = sum(a and not b for a, b in zip(expected, predicted))
        miss_rate = misses / bad if bad else None
        miss_ci = _bootstrap_miss_ci(group) if bad else None
        report["by_failure_type"][failure_type] = {
            "n": len(group), "covered": sum(bool(row["covered"]) for row in group),
            "true_positive": sum(a and b for a, b in zip(expected, predicted)),
            "misses": misses,
            "false_alarms": sum(not a and b for a, b in zip(expected, predicted)),
            "miss_rate": miss_rate, "miss_rate_bootstrap_95ci": miss_ci,
        }
    report["coverage_rate"] = (sum(bool(row["covered"]) for row in items) / len(items)) if items else 0.0
    report["immunity_claim_supported"] = False
    report["note"] = "Finite benchmark results estimate observed error rates; they do not establish immunity."
    return report


def _bootstrap_miss_ci(group: list[dict[str, Any]], draws: int = 2000,
                       seed: int = 0) -> list[float] | None:
    positive = [row for row in group if row["expected_flag"]]
    if len(positive) < 2:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sample = [rng.choice(positive) for _ in positive]
        estimates.append(sum(not row["predicted_flag"] for row in sample) / len(sample))
    estimates.sort()
    return [estimates[int(0.025 * (draws - 1))], estimates[int(0.975 * (draws - 1))]]
