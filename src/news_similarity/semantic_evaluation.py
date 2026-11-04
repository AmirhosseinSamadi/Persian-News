"""Frozen semantic thresholds and explicitly separated historical/fresh evaluation."""

import hashlib
import json
import math
import re
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import GroupKFold

from news_similarity.benchmark import analyze_scores, classification_metrics
from news_similarity.evaluation import EvaluationDataset, EvaluationPair
from news_similarity.semantic import SemanticSimilarity
from news_similarity.tfidf import TfidfSimilarity, prepared_text


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def semantic_predictions(scores: list[float], threshold: float) -> list[int]:
    if not math.isfinite(threshold) or not -1 <= threshold <= 1.000000000000001:
        raise ValueError("Invalid semantic threshold.")
    if any(not math.isfinite(score) or not -1 <= score <= 1 for score in scores):
        raise ValueError("Semantic cosine scores must be finite and in [-1,1].")
    return [int(score >= threshold) for score in scores]


def select_semantic_threshold(labels: list[int], scores: list[float]) -> float:
    semantic_predictions(scores, 0)
    if not scores or len(labels) != len(scores):
        raise ValueError(
            "Threshold selection needs equally sized development labels/scores."
        )
    best = None
    for threshold in sorted(set(scores) | {float(np.nextafter(1.0, math.inf))}):
        metrics = classification_metrics(
            labels, semantic_predictions(scores, threshold)
        )
        rank = (metrics["f1"], metrics["precision"], metrics["accuracy"], threshold)
        if best is None or rank > best[0]:
            best = (rank, threshold)
    return best[1]


def add_error_rates(metrics: dict[str, Any]) -> dict[str, Any]:
    (tn, fp), (fn, tp) = metrics["confusion_matrix"]
    return {
        **metrics,
        "false_positive_rate": fp / (tn + fp) if tn + fp else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
    }


def analyze_semantic(
    pairs: list[EvaluationPair], scores: list[float], threshold: float
) -> dict[str, Any]:
    semantic_predictions(scores, threshold)
    result = analyze_scores(
        pairs, [(score + 1) / 2 for score in scores], (threshold + 1) / 2
    )
    for row, score in zip(result["pairs"], scores, strict=True):
        row["score"] = score
        row["prediction"] = int(score >= threshold)
    result["metrics"] = classification_metrics(
        [pair.label for pair in pairs], semantic_predictions(scores, threshold)
    )
    for category in result["per_scenario"]:
        rows = [row for row in result["pairs"] if row["category"] == category]
        result["per_scenario"][category] = classification_metrics(
            [row["label"] for row in rows], [row["prediction"] for row in rows]
        )
    result["false_positives"] = [
        row for row in result["pairs"] if row["label"] == 0 and row["prediction"] == 1
    ]
    result["false_negatives"] = [
        row for row in result["pairs"] if row["label"] == 1 and row["prediction"] == 0
    ]
    for stats in result["score_distributions"].values():
        for key in ("min", "q25", "median", "q75", "max", "mean"):
            if stats[key] is not None:
                stats[key] = 2 * stats[key] - 1
        if stats["std"] is not None:
            stats["std"] *= 2
    return _rates(result)


def _rates(result: dict[str, Any]) -> dict[str, Any]:
    result["metrics"] = add_error_rates(result["metrics"])
    result["per_scenario"] = {
        key: add_error_rates(value) for key, value in result["per_scenario"].items()
    }
    return result


def load_frozen_baselines(
    dataset: EvaluationDataset, directory: str | Path
) -> tuple[dict[str, TfidfSimilarity], dict[str, str]]:
    models, hashes = {}, {}
    development_ids = sorted(
        pair.pair_id for pair in dataset.pairs if pair.split == "development"
    )
    for kind in ("word", "character"):
        path = Path(directory) / f"{kind}.model.json"
        model = TfidfSimilarity.load(path)
        if (
            model.config.kind != kind
            or model.threshold is None
            or model.provenance["dataset_sha256"] != dataset.sha256
            or model.provenance["fit_pair_ids"] != development_ids
        ):
            raise ValueError(
                "Frozen TF-IDF artifacts do not match the original development corpus."
            )
        models[kind], hashes[kind] = model, file_sha256(path)
    return models, hashes


def load_semantic_freeze(path: str | Path) -> dict[str, Any]:
    try:
        frozen = json.loads(Path(path).read_text(encoding="utf-8"))
        if type(frozen["schema_version"]) is not int or frozen["schema_version"] != 1:
            raise ValueError("Unsupported semantic freeze schema.")
        threshold = frozen["threshold"]
        if type(threshold) not in (float, int):
            raise ValueError("Invalid frozen semantic threshold.")
        semantic_predictions([], threshold)
        if not re.fullmatch(r"[a-f0-9]{64}", frozen["dataset_sha256"]):
            raise ValueError("Invalid frozen dataset identity.")
        if not isinstance(frozen["model"]["configuration"], dict):
            raise ValueError("Invalid frozen model configuration.")
        return frozen
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeError):
        raise ValueError("Malformed local semantic freeze JSON.") from None


def freeze_semantic(
    model: SemanticSimilarity,
    dataset: EvaluationDataset,
    *,
    baseline_directory: str | Path,
    directory: str | Path,
    folds: int = 4,
    seed: int = 42,
) -> dict[str, Any]:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "freeze.json"
    _, baseline_hashes = load_frozen_baselines(dataset, baseline_directory)
    if path.exists():
        frozen = load_semantic_freeze(path)
        metadata = model.metadata()
        identity_keys = ("model_id", "revision", "seed")
        if (
            frozen["dataset_sha256"] != dataset.sha256
            or frozen["baseline_sha256"] != baseline_hashes
            or any(
                frozen["model"]["configuration"][key] != asdict(model.config)[key]
                for key in identity_keys
            )
            or frozen["model"]["preprocessing_fingerprint"]
            != metadata["preprocessing_fingerprint"]
            or frozen["model"]["runtime"] != metadata["runtime"]
            or frozen["seed"] != seed
            or len(frozen["folds"]) != folds
        ):
            raise ValueError(
                "Existing freeze differs. Use a separate artifact directory "
                "for a new protocol."
            )
        return frozen
    development = sorted(
        [pair for pair in dataset.pairs if pair.split == "development"],
        key=lambda pair: pair.pair_id,
    )
    if set(pair.label for pair in development) != {0, 1}:
        raise ValueError("Threshold selection requires both development classes.")
    groups = [pair.event_group_id for pair in development]
    if not 2 <= folds <= len(set(groups)):
        raise ValueError("Invalid development group-fold count.")
    scores = model.compare_batch([(pair.text_a, pair.text_b) for pair in development])
    final_threshold = select_semantic_threshold(
        [pair.label for pair in development], scores
    )
    oof_predictions = np.zeros(len(development), dtype=int)
    audits = []
    for train, validation in GroupKFold(
        n_splits=folds, shuffle=True, random_state=seed
    ).split(np.zeros(len(groups)), groups=groups):
        threshold = select_semantic_threshold(
            [development[index].label for index in train],
            [scores[index] for index in train],
        )
        oof_predictions[validation] = semantic_predictions(
            [scores[index] for index in validation], threshold
        )
        audits.append(
            {
                "training_groups": sorted({groups[index] for index in train}),
                "validation_groups": sorted({groups[index] for index in validation}),
                "threshold": threshold,
            }
        )
    frozen = {
        "schema_version": 1,
        "dataset_name": dataset.name,
        "dataset_sha256": dataset.sha256,
        "model": model.metadata(),
        "threshold": final_threshold,
        "baseline_sha256": baseline_hashes,
        "folds": audits,
        "seed": seed,
        "development_pair_ids": [pair.pair_id for pair in development],
        "development": analyze_semantic(development, scores, final_threshold),
        "group_cv_threshold_metrics": add_error_rates(
            classification_metrics(
                [pair.label for pair in development], oof_predictions.tolist()
            )
        ),
        "selection": "fixed pretrained encoder; threshold maximizes development "
        "F1, precision, accuracy, higher threshold; group CV checks threshold transfer",
        "evaluation_policy": "original test is exploratory; "
        "fresh event groups never participate in selection",
    }
    path.write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return frozen


def validate_fresh_dataset(
    original: EvaluationDataset, fresh: EvaluationDataset
) -> dict[str, Any]:
    if any(pair.split != "test" for pair in fresh.pairs):
        raise ValueError("Every fresh pair must be isolated in the test split.")
    if fresh.name == original.name or set(pair.label for pair in fresh.pairs) != {0, 1}:
        raise ValueError("Fresh data needs a distinct identity and both labels.")
    for key in ("pair_id", "event_group_id"):
        if {getattr(pair, key) for pair in original.pairs} & {
            getattr(pair, key) for pair in fresh.pairs
        }:
            raise ValueError("Fresh pair/event group IDs overlap existing data.")
    old_events = {
        event for pair in original.pairs for event in (pair.event_id_a, pair.event_id_b)
    }
    if old_events & {
        event for pair in fresh.pairs for event in (pair.event_id_a, pair.event_id_b)
    }:
        raise ValueError("Fresh event-claim IDs overlap existing data.")

    def canonical(value: str) -> str:
        return re.sub(r"\d+", "0", prepared_text(value)).casefold()

    old_texts = {
        canonical(value)
        for pair in original.pairs
        for value in (pair.text_a, pair.text_b)
    }
    fresh_texts = {
        canonical(value) for pair in fresh.pairs for value in (pair.text_a, pair.text_b)
    }
    maximum = 0.0
    for text in fresh_texts:
        for previous in old_texts:
            similarity = SequenceMatcher(None, text, previous, autojunk=False).ratio()
            maximum = max(maximum, similarity)
            if similarity >= 0.85:
                raise ValueError(
                    "Fresh text is an exact or near duplicate of existing data."
                )
    return {
        "maximum_number_masked_sequence_similarity": maximum,
        "rejection_threshold": 0.85,
        "event_ids_disjoint": True,
        "group_ids_disjoint": True,
        "limitation": "surface duplicate screening is not proof "
        "of semantic independence",
    }


def evaluate_semantic(
    model: SemanticSimilarity,
    dataset: EvaluationDataset,
    *,
    baseline_directory: str | Path,
    directory: str | Path,
    fresh: EvaluationDataset | None = None,
) -> dict[str, Any]:
    destination = Path(directory)
    frozen = freeze_semantic(
        model, dataset, baseline_directory=baseline_directory, directory=destination
    )
    baselines, baseline_hashes = load_frozen_baselines(dataset, baseline_directory)
    manifest_path = destination / "fresh_manifest.json"
    fresh_manifest = None
    if fresh is not None:
        screening = validate_fresh_dataset(dataset, fresh)
        fresh_manifest = {
            "dataset": fresh.summary(),
            "freeze_sha256": file_sha256(destination / "freeze.json"),
            "screening": screening,
            "pair_ids": [pair.pair_id for pair in fresh.pairs],
            "provenance": "new synthetic event-group challenge; "
            "same-author labels, not independently human reviewed",
        }
        if (
            manifest_path.exists()
            and json.loads(manifest_path.read_text(encoding="utf-8")) != fresh_manifest
        ):
            raise ValueError(
                "Fresh manifest is already locked to different data or freeze."
            )
        manifest_path.write_text(
            json.dumps(fresh_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    # Both thresholds and any fresh manifest are now frozen before evaluation.
    outputs = {}
    for name, pairs in (
        (
            "historical_exploratory",
            [pair for pair in dataset.pairs if pair.split == "test"],
        ),
        ("fresh_synthetic_challenge", list(fresh.pairs) if fresh else []),
    ):
        if not pairs:
            continue
        results = {
            kind: _rates(
                analyze_scores(
                    pairs,
                    baseline.compare_batch(
                        [(pair.text_a, pair.text_b) for pair in pairs]
                    ),
                    baseline.threshold,
                )
            )
            for kind, baseline in baselines.items()
        }
        results["semantic"] = analyze_semantic(
            pairs,
            model.compare_batch([(pair.text_a, pair.text_b) for pair in pairs]),
            frozen["threshold"],
        )
        differences = {}
        semantic_rows = results["semantic"]["pairs"]
        for kind in baselines:
            differences[kind] = {
                "semantic_correct_baseline_wrong": [
                    a["pair_id"]
                    for a, b in zip(semantic_rows, results[kind]["pairs"], strict=True)
                    if a["prediction"] == a["label"] and b["prediction"] != b["label"]
                ],
                "semantic_wrong_baseline_correct": [
                    a["pair_id"]
                    for a, b in zip(semantic_rows, results[kind]["pairs"], strict=True)
                    if a["prediction"] != a["label"] and b["prediction"] == b["label"]
                ],
            }
        outputs[name] = {"models": results, "paired_error_differences": differences}
    report = {
        "schema_version": 1,
        "status": "measured",
        "original_dataset": dataset.summary(),
        "model": model.metadata(),
        "threshold": frozen["threshold"],
        "development": frozen["development"]["metrics"],
        "group_cv_threshold_metrics": frozen["group_cv_threshold_metrics"],
        "baseline_sha256": baseline_hashes,
        "fresh_manifest": fresh_manifest,
        "evaluations": outputs,
        "fresh_limitation": "synthetic same-author challenge only; no unbiased "
        "real-news or independent-annotator performance claim",
    }
    historical_path = Path(baseline_directory) / "evaluation.json"
    if historical_path.is_file():
        previous = json.loads(historical_path.read_text(encoding="utf-8"))
        if previous["dataset"]["sha256"] != dataset.sha256:
            raise ValueError("Historical TF-IDF report uses a different dataset.")
        for kind in baselines:
            measured = outputs["historical_exploratory"]["models"][kind]["metrics"]
            if (
                measured["confusion_matrix"]
                != previous["models"][kind]["test"]["metrics"]["confusion_matrix"]
            ):
                raise ValueError(
                    "Frozen TF-IDF predictions no longer match Phase 1.3A."
                )
        report["historical_tfidf_matches_phase_1_3a"] = True
    (destination / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    from news_similarity.semantic_reporting import render_semantic_report

    (destination / "report.md").write_text(
        render_semantic_report(report), encoding="utf-8"
    )
    return report
