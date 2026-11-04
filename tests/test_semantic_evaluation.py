import json
from dataclasses import replace

import numpy as np
import pytest

from news_similarity.evaluation import load_dataset
from news_similarity.semantic import SemanticSimilarity
from news_similarity.semantic_evaluation import (
    add_error_rates,
    analyze_semantic,
    evaluate_semantic,
    freeze_semantic,
    select_semantic_threshold,
    semantic_predictions,
    validate_fresh_dataset,
)
from news_similarity.tfidf import TfidfConfig, TfidfSimilarity


class StableEncoder:
    max_seq_length = 128

    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, sentences, **kwargs):
        import hashlib

        return np.asarray(
            [
                [int(byte) + 1 for byte in hashlib.sha256(text.encode()).digest()[:4]]
                for text in sentences
            ],
            dtype=float,
        )


@pytest.fixture
def setup(tmp_path):
    dataset = load_dataset()
    baselines = tmp_path / "tfidf"
    baselines.mkdir()
    for kind, bounds in (("word", (1, 2)), ("character", (3, 5))):
        model = TfidfSimilarity(TfidfConfig(kind, *bounds)).fit_development(
            [pair for pair in dataset.pairs if pair.split == "development"],
            dataset_name=dataset.name,
            dataset_sha256=dataset.sha256,
        )
        model.threshold = 0.4
        model.save(baselines / f"{kind}.model.json")
    semantic = SemanticSimilarity(
        factory=lambda _: (StableEncoder(), "cpu", "mock-cache")
    )
    return dataset, semantic, baselines, tmp_path / "semantic"


def test_raw_negative_scores_threshold_and_metrics():
    assert select_semantic_threshold([0, 0, 1, 1], [-0.8, -0.4, -0.1, 0.3]) == -0.1
    assert semantic_predictions([-0.1, -0.2, 0.7], -0.1) == [1, 0, 1]
    data = load_dataset()
    pairs = [replace(data.pairs[0], label=1), replace(data.pairs[1], label=0)]
    result = analyze_semantic(pairs, [-0.1, -0.8], -0.1)
    assert result["metrics"]["f1"] == 1
    assert [row["score"] for row in result["pairs"]] == [-0.1, -0.8]
    assert result["score_distributions"]["all"]["min"] == pytest.approx(-0.8)
    assert (
        add_error_rates({"confusion_matrix": [[3, 2], [1, 4]]})["false_positive_rate"]
        == 0.4
    )


def test_development_freeze_and_group_isolation(setup):
    dataset, model, baselines, output = setup
    frozen = freeze_semantic(
        model, dataset, baseline_directory=baselines, directory=output
    )
    dev_ids = {pair.pair_id for pair in dataset.pairs if pair.split == "development"}
    assert set(frozen["development_pair_ids"]) == dev_ids
    assert set(row["pair_id"] for row in frozen["development"]["pairs"]) == dev_ids
    for fold in frozen["folds"]:
        assert set(fold["training_groups"]).isdisjoint(fold["validation_groups"])
    before = (output / "freeze.json").read_bytes()
    assert (
        freeze_semantic(model, dataset, baseline_directory=baselines, directory=output)
        == frozen
    )
    assert (output / "freeze.json").read_bytes() == before


def test_historical_output_is_exploratory_and_baselines_never_refit(setup, monkeypatch):
    dataset, model, baselines, output = setup

    def fail(*args, **kwargs):
        raise AssertionError("Frozen baselines must not be refitted.")

    monkeypatch.setattr(TfidfSimilarity, "fit_development", fail)
    report = evaluate_semantic(
        model, dataset, baseline_directory=baselines, directory=output
    )
    assert set(report["evaluations"]) == {"historical_exploratory"}
    assert report["fresh_manifest"] is None
    assert (
        report["evaluations"]["historical_exploratory"]["models"]["semantic"][
            "metrics"
        ]["count"]
        == 24
    )
    assert (
        json.loads((output / "evaluation.json").read_text(encoding="utf-8"))["status"]
        == "measured"
    )


def test_test_labels_cannot_change_development_threshold(setup, tmp_path):
    dataset, model, baselines, output = setup
    first = freeze_semantic(
        model, dataset, baseline_directory=baselines, directory=output
    )
    changed = replace(
        dataset,
        pairs=tuple(
            replace(pair, label=1 - pair.label) if pair.split == "test" else pair
            for pair in dataset.pairs
        ),
    )
    second = freeze_semantic(
        model,
        changed,
        baseline_directory=baselines,
        directory=tmp_path / "second-freeze",
    )
    assert first["threshold"] == second["threshold"]
    assert first["development"] == second["development"]


def test_fresh_duplicate_and_group_leakage_rejected():
    original = load_dataset()
    samples = (
        *original.pairs[:2],
        next(pair for pair in original.pairs if pair.label == 0),
    )
    test_pairs = tuple(replace(pair, split="test") for pair in samples)
    fresh = replace(original, name="fresh", pairs=test_pairs)
    with pytest.raises(ValueError, match="overlap"):
        validate_fresh_dataset(original, fresh)
    fresh = replace(
        fresh,
        pairs=tuple(
            replace(
                pair,
                pair_id=f"new-{i}",
                event_group_id="new-group",
                event_id_a="new-event",
                event_id_b="new-event",
            )
            for i, pair in enumerate(test_pairs)
        ),
    )
    fresh = replace(
        fresh,
        pairs=(
            *fresh.pairs,
            replace(
                fresh.pairs[0], pair_id="negative", label=0, event_id_b="negative-event"
            ),
        ),
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_fresh_dataset(original, fresh)


def test_new_fixture_manifest_is_frozen_and_fresh_labels_never_tune(setup):
    from importlib.resources import files

    from news_similarity.semantic_evaluation import file_sha256

    dataset, model, baselines, output = setup
    fresh_path = files("news_similarity").joinpath("data/synthetic_fresh_v1.json")
    fresh = load_dataset(str(fresh_path))
    assert len(fresh.pairs) == 32
    assert validate_fresh_dataset(dataset, fresh)["group_ids_disjoint"] is True
    frozen = freeze_semantic(
        model, dataset, baseline_directory=baselines, directory=output
    )
    before = (output / "freeze.json").read_bytes()
    report = evaluate_semantic(
        model, dataset, baseline_directory=baselines, directory=output, fresh=fresh
    )
    manifest = json.loads((output / "fresh_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_sha256"] == file_sha256(output / "freeze.json")
    assert manifest["dataset"]["sha256"] == fresh.sha256
    assert len(manifest["pair_ids"]) == 32
    assert report["threshold"] == frozen["threshold"]
    assert (output / "freeze.json").read_bytes() == before
    modified = replace(fresh, name="changed-after-evaluation")
    with pytest.raises(ValueError, match="manifest is already locked"):
        evaluate_semantic(
            model,
            dataset,
            baseline_directory=baselines,
            directory=output,
            fresh=modified,
        )
