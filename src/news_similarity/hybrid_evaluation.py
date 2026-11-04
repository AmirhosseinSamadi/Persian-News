"""Development-group selection and immutable freezes; examined sets are diagnostic."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

from news_similarity.benchmark import predictions, select_threshold
from news_similarity.evaluation import EvaluationDataset, EvaluationPair, load_dataset
from news_similarity.event_comparison import compare_news_features
from news_similarity.hybrid import (
    POLICY_VERSION,
    HybridConfig,
    HybridMatcher,
    assess_scores,
    fused_score,
    policy_fingerprint,
    read_json,
    relevant_contradictions,
)
from news_similarity.hybrid_metrics import decision_metrics
from news_similarity.semantic import SemanticSimilarity
from news_similarity.semantic_evaluation import (
    file_sha256,
    load_frozen_baselines,
    load_semantic_freeze,
    semantic_predictions,
    validate_fresh_dataset,
)
from news_similarity.tfidf import TfidfSimilarity, prepared_text

# Declared before diagnostics. Order resolves exact ties, not examined test labels.
FUSION_GRID = tuple(
    (semantic, word) for semantic in (0.5, 0.25, 0.75) for word in (0.5, 1.0, 0.0)
)


def selection_fingerprint() -> str:
    return hashlib.sha256(
        (policy_fingerprint() + Path(__file__).read_text(encoding="utf-8")).encode()
    ).hexdigest()


def development_digest(development: Sequence[EvaluationPair]) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                asdict(pair)
                for pair in sorted(development, key=lambda pair: pair.pair_id)
            ],
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _development_only(pairs):
    if not pairs or any(pair.split != "development" for pair in pairs):
        raise ValueError("Selection accepts development pairs only.")
    if {pair.label for pair in pairs} != {0, 1}:
        raise ValueError("Development selection requires both labels.")
    owners = {}
    for pair in pairs:
        for text in (pair.text_a, pair.text_b):
            key = prepared_text(text)
            if (
                key
                and owners.setdefault(key, pair.event_group_id) != pair.event_group_id
            ):
                raise ValueError("Prepared articles overlap development groups.")


def _partitions(pairs, folds, seed):
    groups = [pair.event_group_id for pair in pairs]
    if type(folds) is not int or not 2 <= folds <= len(set(groups)):
        raise ValueError("Invalid group-aware fold count.")
    return list(
        GroupKFold(n_splits=folds, shuffle=True, random_state=seed).split(
            np.zeros(len(pairs)), groups=groups
        )
    )


def _fit_scores(training, validation, configs, dataset):
    results = []
    for config in configs:
        model = TfidfSimilarity(config).fit_development(
            training, dataset_name=dataset.name, dataset_sha256=dataset.sha256
        )
        results.append(
            model.compare_batch([(pair.text_a, pair.text_b) for pair in validation])
        )
    return results


def grouped_components(pairs, semantic_scores, configs, dataset, folds, seed):
    """No validation article contributes to vocabulary or IDF fitting."""
    _development_only(pairs)
    if len(semantic_scores) != len(pairs):
        raise ValueError("Component score count mismatch.")
    components = [[0.0, 0.0, semantic] for semantic in semantic_scores]
    audits = []
    for training, validation in _partitions(pairs, folds, seed):
        train = [pairs[index] for index in training]
        held = [pairs[index] for index in validation]
        values = _fit_scores(train, held, configs, dataset)
        for index, word, character in zip(validation, *values, strict=True):
            components[index][:2] = [word, character]
        audits.append(
            {
                "fit_pair_ids": [pair.pair_id for pair in train],
                "validation_pair_ids": [pair.pair_id for pair in held],
                "fit_groups": sorted({pair.event_group_id for pair in train}),
                "validation_groups": sorted({pair.event_group_id for pair in held}),
            }
        )
    return components, audits


def select_fusion(development, components, evidence):
    """Select a ranking-proxy threshold, never tune factual rules from labels."""
    _development_only(development)
    if len(components) != len(development) or len(evidence) != len(development):
        raise ValueError("Each development pair needs scores and evidence.")
    best, trials = None, []
    for semantic_weight, word_weight in FUSION_GRID:
        config = HybridConfig(semantic_weight=semantic_weight, word_weight=word_weight)
        scores = [
            max(
                0.0,
                fused_score(*values, config)[1]
                - (config.confirmed_penalty if relevant_contradictions(item) else 0),
            )
            for values, item in zip(components, evidence, strict=True)
        ]
        threshold, metrics = select_threshold(
            [pair.label for pair in development], scores
        )
        selected = HybridConfig(
            semantic_weight,
            word_weight,
            config.confirmed_penalty,
            threshold,
            threshold / 2,
        )
        trials.append(
            {"configuration": asdict(selected), "ranking_proxy_metrics": metrics}
        )
        rank = (metrics["f1"], metrics["precision"], metrics["accuracy"])
        if best is None or rank > best[0]:
            best = rank, selected
    return best[1], trials


def select_development_hybrid(
    development, semantic, configs, dataset, *, folds=4, seed=42
):
    _development_only(development)
    if len({pair.event_group_id for pair in development}) < 4:
        raise ValueError(
            "Nested group validation requires at least four development groups."
        )
    semantic_scores = semantic.compare_batch(
        [(pair.text_a, pair.text_b) for pair in development]
    )
    semantic_predictions(semantic_scores, 0)  # validate pretrained scores
    if len(semantic_scores) != len(development):
        raise ValueError("Semantic component score count mismatch.")
    evidence = [compare_news_features(pair.text_a, pair.text_b) for pair in development]
    outer_audits, full, ablated = (
        [],
        [None] * len(development),
        [None] * len(development),
    )
    for training, validation in _partitions(development, folds, seed):
        train = [development[index] for index in training]
        held = [development[index] for index in validation]
        inner_folds = min(folds, len({pair.event_group_id for pair in train}))
        inner, audits = grouped_components(
            train,
            [semantic_scores[index] for index in training],
            configs,
            dataset,
            inner_folds,
            seed,
        )
        config, _ = select_fusion(train, inner, [evidence[index] for index in training])
        word, character = _fit_scores(train, held, configs, dataset)
        for index, w, c in zip(validation, word, character, strict=True):
            values = w, c, semantic_scores[index], evidence[index], config
            full[index] = assess_scores(*values).decision
            ablated[index] = assess_scores(*values, use_event_evidence=False).decision
        outer_audits.append(
            {
                "fit_pair_ids": [pair.pair_id for pair in train],
                "validation_pair_ids": [pair.pair_id for pair in held],
                "fit_groups": sorted({pair.event_group_id for pair in train}),
                "validation_groups": sorted({pair.event_group_id for pair in held}),
                "configuration": asdict(config),
                "inner_folds": audits,
            }
        )
    components, final_folds = grouped_components(
        development, semantic_scores, configs, dataset, folds, seed
    )
    config, trials = select_fusion(development, components, evidence)
    return config, {
        "development_pair_ids": [pair.pair_id for pair in development],
        "development_groups": sorted({pair.event_group_id for pair in development}),
        "development_sha256": development_digest(development),
        "outer_folds": outer_audits,
        "final_oof_folds": final_folds,
        "trials": trials,
        "nested_group_validation": {
            "hybrid": decision_metrics([pair.label for pair in development], full),
            "hybrid_without_events": decision_metrics(
                [pair.label for pair in development], ablated
            ),
        },
        "protocol": "Fixed existing lexical configurations; all fold IDFs fit "
        "only training articles. Inner grouped OOF F1 selects fusion ranking "
        "proxy; outer groups measure abstaining decisions. Final grouped OOF "
        "selects frozen parameters. Development results remain diagnostic, "
        "conditional on previous model choices.",
    }


def _semantic_identity(semantic):
    metadata = semantic.metadata()
    return {
        "configuration": {
            key: metadata["configuration"][key]
            for key in ("model_id", "revision", "seed")
        },
        **{
            key: metadata[key]
            for key in (
                "runtime",
                "execution_device",
                "embedding_dimension",
                "max_seq_length",
                "preprocessing_fingerprint",
            )
        },
    }


def _bindings(dataset, baselines, semantic, semantic_freeze):
    models, hashes = load_frozen_baselines(dataset, baselines)
    frozen = load_semantic_freeze(semantic_freeze)
    identity = _semantic_identity(semantic)
    if (
        frozen["dataset_sha256"] != dataset.sha256
        or any(
            frozen["model"][key] != identity[key]
            for key in ("runtime", "preprocessing_fingerprint")
        )
        or any(
            frozen["model"]["configuration"][key] != value
            for key, value in identity["configuration"].items()
        )
    ):
        raise ValueError(
            "Semantic freeze identity differs from the requested model/dataset."
        )
    return models, {
        "policy_version": POLICY_VERSION,
        "implementation_sha256": selection_fingerprint(),
        "baseline_sha256": hashes,
        "semantic_freeze_sha256": file_sha256(semantic_freeze),
        "semantic": identity,
        "lexical": {
            key: {
                "configuration": asdict(model.config),
                "provenance": model.provenance,
                "threshold": model.threshold,
            }
            for key, model in models.items()
        },
    }


def freeze_hybrid(
    dataset,
    semantic,
    *,
    baseline_directory,
    semantic_freeze,
    directory,
    folds=4,
    seed=42,
):
    models, bindings = _bindings(dataset, baseline_directory, semantic, semantic_freeze)
    development = sorted(
        [pair for pair in dataset.pairs if pair.split == "development"],
        key=lambda pair: pair.pair_id,
    )
    destination = Path(directory)
    path = destination / "hybrid.freeze.json"
    if path.exists():
        frozen = load_hybrid_freeze(path)
        if (
            frozen["bindings"] != bindings
            or frozen["selection"]["development_sha256"]
            != development_digest(development)
            or frozen["folds"] != folds
            or frozen["seed"] != seed
        ):
            raise ValueError(
                "Existing hybrid freeze differs; use a separate output directory."
            )
        return frozen, models
    config, selection = select_development_hybrid(
        development,
        semantic,
        [models[kind].config for kind in ("word", "character")],
        dataset,
        folds=folds,
        seed=seed,
    )
    frozen = {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "configuration": asdict(config),
        "bindings": bindings,
        "selection": selection,
        "folds": folds,
        "seed": seed,
        "status": "development_frozen_before_diagnostics",
        "independent_evaluation": "unavailable; examined synthetic data "
        "is diagnostic only",
    }
    destination.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(frozen, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
    return frozen, models


def load_hybrid_freeze(path):
    try:
        frozen = read_json(path)
        if (
            type(frozen["schema_version"]) is not int
            or frozen["schema_version"] != 1
            or frozen["policy_version"] != POLICY_VERSION
        ):
            raise ValueError("Unsupported hybrid freeze.")
        HybridConfig(**frozen["configuration"])
        if frozen["bindings"]["implementation_sha256"] != selection_fingerprint():
            raise ValueError("Hybrid implementation differs from its freeze.")
        if not isinstance(frozen["selection"]["development_sha256"], str):
            raise ValueError("Missing hybrid development identity.")
        return frozen
    except (KeyError, TypeError):
        raise ValueError("Malformed hybrid freeze.") from None


def load_hybrid_matcher(
    semantic,
    *,
    baseline_directory="artifacts/tfidf",
    semantic_freeze="artifacts/semantic/freeze.json",
    freeze_path="artifacts/hybrid/hybrid.freeze.json",
):
    if not Path(freeze_path).is_file():
        raise ValueError(
            "Hybrid freeze is missing. Run evaluate-hybrid first; "
            "comparison never trains on inputs."
        )
    frozen = load_hybrid_freeze(freeze_path)
    dataset = load_dataset()
    models, bindings = _bindings(dataset, baseline_directory, semantic, semantic_freeze)
    development = [pair for pair in dataset.pairs if pair.split == "development"]
    if frozen["bindings"] != bindings or frozen["selection"][
        "development_sha256"
    ] != development_digest(development):
        raise ValueError("Hybrid model artifacts differ from the frozen bindings.")
    return HybridMatcher(
        models["word"],
        models["character"],
        semantic,
        HybridConfig(**frozen["configuration"]),
        model_metadata={
            **bindings,
            "parameter_source": "development_group_oof",
            "freeze_sha256": file_sha256(freeze_path),
        },
    )


def analyze_decisions(pairs, decisions, scores, extras=None):
    rows = [
        {
            **asdict(pair),
            "decision": decision,
            "ranking_score": score,
            **(extras[index] if extras else {}),
        }
        for index, (pair, decision, score) in enumerate(
            zip(pairs, decisions, scores, strict=True)
        )
    ]
    return {
        "metrics": decision_metrics([pair.label for pair in pairs], decisions),
        "per_scenario": {
            category: decision_metrics(
                [row["label"] for row in rows if row["category"] == category],
                [row["decision"] for row in rows if row["category"] == category],
            )
            for category in sorted({pair.category for pair in pairs})
        },
        "pairs": rows,
    }


def diagnostic_comparison(pairs, models, semantic, semantic_threshold, config):
    news = [(pair.text_a, pair.text_b) for pair in pairs]
    word, character, semantic_scores = [
        model.compare_batch(news)
        for model in (models["word"], models["character"], semantic)
    ]
    evidence = [compare_news_features(*pair) for pair in news]
    full = [
        assess_scores(w, c, s, e, config)
        for w, c, s, e in zip(word, character, semantic_scores, evidence, strict=True)
    ]
    ablated = [
        assess_scores(w, c, s, e, config, use_event_evidence=False)
        for w, c, s, e in zip(word, character, semantic_scores, evidence, strict=True)
    ]
    results = {}
    for kind, scores in (
        ("word", word),
        ("character", character),
        ("semantic", semantic_scores),
    ):
        binary = (
            semantic_predictions(scores, semantic_threshold)
            if kind == "semantic"
            else predictions(scores, models[kind].threshold)
        )
        results[kind] = analyze_decisions(
            pairs,
            [
                "likely_same_event" if value else "likely_different_event"
                for value in binary
            ],
            scores,
        )
    for name, values in (("hybrid_without_events", ablated), ("hybrid", full)):
        results[name] = analyze_decisions(
            pairs,
            [item.decision for item in values],
            [item.combined_ranking_score for item in values],
            [
                {
                    "applied_penalty": item.applied_penalty,
                    "explanation": item.explanation,
                    "event_evidence": item.event_evidence.to_dict(),
                    "conflict_warnings": item.conflict_warnings,
                }
                for item in values
            ],
        )
    changes = [
        {
            "pair_id": pair.pair_id,
            "category": pair.category,
            "label": pair.label,
            "without_events": old.decision,
            "with_events": new.decision,
            "score_without_events": old.combined_ranking_score,
            "score_with_events": new.combined_ranking_score,
            "penalty": new.applied_penalty,
            "explanation": new.explanation,
        }
        for pair, old, new in zip(pairs, ablated, full, strict=True)
        if old.decision != new.decision
        or old.combined_ranking_score != new.combined_ranking_score
    ]
    fp_changes = {}
    for name in ("word", "character", "semantic", "hybrid_without_events"):
        old_rows = results[name]["pairs"]
        fp_ids = {
            row["pair_id"]
            for row in old_rows
            if row["label"] == 0 and row["decision"] == "likely_same_event"
        }
        fp_changes[name] = {
            "baseline_false_positive_rate": results[name]["metrics"][
                "false_positive_rate"
            ],
            "hybrid_false_positive_rate": results["hybrid"]["metrics"][
                "false_positive_rate"
            ],
            "delta": results["hybrid"]["metrics"]["false_positive_rate"]
            - results[name]["metrics"]["false_positive_rate"]
            if results[name]["metrics"]["false_positive_rate"] is not None
            else None,
            "false_positives_to_uncertain": [
                pair.pair_id
                for pair, result in zip(pairs, full, strict=True)
                if pair.pair_id in fp_ids and result.decision == "uncertain"
            ],
            "false_positives_to_different": [
                pair.pair_id
                for pair, result in zip(pairs, full, strict=True)
                if pair.pair_id in fp_ids
                and result.decision == "likely_different_event"
            ],
        }
    tags = {
        "dates_times": {"date", "time"},
        "numbers": {"number"},
        "negation": {"negation", "assertion"},
        "locations": {"location"},
    }
    error_analysis = {
        name: [
            pair.pair_id
            for pair, item in zip(pairs, evidence, strict=True)
            if any(
                feature.feature_type in kinds
                for news_item in (item.news_a, item.news_b)
                for feature in news_item.features
            )
        ]
        for name, kinds in tags.items()
    }
    error_analysis["update_cues"] = [
        pair.pair_id
        for pair, item in zip(pairs, evidence, strict=True)
        if any(
            "update_or_change" in feature.qualifiers
            for news_item in (item.news_a, item.news_b)
            for feature in news_item.features
        )
    ]
    error_analysis["same_topic_different_events"] = [
        pair.pair_id for pair in pairs if pair.category == "same_topic_different_events"
    ]
    error_analysis["paraphrases"] = [
        pair.pair_id for pair in pairs if pair.category == "same_event_paraphrase"
    ]
    return {
        "models": results,
        "evidence_changes": changes,
        "false_positive_changes": fp_changes,
        "error_analysis_pair_ids": error_analysis,
    }


def evaluate_hybrid(
    dataset: EvaluationDataset,
    semantic: SemanticSimilarity,
    *,
    baseline_directory="artifacts/tfidf",
    semantic_freeze="artifacts/semantic/freeze.json",
    directory="artifacts/hybrid",
    diagnostic_dataset: EvaluationDataset | None = None,
    folds=4,
    seed=42,
    freeze_only=False,
):
    frozen, models = freeze_hybrid(
        dataset,
        semantic,
        baseline_directory=baseline_directory,
        semantic_freeze=semantic_freeze,
        directory=directory,
        folds=folds,
        seed=seed,
    )
    if freeze_only:
        return frozen
    config = HybridConfig(**frozen["configuration"])
    semantic_threshold = load_semantic_freeze(semantic_freeze)["threshold"]
    diagnostic_dataset = diagnostic_dataset or load_dataset(
        str(files("news_similarity").joinpath("data/synthetic_fresh_v1.json"))
    )
    screening = validate_fresh_dataset(dataset, diagnostic_dataset)
    # Freeze exists before either examined held-out set is transformed/scored.
    evaluations = {}
    for name, pairs in (
        (
            "historical_diagnostic",
            [pair for pair in dataset.pairs if pair.split == "test"],
        ),
        ("examined_challenge_diagnostic", list(diagnostic_dataset.pairs)),
    ):
        evaluations[name] = diagnostic_comparison(
            pairs, models, semantic, semantic_threshold, config
        )
    report = {
        "schema_version": 1,
        "status": "diagnostic_only",
        "independent_evaluation": "Unavailable: no independently verified new "
        "real-news labels. Both existing sets were previously examined.",
        "classification_definition": "Existing binary labels mean strict "
        "event-and-fact agreement, not independently verified evolving-event "
        "identity; updates can disagree with this proxy.",
        "configuration": asdict(config),
        "freeze_sha256": file_sha256(Path(directory) / "hybrid.freeze.json"),
        "bindings": frozen["bindings"],
        "selection": frozen["selection"],
        "historical_dataset": dataset.summary(),
        "challenge_dataset": diagnostic_dataset.summary(),
        "screening": screening,
        "evaluations": evaluations,
    }
    destination = Path(directory) / "hybrid.evaluation.json"
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    from news_similarity.hybrid_reporting import render_hybrid_report

    (Path(directory) / "hybrid.report.md").write_text(
        render_hybrid_report(report), encoding="utf-8"
    )
    return report
