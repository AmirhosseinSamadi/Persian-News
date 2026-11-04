"""Read measured artifacts only; normalize presentation, never rerun evaluation."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkSet:
    key: str
    title: str
    models: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class BenchmarkArtifact:
    family: str
    path: Path
    datasets: tuple[BenchmarkSet, ...] = ()
    error: str | None = None


def presentation_metrics(metrics):
    matrix = metrics.get("confusion_matrix")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 2
        or any(not isinstance(row, list) or len(row) not in {2, 3} for row in matrix)
        or len(matrix[0]) != len(matrix[1])
    ):
        raise ValueError("Invalid confusion matrix.")
    if any(type(value) is not int or value < 0 for row in matrix for value in row):
        raise ValueError("Invalid confusion counts.")
    count = sum(sum(row) for row in matrix)
    if count == 0 or metrics.get("count") != count:
        raise ValueError("Inconsistent benchmark count.")
    result = metrics.copy()
    for name in (
        "precision",
        "recall",
        "f1",
        "accuracy",
        "false_positive_rate",
        "false_negative_rate",
        "coverage",
        "abstention_rate",
    ):
        value = result.get(name)
        if value is not None and (
            type(value) not in (float, int)
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError("Invalid benchmark metric.")
    negatives, positives = sum(matrix[0]), sum(matrix[1])
    unknown_negative = matrix[0][2] if len(matrix[0]) == 3 else 0
    unknown_positive = matrix[1][2] if len(matrix[1]) == 3 else 0
    result.setdefault(
        "false_positive_rate", matrix[0][1] / negatives if negatives else None
    )
    result.setdefault(
        "false_negative_rate",
        (matrix[1][0] + unknown_positive) / positives if positives else None,
    )
    result.setdefault("coverage", 1 - (unknown_negative + unknown_positive) / count)
    result.setdefault("abstention_rate", (unknown_negative + unknown_positive) / count)
    return result


def _model(entry):
    scenarios = entry.get("per_scenario", {})
    if not isinstance(scenarios, dict):
        raise ValueError("Invalid scenario breakdown.")
    return {
        "metrics": presentation_metrics(entry["metrics"]),
        "per_scenario": {
            name: presentation_metrics(metrics) for name, metrics in scenarios.items()
        },
    }


def read_benchmarks(artifact_root: Path) -> tuple[BenchmarkArtifact, ...]:
    artifacts = []
    for family, relative in (
        ("TF-IDF", "tfidf/evaluation.json"),
        ("MiniLM", "semantic/evaluation.json"),
        ("Hybrid", "hybrid/hybrid.evaluation.json"),
    ):
        path = artifact_root / relative
        if not path.is_file():
            artifacts.append(
                BenchmarkArtifact(
                    family, path, error="پروندهٔ ارزیابی این مدل در دسترس نیست."
                )
            )
            continue
        try:
            if path.stat().st_size > 30_000_000:
                raise ValueError("Report is too large.")
            document = json.loads(path.read_text(encoding="utf-8"))
            sets = []
            if family == "TF-IDF":
                models = {
                    name: _model(entry["test"])
                    for name, entry in document["models"].items()
                }
                sets.append(BenchmarkSet("historical", "آزمون تاریخی · مصنوعی", models))
            else:
                for key, entry in document["evaluations"].items():
                    title = (
                        "آزمون تاریخی · مصنوعی"
                        if "historical" in key
                        else "چالش بررسی‌شده · مصنوعی"
                    )
                    sets.append(
                        BenchmarkSet(
                            key,
                            title,
                            {
                                name: _model(model)
                                for name, model in entry["models"].items()
                            },
                        )
                    )
            if not sets or any(not item.models for item in sets):
                raise ValueError("No evaluation results.")
            artifacts.append(BenchmarkArtifact(family, path, tuple(sets)))
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
            artifacts.append(
                BenchmarkArtifact(
                    family,
                    path,
                    error=(
                        "ساختار پروندهٔ ارزیابی خواندنی نیست یا با "
                        "این نمایش سازگار نیست."
                    ),
                )
            )
    return tuple(artifacts)
