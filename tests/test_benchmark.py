import json
from dataclasses import replace

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from news_similarity.baseline_reporting import render_baseline_report
from news_similarity.benchmark import (
    MAX_THRESHOLD,
    classification_metrics,
    predictions,
    run_evaluation,
    save_evaluation,
    select_threshold,
)
from news_similarity.evaluation import load_dataset
from news_similarity.tfidf import TfidfSimilarity, prepared_text


@pytest.fixture(scope="module")
def evaluated():
    dataset = load_dataset()
    report, models = run_evaluation(dataset)
    return dataset, report, models


def test_metrics_and_confusion_order():
    result = classification_metrics([0, 0, 1, 1], [0, 1, 0, 1])
    for name in ("precision", "recall", "f1", "accuracy"):
        assert result[name] == 0.5
    assert result["confusion_matrix"] == [[1, 1], [1, 1]]
    assert classification_metrics([0, 0], [0, 0])["f1"] == 0


def test_development_threshold_and_conservative_tie_rule():
    threshold, metrics = select_threshold([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert threshold == 0.8 and metrics["f1"] == 1
    threshold, metrics = select_threshold([0, 0], [0.2, 0.9])
    assert threshold == MAX_THRESHOLD and metrics["accuracy"] == 1
    assert predictions([0, 0.5, 1], 0) == [0, 1, 1]
    assert predictions([0.5, 0.6], 0.5) == [1, 1]


@pytest.mark.parametrize(
    "scores,threshold",
    [([float("nan")], 0.5), ([-0.1], 0.5), ([1.1], 0.5), ([0.3], -1)],
)
def test_invalid_prediction_inputs(scores, threshold):
    with pytest.raises(ValueError):
        predictions(scores, threshold)


def test_groups_and_fold_fits_are_isolated(evaluated):
    dataset, report, models = evaluated
    development = {
        pair.pair_id for pair in dataset.pairs if pair.split == "development"
    }
    test = {pair.pair_id for pair in dataset.pairs if pair.split == "test"}
    for kind, result in report["models"].items():
        covered = []
        for fold in result["folds"]:
            assert set(fold["fit_pair_ids"]).isdisjoint(fold["validation_pair_ids"])
            assert set(fold["fit_groups"]).isdisjoint(fold["validation_groups"])
            assert set(fold["fit_pair_ids"]) <= development
            assert set(fold["fit_pair_ids"]).isdisjoint(test)
            covered.extend(fold["validation_pair_ids"])
        assert set(covered) == development and len(covered) == len(development)
        assert set(models[kind].provenance["fit_pair_ids"]) == development
        oof = result["development_oof"]["pairs"]
        threshold, _ = select_threshold(
            [row["label"] for row in oof], [row["score"] for row in oof]
        )
        assert threshold == result["threshold"]


def test_every_vectorizer_fit_uses_only_permitted_articles(monkeypatch):
    dataset = load_dataset()
    allowed = {
        prepared_text(value)
        for pair in dataset.pairs
        if pair.split == "development"
        for value in (pair.text_a, pair.text_b)
    }
    original = TfidfVectorizer.fit
    observed = []

    def observe(self, corpus, *args, **kwargs):
        observed.append(set(corpus))
        assert set(corpus) <= allowed
        return original(self, corpus, *args, **kwargs)

    monkeypatch.setattr(TfidfVectorizer, "fit", observe)
    report, _ = run_evaluation(dataset)
    assert len(observed) == 18  # 2 methods * (2 candidates * 4 folds + final fit)
    pair_lookup = {pair.pair_id: pair for pair in dataset.pairs}
    expected = []
    for result in report["models"].values():
        for _trial in result["trials"]:
            for fold in result["folds"]:
                corpus = {
                    prepared_text(value)
                    for pair_id in fold["fit_pair_ids"]
                    for value in (
                        pair_lookup[pair_id].text_a,
                        pair_lookup[pair_id].text_b,
                    )
                } - {""}
                expected.append(corpus)
        expected.append(allowed - {""})
    assert observed == expected


def test_test_text_and_labels_cannot_change_selection_or_fitted_statistics(evaluated):
    dataset, report, models = evaluated
    changed = replace(
        dataset,
        pairs=tuple(
            replace(
                pair,
                text_a=f"qqqheldoutA{index}",
                text_b=f"zzzheldoutB{index}",
                label=1 - pair.label,
            )
            if pair.split == "test"
            else pair
            for index, pair in enumerate(dataset.pairs)
        ),
    )
    changed_report, changed_models = run_evaluation(changed)
    for kind in models:
        assert (
            report["models"][kind]["configuration"]
            == changed_report["models"][kind]["configuration"]
        )
        assert models[kind].threshold == changed_models[kind].threshold
        assert models[kind].features == changed_models[kind].features
        np.testing.assert_array_equal(models[kind].idf, changed_models[kind].idf)
        assert models[kind].provenance == changed_models[kind].provenance


def test_all_models_frozen_before_test_scoring(monkeypatch):
    dataset = load_dataset()
    held_out = {
        (pair.text_a, pair.text_b) for pair in dataset.pairs if pair.split == "test"
    }
    original = TfidfSimilarity.compare_batch
    seen = []

    def observe(self, pairs):
        if any(pair in held_out for pair in pairs):
            assert len(final_models) == 2
            assert all(model.threshold is not None for model in final_models)
            seen.append(self.config.kind)
        return original(self, pairs)

    final_models = []
    fit = TfidfSimilarity.fit_development

    def fit_observe(self, pairs, **kwargs):
        result = fit(self, pairs, **kwargs)
        if len(pairs) == 48:
            final_models.append(result)
        return result

    monkeypatch.setattr(TfidfSimilarity, "fit_development", fit_observe)
    monkeypatch.setattr(TfidfSimilarity, "compare_batch", observe)
    run_evaluation(dataset)
    assert seen == ["word", "character"]


def test_evaluation_is_deterministic_and_has_complete_error_analysis(evaluated):
    dataset, report, _ = evaluated
    again, _ = run_evaluation(dataset)
    assert json.dumps(report, sort_keys=True) == json.dumps(again, sort_keys=True)
    for result in report["models"].values():
        test = result["test"]
        assert len(test["pairs"]) == 24
        assert len(test["per_scenario"]) == 8
        assert len(test["false_positives"]) == test["metrics"]["confusion_matrix"][0][1]
        assert len(test["false_negatives"]) == test["metrics"]["confusion_matrix"][1][0]
        assert (
            sum(test["score_distributions"][str(label)]["count"] for label in (0, 1))
            == 24
        )


def test_report_and_artifact_outputs(evaluated, tmp_path):
    _, report, models = evaluated
    path = save_evaluation(report, models, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == report
    rendered = render_baseline_report(report)
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == rendered
    assert "not calibrated probabilities" in rendered
    assert "synthetic" in rendered
    for kind in models:
        restored = TfidfSimilarity.load(tmp_path / f"{kind}.model.json")
        assert restored.threshold == models[kind].threshold
        for error in report["models"][kind]["test"]["false_positives"]:
            assert error["pair_id"] in rendered


@pytest.mark.parametrize("field", ["event_group_id", "event_id_a", "text_a"])
def test_cross_split_leakage_rejected(field):
    dataset = load_dataset()
    development = next(pair for pair in dataset.pairs if pair.split == "development")
    test = next(pair for pair in dataset.pairs if pair.split == "test")
    altered = replace(test, **{field: getattr(development, field)})
    dataset = replace(
        dataset,
        pairs=tuple(altered if pair == test else pair for pair in dataset.pairs),
    )
    with pytest.raises(ValueError, match="overlap"):
        run_evaluation(dataset)


def test_invalid_metrics_thresholds_and_folds():
    with pytest.raises(ValueError):
        classification_metrics([], [])
    with pytest.raises(ValueError):
        classification_metrics([True], [1])
    with pytest.raises(ValueError):
        select_threshold([1], [])
    with pytest.raises(ValueError, match="CV folds"):
        run_evaluation(load_dataset(), folds=1)
