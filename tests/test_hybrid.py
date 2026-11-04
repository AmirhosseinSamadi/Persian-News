import json
from dataclasses import replace

import pytest

from news_similarity.event_comparison import compare_news_features
from news_similarity.hybrid import (
    HybridConfig,
    HybridMatcher,
    HybridModelError,
    assess_scores,
    fused_score,
)
from news_similarity.hybrid_metrics import decision_metrics
from news_similarity.semantic import SemanticModelError

ANCHOR = "جلسه «آزمون سپهر» در تهران در ۱۲ آبان ۱۴۰۵ ساعت ۰۹:۴۵ UTC"


class Scorer:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def compare_batch(self, pairs):
        self.calls.append(pairs)
        return self.values[: len(pairs)]


def test_weighted_fusion_preserves_raw_negative_semantic_score():
    config = HybridConfig(semantic_weight=0.6, word_weight=0.25)
    lexical, score = fused_score(0.8, 0.4, 0.9, config)
    assert lexical == pytest.approx(0.5)
    assert score == pytest.approx(0.74)
    evidence = compare_news_features("خبر کوتاه", "متن دوم")
    result = assess_scores(0.8, 0.4, -0.2, evidence, config)
    assert result.semantic_similarity == -0.2
    assert result.combined_ranking_score == pytest.approx(0.2)
    assert result.decision == "uncertain"
    assert "probability" in result.score_interpretation


@pytest.mark.parametrize(
    "kwargs",
    [
        {"semantic_weight": -1},
        {"semantic_weight": 1.1},
        {"word_weight": float("nan")},
        {"confirmed_penalty": float("inf")},
        {"word_weight": True},
        {"same_threshold": 0.2, "different_threshold": 0.3},
        {"same_threshold": 0, "different_threshold": 0},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        HybridConfig(**kwargs)


@pytest.mark.parametrize(
    "values", [(float("nan"), 0, 0), (0, 1.2, 0), (0, 0, -1.1), (True, 0, 0)]
)
def test_invalid_component_scores(values):
    with pytest.raises(ValueError):
        fused_score(*values, HybridConfig())


def test_config_roundtrip_and_malformed_config(tmp_path):
    path = tmp_path / "config.json"
    config = HybridConfig(semantic_weight=0.25, confirmed_penalty=0.45)
    config.save(path)
    assert HybridConfig.load(path) == config
    document = json.loads(path.read_text())
    document["schema_version"] = True
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        HybridConfig.load(path)
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="Duplicate"):
        HybridConfig.load(path)
    path.write_text("not json")
    with pytest.raises(ValueError, match="Malformed"):
        HybridConfig.load(path)


def test_strong_contradiction_penalizes_once_but_does_not_infer_different_event():
    evidence = compare_news_features(f"{ANCHOR} لغو شد.", f"{ANCHOR} لغو نشد.")
    result = assess_scores(0.9, 0.9, 0.95, evidence, HybridConfig())
    assert result.applied_penalty == 0.35
    assert result.combined_ranking_score == pytest.approx(
        result.unpenalized_score - 0.35
    )
    assert result.decision == "uncertain"
    assert result.conflict_warnings[0]["evidence_a"]
    assert result.event_evidence.news_b.original_text.endswith("لغو نشد.")
    duplicated = replace(
        evidence, conflicting_features=evidence.conflicting_features * 2
    )
    assert (
        assess_scores(0.9, 0.9, 0.95, duplicated, HybridConfig()).applied_penalty
        == 0.35
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("در تهران ۸ نفر آمدند.", "در تهران ۹ نفر آمدند."),
        ("مسابقه ۱۴۰۵/۰۸/۱۲ برگزار شد.", "مسابقه ۱۴۰۵/۰۸/۱۳ برگزار شد."),
        ("در تهران مسابقه بود.", "در شیراز مسابقه بود."),
        (
            f"{ANCHOR} ابتدا با ۸ نفر برگزار شد.",
            f"{ANCHOR} طبق آمار تازه با ۱۰ نفر برگزار شد.",
        ),
    ],
)
def test_possible_differences_and_updates_do_not_get_strong_penalties(left, right):
    result = assess_scores(
        0.95, 0.95, 0.98, compare_news_features(left, right), HybridConfig()
    )
    assert result.applied_penalty == 0
    assert result.decision == "uncertain"


def test_matching_anchors_support_same_event_but_plain_high_cosine_does_not():
    result = assess_scores(
        0.95,
        0.95,
        0.98,
        compare_news_features(f"{ANCHOR} برگزار شد.", f"{ANCHOR} برگزار شد."),
        HybridConfig(),
    )
    assert result.decision == "likely_same_event"
    without_facts = assess_scores(
        1, 1, 1, compare_news_features("خبری کوتاه", "خبری کوتاه"), HybridConfig()
    )
    assert without_facts.decision == "uncertain"


def test_missing_or_unresolved_evidence_does_not_prove_same_event():
    evidence = compare_news_features(
        f"{ANCHOR} با ۸ نفر برگزار شد.", f"{ANCHOR} برگزار شد."
    )
    assert assess_scores(1, 1, 1, evidence, HybridConfig()).decision == "uncertain"
    evidence = compare_news_features("۸ و ۹", "۱۰ و ۱۱")
    assert assess_scores(0, 0, 0, evidence, HybridConfig()).decision == "uncertain"


def test_different_event_requires_agreeing_low_scores_and_two_anchor_discrepancies():
    evidence = compare_news_features(
        "در تهران در ۱۲ آبان ۱۴۰۵ ورزش بود.", "در شیراز در ۱۸ آبان ۱۴۰۵ کتاب بود."
    )
    low = assess_scores(0.1, 0.1, 0.15, evidence, HybridConfig())
    high = assess_scores(0.9, 0.9, 0.95, evidence, HybridConfig())
    assert low.decision == "likely_different_event"
    assert high.decision == "uncertain"


def test_batch_inference_filters_empty_text_and_reuses_each_component_once():
    scorers = [Scorer([0.8, 0.6]) for _ in range(3)]
    matcher = HybridMatcher(*scorers)
    pairs = [("خبر الف", "خبر ب"), (None, "متن"), ("خبر پ", "خبر ت")]
    result = matcher.compare_batch(pairs)
    assert len(result) == 3
    assert result[1].decision == "uncertain"
    assert result[1].combined_ranking_score is None
    assert [scorer.calls for scorer in scorers] == [[[pairs[0], pairs[2]]]] * 3
    assert matcher.compare_batch([]) == []
    json.dumps([item.to_dict() for item in result], ensure_ascii=False, allow_nan=False)


def test_all_empty_inputs_require_no_model():
    class Forbidden:
        def compare_batch(self, pairs):
            pytest.fail("Empty input must not load models.")

    matcher = HybridMatcher(Forbidden(), Forbidden(), Forbidden())
    assert matcher.compare("\u200f", None).combined_ranking_score is None
    with pytest.raises(TypeError):
        matcher.compare(12, "خبر")


def test_rank_sorts_by_score_then_input_index_and_unknown_last():
    scorers = [Scorer([0.7, 0.9, 0.9]) for _ in range(3)]
    matcher = HybridMatcher(*scorers)
    ranked = matcher.rank("خبر", ["الف", "ب", "پ", ""])
    assert [item.index for item in ranked] == [1, 2, 0, 3]
    assert [
        item.index for item in matcher.rank("خبر", ["الف", "ب", "پ", ""], top_k=2)
    ] == [1, 2]
    assert matcher.rank("خبر", []) == []
    for value in (0, -1, True):
        with pytest.raises(ValueError):
            matcher.rank("خبر", [], top_k=value)


def test_inference_failures_never_substitute_fake_scores():
    class Unavailable:
        def compare_batch(self, pairs):
            raise SemanticModelError("private token 123")

    matcher = HybridMatcher(Scorer([0.8]), Scorer([0.8]), Unavailable())
    with pytest.raises(HybridModelError, match="unavailable") as caught:
        matcher.compare("خبر", "متن")
    assert "private" not in str(caught.value)
    with pytest.raises(HybridModelError):
        HybridMatcher(Scorer([]), Scorer([0.8]), Scorer([0.8])).compare("خبر", "متن")


def test_pair_and_batch_outputs_are_deterministic():
    matcher = HybridMatcher(Scorer([0.8, 0.8]), Scorer([0.7, 0.7]), Scorer([0.9, 0.9]))
    pair = (f"{ANCHOR} برگزار شد.", f"{ANCHOR} برگزار شد.")
    single = matcher.compare(*pair).to_dict()
    assert matcher.compare_batch([pair, pair])[1].to_dict() == single


def test_abstentions_are_errors_not_implicitly_correct_negatives():
    decisions = [
        "likely_different_event",
        "likely_same_event",
        "uncertain",
        "likely_same_event",
        "likely_different_event",
        "uncertain",
    ]
    metrics = decision_metrics([0, 0, 0, 1, 1, 1], decisions)
    assert metrics["confusion_matrix"] == [[1, 1, 1], [1, 1, 1]]
    assert metrics["accuracy"] == pytest.approx(2 / 6)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == pytest.approx(1 / 3)
    assert metrics["false_negative_rate"] == pytest.approx(2 / 3)
    assert metrics["false_positive_rate"] == pytest.approx(1 / 3)
    assert metrics["coverage"] == pytest.approx(4 / 6)
    assert metrics["decided_only"]["accuracy"] == 0.5


def test_all_abstained_conditional_metrics_are_unavailable():
    metrics = decision_metrics([0, 1], ["uncertain", "uncertain"])
    assert metrics["accuracy"] == metrics["f1"] == metrics["coverage"] == 0
    assert metrics["decided_only"]["f1"] is None
    assert metrics["abstentions"] == {"negative": 1, "positive": 1, "total": 2}


@pytest.mark.parametrize(
    ("labels", "decisions"),
    [([], []), ([0], []), ([True], ["uncertain"]), ([0], ["unknown"])],
)
def test_bad_metric_inputs_rejected(labels, decisions):
    with pytest.raises(ValueError):
        decision_metrics(labels, decisions)
