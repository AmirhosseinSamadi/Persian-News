import json
from dataclasses import replace

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from news_similarity.evaluation import EvaluationPair
from news_similarity.tfidf import TfidfConfig, TfidfSimilarity


@pytest.fixture
def development_pairs():
    texts = [
        "علي كاشان ۱۴۰۵/۰۷/۱۰ نمی‌رود",
        "قهرمانی تیم فوتبال بندر",
        "آزمایشگاه زیست‌شناسی کرمان",
    ]
    return [
        EvaluationPair(
            str(i),
            text,
            text,
            1,
            "same_event_paraphrase",
            str(i),
            str(i),
            str(i),
            "development",
        )
        for i, text in enumerate(texts)
    ]


@pytest.fixture(params=[TfidfConfig("word", 1, 2), TfidfConfig("character", 3, 5)])
def model(request, development_pairs):
    result = TfidfSimilarity(request.param).fit_development(
        development_pairs, dataset_name="test-development", dataset_sha256="a" * 64
    )
    result.threshold = 0.4
    return result


def test_identical_persian_unicode_and_unrelated_text(model):
    assert model.compare(
        "علي كاشان ۱۴۰۵/۰۷/۱۰ نمی‌رود", "علی کاشان ۱۴۰۵/۰۷/۱۰ نمی‌رود"
    ) == pytest.approx(1)
    assert model.compare("قهرمانی تیم فوتبال بندر", "آزمایشگاه زیست‌شناسی کرمان") < 0.3
    assert model.compare("xyzqv", "xyzqv") == 0  # Identical OOV text is not evidence.


@pytest.mark.parametrize(
    "a,b", [("", ""), (None, ""), ("", "قهرمانی"), ("!!!", "\u200b")]
)
def test_empty_text_and_oov_are_zero(model, a, b):
    assert model.compare(a, b) == 0


def test_batch_matches_individual_and_never_changes_fitted_state(model):
    pairs = [("قهرمانی", "قهرمانی"), ("کرمان", "کاشان"), ("", None)]
    before = model.features, model.idf
    assert model.compare_batch(pairs) == pytest.approx(
        [model.compare(a, b) for a, b in pairs]
    )
    assert model.compare_batch([]) == []
    assert (model.features, model.idf) == before
    assert model.compare_batch(pairs) == model.compare_batch(pairs)


def test_word_tokenization_keeps_dates_negation_and_bigrams(development_pairs):
    model = TfidfSimilarity().fit_development(
        development_pairs, dataset_name="test", dataset_sha256="a" * 64
    )
    assert "۱۴۰۵/۰۷/۱۰" in model.features
    assert "نمی‌رود" in model.features
    assert "علی کاشان" in model.features
    assert model.provenance["document_count"] == 3
    unigram = TfidfSimilarity(TfidfConfig(ngram_max=1)).fit_development(
        development_pairs, dataset_name="test", dataset_sha256="a" * 64
    )
    assert "علی کاشان" not in unigram.features


def test_fitting_rejects_test_and_refitting(model, development_pairs):
    with pytest.raises(ValueError, match="cannot be refitted"):
        model.fit_development(
            development_pairs, dataset_name="test", dataset_sha256="a" * 64
        )
    with pytest.raises(ValueError, match="test news are forbidden"):
        TfidfSimilarity().fit_development(
            [replace(development_pairs[0], split="test")],
            dataset_name="test",
            dataset_sha256="a" * 64,
        )


def test_unfitted_and_empty_fit_are_clear(development_pairs):
    with pytest.raises(ValueError, match="not fitted"):
        TfidfSimilarity().compare("a", "b")
    with pytest.raises(ValueError, match="no usable text"):
        TfidfSimilarity().fit_development(
            [replace(development_pairs[0], text_a="", text_b="")],
            dataset_name="test",
            dataset_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="no features"):
        TfidfSimilarity(TfidfConfig(min_df=100)).fit_development(
            development_pairs, dataset_name="test", dataset_sha256="a" * 64
        )


def test_json_round_trip_does_not_call_fit(model, tmp_path, monkeypatch):
    path = tmp_path / "model.json"
    model.save(path)
    before = model.compare("قهرمانی تیم", "قهرمانی")

    def forbidden(*args, **kwargs):
        raise AssertionError("Loading or comparing must not fit.")

    monkeypatch.setattr(TfidfVectorizer, "fit", forbidden)
    restored = TfidfSimilarity.load(path)
    assert restored.features == model.features
    np.testing.assert_array_equal(restored.idf, model.idf)
    assert restored.compare("قهرمانی تیم", "قهرمانی") == before
    assert restored.threshold == model.threshold
    assert restored.provenance == model.provenance


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 99),
        ("format", "pickle"),
        ("features", []),
        ("features", ["a", "a"]),
        ("idf", [float("nan")]),
        ("threshold", -1),
        ("threshold", float("inf")),
        ("threshold", True),
        ("preprocessing_fingerprint", "wrong"),
        ("runtime", {}),
        ("provenance", {"fit_split": "test"}),
        ("configuration", {"kind": "semantic"}),
    ],
)
def test_invalid_artifacts_rejected(model, tmp_path, field, value):
    path = tmp_path / "model.json"
    model.save(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document[field] = value
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        TfidfSimilarity.load(path)


def test_missing_and_duplicate_json_artifacts(tmp_path):
    with pytest.raises(ValueError, match="Run evaluate-tfidf"):
        TfidfSimilarity.load(tmp_path / "missing.json")
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON"):
        TfidfSimilarity.load(path)


@pytest.mark.parametrize(
    "config",
    [
        {"kind": "other"},
        {"ngram_min": 0},
        {"ngram_max": 0},
        {"ngram_min": 3, "ngram_max": 1},
        {"min_df": True},
        {"sublinear_tf": "yes"},
    ],
)
def test_invalid_configuration(config):
    with pytest.raises(ValueError):
        TfidfConfig(**config)
