"""Explicit three-way evaluation; abstentions are never counted as correct."""

from collections.abc import Sequence
from typing import Any

from news_similarity.benchmark import classification_metrics
from news_similarity.semantic_evaluation import add_error_rates

DECISIONS = ("likely_different_event", "likely_same_event", "uncertain")


def decision_metrics(labels: Sequence[int], decisions: Sequence[str]) -> dict[str, Any]:
    if not labels or len(labels) != len(decisions):
        raise ValueError("Metrics require nonempty equally sized inputs.")
    if any(type(label) is not int or label not in (0, 1) for label in labels):
        raise ValueError("Metric labels must be binary integers.")
    if any(value not in DECISIONS for value in decisions):
        raise ValueError("Unknown event decision.")
    matrix = [[0, 0, 0], [0, 0, 0]]
    for label, decision in zip(labels, decisions, strict=True):
        matrix[label][DECISIONS.index(decision)] += 1
    (tn, fp, un), (fn, tp, up) = matrix
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn + up) if tp + fn + up else 0.0
    selected = [
        (label, DECISIONS.index(decision))
        for label, decision in zip(labels, decisions, strict=True)
        if decision != "uncertain"
    ]
    conditional = (
        add_error_rates(
            classification_metrics(
                [row[0] for row in selected], [row[1] for row in selected]
            )
        )
        if selected
        else {
            "count": 0,
            "precision": None,
            "recall": None,
            "f1": None,
            "accuracy": None,
            "false_positive_rate": None,
            "false_negative_rate": None,
            "confusion_matrix": [[0, 0], [0, 0]],
        }
    )
    return {
        "count": len(labels),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0,
        "accuracy": (tn + tp) / len(labels),
        "false_positive_rate": fp / (tn + fp + un) if tn + fp + un else None,
        "false_negative_rate": (fn + up) / (fn + tp + up) if fn + tp + up else None,
        "explicit_false_negative_rate": fn / (fn + tp + up) if fn + tp + up else None,
        "confusion_matrix": matrix,
        "confusion_matrix_order": "rows=true [different,same]; "
        "columns=predicted [different,same,uncertain]",
        "coverage": len(selected) / len(labels),
        "abstention_rate": (un + up) / len(labels),
        "abstentions": {"negative": un, "positive": up, "total": un + up},
        "decided_only": conditional,
        "policy": "All abstentions count as errors in accuracy; positive "
        "abstentions count as misses in recall/FNR. FPR includes abstained "
        "negatives in its denominator; inspect coverage and decided-only metrics.",
    }
