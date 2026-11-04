import hashlib
import json
from dataclasses import replace
from importlib.resources import files

import numpy as np
import pytest

from news_similarity.evaluation import load_dataset
from news_similarity.hybrid import HybridConfig
from news_similarity.hybrid_evaluation import (
    evaluate_hybrid,
    freeze_hybrid,
    grouped_components,
    load_hybrid_freeze,
    load_hybrid_matcher,
    select_development_hybrid,
    select_fusion,
)
from news_similarity.semantic import SemanticSimilarity
from news_similarity.tfidf import TfidfConfig, TfidfSimilarity


class TestEncoder:
    __test__ = False
    max_seq_length = 128

    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, sentences, **kwargs):
        return np.asarray(
            [
                [byte + 1 for byte in hashlib.sha256(text.encode()).digest()[:4]]
                for text in sentences
            ],
            dtype=float,
        )


@pytest.fixture
def setup(tmp_path):
    dataset = load_dataset()
    baselines = tmp_path / "baselines"
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
        factory=lambda _: (TestEncoder(), "cpu", "test-cache")
    )
    semantic_freeze = tmp_path / "semantic.json"
    semantic_freeze.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_sha256": dataset.sha256,
                "threshold": 0.7,
                "model": semantic.metadata(),
            }
        ),
        encoding="utf-8",
    )
    return (
        dataset,
        semantic,
        {
            "baseline_directory": baselines,
            "semantic_freeze": semantic_freeze,
            "directory": tmp_path / "hybrid",
            "folds": 2,
        },
    )


def test_nested_group_selection_never_fits_validation_articles(setup, monkeypatch):
    dataset, semantic, kwargs = setup
    original = TfidfSimilarity.fit_development
    fit_records = []

    def recording(self, pairs, **metadata):
        assert all(pair.split == "development" for pair in pairs)
        fit_records.append({pair.pair_id for pair in pairs})
        return original(self, pairs, **metadata)

    monkeypatch.setattr(TfidfSimilarity, "fit_development", recording)
    frozen, _ = freeze_hybrid(dataset, semantic, **kwargs)
    for outer in frozen["selection"]["outer_folds"]:
        assert set(outer["fit_groups"]).isdisjoint(outer["validation_groups"])
        for inner in outer["inner_folds"]:
            assert set(inner["fit_groups"]).isdisjoint(inner["validation_groups"])
            assert set(inner["fit_pair_ids"]) <= set(outer["fit_pair_ids"])
            assert set(inner["validation_pair_ids"]) <= set(outer["fit_pair_ids"])
    held_ids = {pair.pair_id for pair in dataset.pairs if pair.split == "test"}
    assert fit_records and all(record.isdisjoint(held_ids) for record in fit_records)
    assert len(frozen["selection"]["trials"]) == 9
    assert frozen["selection"]["nested_group_validation"]["hybrid"]["count"] == 48
    assert HybridConfig(**frozen["configuration"])


def test_selection_never_scores_held_out_texts(setup):
    dataset, semantic, kwargs = setup
    original = semantic.compare_batch
    allowed = {
        (pair.text_a, pair.text_b)
        for pair in dataset.pairs
        if pair.split == "development"
    }

    def development_only(pairs):
        assert set(pairs) <= allowed
        return original(pairs)

    semantic.compare_batch = development_only
    report = evaluate_hybrid(dataset, semantic, **kwargs, freeze_only=True)
    assert report["status"] == "development_frozen_before_diagnostics"
    assert not (kwargs["directory"] / "hybrid.evaluation.json").exists()


def test_test_label_changes_cannot_select_different_parameters(setup):
    dataset, semantic, kwargs = setup
    first, _ = freeze_hybrid(dataset, semantic, **kwargs)
    changed = replace(
        dataset,
        pairs=tuple(
            replace(pair, label=1 - pair.label) if pair.split == "test" else pair
            for pair in dataset.pairs
        ),
    )
    second, _ = freeze_hybrid(
        changed,
        semantic,
        **{**kwargs, "directory": kwargs["directory"].parent / "other"},
    )
    assert first["configuration"] == second["configuration"]
    assert first["selection"] == second["selection"]


def test_diagnostics_use_five_models_and_never_reselect_or_modify_old_artifacts(
    setup, monkeypatch
):
    from news_similarity import hybrid_evaluation

    dataset, semantic, kwargs = setup
    freeze_hybrid(dataset, semantic, **kwargs)
    frozen_path = kwargs["directory"] / "hybrid.freeze.json"
    before = frozen_path.read_bytes()
    protected = {
        path: path.read_bytes() for path in kwargs["baseline_directory"].iterdir()
    }
    semantic_before = kwargs["semantic_freeze"].read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("Existing freeze forbids refitting/reselection.")

    monkeypatch.setattr(hybrid_evaluation, "select_fusion", forbidden)
    monkeypatch.setattr(TfidfSimilarity, "fit_development", forbidden)
    report = evaluate_hybrid(dataset, semantic, **kwargs)
    assert report["status"] == "diagnostic_only"
    assert "Unavailable" in report["independent_evaluation"]
    for name, count in (
        ("historical_diagnostic", 24),
        ("examined_challenge_diagnostic", 32),
    ):
        evaluation = report["evaluations"][name]
        assert set(evaluation["models"]) == {
            "word",
            "character",
            "semantic",
            "hybrid_without_events",
            "hybrid",
        }
        assert all(
            result["metrics"]["count"] == count
            for result in evaluation["models"].values()
        )
        assert len(evaluation["models"]["hybrid"]["per_scenario"]) == 8
        assert (
            "false_positives_to_uncertain"
            in evaluation["false_positive_changes"]["semantic"]
        )
    assert frozen_path.read_bytes() == before
    assert all(path.read_bytes() == content for path, content in protected.items())
    assert kwargs["semantic_freeze"].read_bytes() == semantic_before
    rendered = (kwargs["directory"] / "hybrid.report.md").read_text(encoding="utf-8")
    assert "Diagnostic only" in rendered
    assert "abstention" in rendered
    assert (
        json.loads(
            (kwargs["directory"] / "hybrid.evaluation.json").read_text(encoding="utf-8")
        )["status"]
        == "diagnostic_only"
    )


def test_examined_challenge_labels_never_change_freeze(setup):
    dataset, semantic, kwargs = setup
    freeze_hybrid(dataset, semantic, **kwargs)
    before = (kwargs["directory"] / "hybrid.freeze.json").read_bytes()
    fresh = load_dataset(
        str(files("news_similarity").joinpath("data/synthetic_fresh_v1.json"))
    )
    changed = replace(
        fresh, pairs=tuple(replace(pair, label=1 - pair.label) for pair in fresh.pairs)
    )
    evaluate_hybrid(dataset, semantic, **kwargs, diagnostic_dataset=changed)
    assert (kwargs["directory"] / "hybrid.freeze.json").read_bytes() == before


def test_frozen_loading_fails_when_bindings_or_source_change(setup, monkeypatch):
    from news_similarity import hybrid_evaluation

    dataset, semantic, kwargs = setup
    freeze_hybrid(dataset, semantic, **kwargs)
    path = kwargs["directory"] / "hybrid.freeze.json"
    matcher = load_hybrid_matcher(
        semantic,
        baseline_directory=kwargs["baseline_directory"],
        semantic_freeze=kwargs["semantic_freeze"],
        freeze_path=path,
    )
    assert (
        matcher.compare("خبر", "متن").metadata["models"]["parameter_source"]
        == "development_group_oof"
    )
    with pytest.raises(ValueError, match="differs"):
        freeze_hybrid(dataset, semantic, **{**kwargs, "seed": 73})
    monkeypatch.setattr(hybrid_evaluation, "selection_fingerprint", lambda: "changed")
    with pytest.raises(ValueError, match="implementation"):
        load_hybrid_freeze(path)


def test_configurations_are_not_silently_reselected_on_load_failure(setup):
    dataset, semantic, kwargs = setup
    with pytest.raises(ValueError, match="missing"):
        load_hybrid_matcher(semantic, freeze_path=kwargs["directory"] / "missing.json")
    freeze_hybrid(dataset, semantic, **kwargs)
    kwargs["semantic_freeze"].write_text("{}")
    with pytest.raises(ValueError, match="Malformed"):
        freeze_hybrid(dataset, semantic, **kwargs)


def test_selection_rejects_test_pairs_and_cross_group_article_leakage(setup):
    dataset, semantic, kwargs = setup
    test = [pair for pair in dataset.pairs if pair.split == "test"]
    with pytest.raises(ValueError, match="development"):
        select_fusion(test, [], [])
    dev = [pair for pair in dataset.pairs if pair.split == "development"]
    duplicate = replace(dev[0], pair_id="duplicate", event_group_id="other-group")
    with pytest.raises(ValueError, match="overlap"):
        grouped_components(
            [*dev, duplicate], [0.5] * (len(dev) + 1), [], dataset, 2, 42
        )
    with pytest.raises(ValueError, match="four"):
        select_development_hybrid(
            [
                next(pair for pair in dev if pair.label == 0),
                next(pair for pair in dev if pair.label == 1),
            ],
            semantic,
            [],
            dataset,
            folds=2,
        )
