"""Small-sample-safe probability calibration and monotonic application."""
from __future__ import annotations

from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def fit_calibrator(scores: list[float], labels: list[int], *, isotonic_min_samples: int = 200) -> dict:
    """Use Platt scaling by default; isotonic needs a deliberately larger validation set."""
    if len(scores) != len(labels) or len(scores) < 10 or len(set(labels)) < 2:
        raise ValueError("calibration requires >=10 aligned samples from both classes")
    if len(scores) >= isotonic_min_samples:
        return {"kind": "isotonic", **fit_isotonic(scores, labels)}
    model = LogisticRegression(random_state=0)
    model.fit([[float(score)] for score in scores], labels)
    return {"kind": "platt", "coef": float(model.coef_[0][0]),
            "intercept": float(model.intercept_[0]), "samples": len(scores)}


def fit_isotonic(scores: list[float], labels: list[int]) -> dict:
    if len(scores) != len(labels) or len(scores) < 2:
        raise ValueError("calibration requires at least two aligned validation samples")
    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(scores, labels)
    return {"x": [float(x) for x in calibrator.X_thresholds_],
            "y": [float(y) for y in calibrator.y_thresholds_]}


def apply_isotonic(score: float, table: dict) -> float:
    xs, ys = table["x"], table["y"]
    if not xs or len(xs) != len(ys):
        raise ValueError("invalid isotonic table")
    if score <= xs[0]:
        return float(ys[0])
    if score >= xs[-1]:
        return float(ys[-1])
    for index in range(1, len(xs)):
        if score <= xs[index]:
            ratio = (score - xs[index - 1]) / (xs[index] - xs[index - 1])
            return float(ys[index - 1] + ratio * (ys[index] - ys[index - 1]))
    return float(ys[-1])


def apply_calibrator(score: float, calibrator: dict) -> float:
    if calibrator.get("kind") == "platt":
        import math
        value = float(calibrator["coef"]) * score + float(calibrator["intercept"])
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))
    return apply_isotonic(score, calibrator)
