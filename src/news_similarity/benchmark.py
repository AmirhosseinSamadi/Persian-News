"""Development-only model selection followed by a frozen held-out evaluation."""

import json
import math
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import GroupKFold

from news_similarity.evaluation import EvaluationDataset, EvaluationPair
from news_similarity.tfidf import (
    MAX_THRESHOLD,
    ModelKind,
    TfidfConfig,
    TfidfSimilarity,
    prepared_text,
    runtime_versions,
)

# Predeclared grids: their order is the final configuration tie-breaker.
CANDIDATES = {
    "word": (TfidfConfig("word", 1, 1), TfidfConfig("word", 1, 2)),
    "character": (TfidfConfig("character", 3, 5), TfidfConfig("character", 4, 6)),
}


def predictions(scores: Sequence[float], threshold: float) -> list[int]:
    if not math.isfinite(threshold) or not 0 <= threshold <= MAX_THRESHOLD:
        raise ValueError(
            "Threshold must be finite and between zero and nextafter(1, +inf)."
        )
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in scores):
        raise ValueError("Cosine scores must be finite values in [0, 1].")
    # Empty/OOV news provide no positive evidence, even at threshold zero.
    return [int(score > 0 and score >= threshold) for score in scores]


def classification_metrics(
    labels: Sequence[int], predicted: Sequence[int]
) -> dict[str, Any]:
    if not labels or len(labels) != len(predicted):
        raise ValueError(
            "Metrics require nonempty, equally sized label and prediction lists."
        )
    if any(
        type(value) is not int or value not in (0, 1) for value in [*labels, *predicted]
    ):
        raise ValueError("Labels and predictions must be binary integers.")
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predicted, average="binary", zero_division=0
    )
    return {
        "count": len(labels),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "accuracy": float(accuracy_score(labels, predicted)),
        "confusion_matrix": confusion_matrix(labels, predicted, labels=[0, 1]).tolist(),
        "confusion_matrix_order": "rows=true [0,1], columns=predicted [0,1]",
    }


def select_threshold(
    labels: Sequence[int], scores: Sequence[float]
) -> tuple[float, dict[str, Any]]:
    if len(labels) != len(scores) or not scores:
        raise ValueError(
            "Threshold selection needs equally sized, nonempty development data."
        )
    predictions(scores, 0.0)  # Validate finite scores before constructing candidates.
    candidates = sorted({value for value in scores if value > 0} | {MAX_THRESHOLD})
    best = None
    for threshold in candidates:
        metrics = classification_metrics(labels, predictions(scores, threshold))
        rank = (metrics["f1"], metrics["precision"], metrics["accuracy"], threshold)
        if best is None or rank > best[0]:
            best = (rank, threshold, metrics)
    assert best is not None
    return best[1], best[2]


def _score(model: TfidfSimilarity, pairs: Sequence[EvaluationPair]) -> list[float]:
    return model.compare_batch([(pair.text_a, pair.text_b) for pair in pairs])


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "q25": None,
            "median": None,
            "q75": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "q25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "q75": float(np.quantile(values, 0.75)),
        "max": max(values),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
    }


def analyze_scores(
    pairs: Sequence[EvaluationPair], scores: list[float], threshold: float
) -> dict[str, Any]:
    predicted = predictions(scores, threshold)
    if len(pairs) != len(scores):
        raise ValueError("Each evaluation pair must have exactly one score.")
    rows = [
        {**asdict(pair), "score": score, "prediction": prediction}
        for pair, score, prediction in zip(pairs, scores, predicted, strict=True)
    ]
    by_scenario = {}
    for category in sorted({pair.category for pair in pairs}):
        selected = [row for row in rows if row["category"] == category]
        by_scenario[category] = classification_metrics(
            [row["label"] for row in selected], [row["prediction"] for row in selected]
        )
    return {
        "metrics": classification_metrics([pair.label for pair in pairs], predicted),
        "per_scenario": by_scenario,
        "score_distributions": {
            "all": _distribution(scores),
            **{
                str(label): _distribution(
                    [row["score"] for row in rows if row["label"] == label]
                )
                for label in (0, 1)
            },
        },
        "false_positives": [
            row for row in rows if row["label"] == 0 and row["prediction"] == 1
        ],
        "false_negatives": [
            row for row in rows if row["label"] == 1 and row["prediction"] == 0
        ],
        "pairs": rows,
    }


def select_development_model(
    development: Sequence[EvaluationPair],
    *,
    kind: ModelKind,
    dataset_name: str,
    dataset_sha256: str,
    folds: int = 4,
    seed: int = 42,
) -> tuple[TfidfSimilarity, dict[str, Any]]:
    """This function deliberately receives no held-out pairs or labels."""
    if not development or any(pair.split != "development" for pair in development):
        raise ValueError("Model selection accepts development pairs only.")
    if set(pair.label for pair in development) != {0, 1}:
        raise ValueError("Development selection requires both binary classes.")
    groups = [pair.event_group_id for pair in development]
    if folds < 2 or folds > len(set(groups)):
        raise ValueError(
            "CV folds must be between two and the number of development groups."
        )
    splitter = GroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    partitions = list(splitter.split(np.zeros(len(groups)), groups=groups))
    audits, trials = [], []
    best = None
    for config in CANDIDATES[kind]:
        scores = np.zeros(len(development))
        for fold_index, (training, validation) in enumerate(partitions):
            train_pairs = [development[index] for index in training]
            validation_pairs = [development[index] for index in validation]
            model = TfidfSimilarity(config).fit_development(
                train_pairs, dataset_name=dataset_name, dataset_sha256=dataset_sha256
            )
            scores[validation] = _score(model, validation_pairs)
            if config == CANDIDATES[kind][0]:
                audits.append(
                    {
                        "fold": fold_index,
                        "fit_pair_ids": sorted(pair.pair_id for pair in train_pairs),
                        "validation_pair_ids": sorted(
                            pair.pair_id for pair in validation_pairs
                        ),
                        "fit_groups": sorted(
                            {pair.event_group_id for pair in train_pairs}
                        ),
                        "validation_groups": sorted(
                            {pair.event_group_id for pair in validation_pairs}
                        ),
                        "fit_document_count": model.provenance["document_count"],
                    }
                )
        threshold, metrics = select_threshold(
            [pair.label for pair in development], scores.tolist()
        )
        trial = {
            "configuration": asdict(config),
            "threshold": threshold,
            "development_oof_metrics": metrics,
        }
        trials.append(trial)
        rank = (metrics["f1"], metrics["precision"], metrics["accuracy"])
        if best is None or rank > best[0]:
            best = (rank, config, threshold, scores.tolist())
    assert best is not None
    # Configuration and threshold are now locked; fit one final development-only model.
    model = TfidfSimilarity(best[1]).fit_development(
        development, dataset_name=dataset_name, dataset_sha256=dataset_sha256
    )
    model.threshold = best[2]
    selection = {
        "trials": trials,
        "folds": audits,
        "development_oof": analyze_scores(development, best[3], best[2]),
        "development_in_sample": analyze_scores(
            development, _score(model, development), best[2]
        ),
    }
    return model, selection


def run_evaluation(
    dataset: EvaluationDataset,
    *,
    kinds: Sequence[ModelKind] = ("word", "character"),
    folds: int = 4,
    seed: int = 42,
) -> tuple[dict[str, Any], dict[str, TfidfSimilarity]]:
    development = sorted(
        (pair for pair in dataset.pairs if pair.split == "development"),
        key=lambda pair: pair.pair_id,
    )
    test = sorted(
        (pair for pair in dataset.pairs if pair.split == "test"),
        key=lambda pair: pair.pair_id,
    )
    if (
        not development
        or not test
        or not kinds
        or any(kind not in CANDIDATES for kind in kinds)
    ):
        raise ValueError(
            "Evaluation requires development/test pairs and supported model kinds."
        )
    for values in (
        lambda pair: {pair.event_group_id},
        lambda pair: {pair.event_id_a, pair.event_id_b},
        lambda pair: {prepared_text(pair.text_a), prepared_text(pair.text_b)} - {""},
    ):
        train_keys = set().union(*(values(pair) for pair in development))
        test_keys = set().union(*(values(pair) for pair in test))
        if train_keys & test_keys:
            raise ValueError(
                "Development/test groups, event IDs or prepared articles overlap."
            )
    models, results = {}, {}
    # Freeze every requested model before exposing test news to any transform.
    for kind in kinds:
        models[kind], results[kind] = select_development_model(
            development,
            kind=kind,
            dataset_name=dataset.name,
            dataset_sha256=dataset.sha256,
            folds=folds,
            seed=seed,
        )
    for kind in kinds:
        model = models[kind]
        results[kind].update(
            {
                "configuration": asdict(model.config),
                "threshold": model.threshold,
                "fit_provenance": model.provenance,
                "features": len(model.features),
                "test": analyze_scores(test, _score(model, test), model.threshold),
            }
        )
    report = {
        "schema_version": 1,
        "dataset": dataset.summary(),
        "runtime": runtime_versions(),
        "protocol": {
            "seed": seed,
            "folds": folds,
            "fit_corpus": "unique nonempty prepared development articles",
            "preprocessing": "lexical profile, builtin tokenizer, joined tokens, "
            "no stopwords",
            "selection": "pooled grouped-OOF development F1; precision then "
            "accuracy; grid order breaks config ties",
            "threshold_ties": "higher threshold after F1, precision and accuracy",
            "decision": "score > 0 and score >= threshold; score is not a probability",
            "test_policy": "all model configurations and thresholds frozen "
            "before held-out transformation",
        },
        "models": results,
    }
    return report, models


def save_evaluation(
    report: dict[str, Any], models: dict[str, TfidfSimilarity], directory: str | Path
) -> Path:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    for kind, model in models.items():
        model.save(destination / f"{kind}.model.json")
    path = destination / "evaluation.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    from news_similarity.baseline_reporting import render_baseline_report

    (destination / "report.md").write_text(
        render_baseline_report(report), encoding="utf-8"
    )
    return path
