"""Fictional rule-level contracts; examined corpora are diagnostic inputs only."""

import json
from importlib.resources import files

import pytest

from news_similarity.evaluation import load_dataset
from news_similarity.event_comparison import compare_news_features
from news_similarity.event_features import EventFeatureExtractor

ANCHOR = "جلسه «سپهر آزمایشی» در ۱۲ آبان ۱۴۰۵ ساعت ۰۹:۴۵ UTC"


def by_kind(findings, kind):
    return [finding for finding in findings if finding.feature_type == kind]


def test_equivalent_numbers_match_without_a_similarity_percentage():
    result = compare_news_features(
        "در تهران ۲٫۵ کیلومتر مسیر ساخته شد.", "در تهران 2500 متر مسیر ساخته شد."
    )
    (match,) = by_kind(result.matching_features, "number")
    assert match.values_a[0]["value"] == match.values_b[0]["value"] == "2500"
    assert match.confidence == "explicit_match"
    assert not result.conflicting_features
    assert result.event_identity == "undetermined"
    data = result.to_dict()
    assert not {"score", "similarity", "prediction", "percentage"}.intersection(data)
    assert json.loads(json.dumps(data))["event_identity"] == "undetermined"


@pytest.mark.parametrize(
    ("left", "right", "kind"),
    [
        ("۸ نفر ثبت نام کردند.", "۹ نفر ثبت نام کردند.", "number"),
        ("در تهران مسابقه برگزار شد.", "در شیراز مسابقه برگزار شد.", "location"),
        ("مسابقه ۱۴۰۵/۰۸/۱۲ برگزار شد.", "مسابقه ۱۴۰۵/۰۸/۱۳ برگزار شد.", "date"),
        ("مسابقه ساعت ۱۲:۳۰ برگزار شد.", "مسابقه ساعت ۱۴:۳۰ برگزار شد.", "time"),
        ("شرکت «باران» ثبت شد.", "شرکت «آفتاب» ثبت شد.", "entity"),
        ("نشست لغو شد.", "نشست لغو نشد.", "assertion"),
    ],
)
def test_similar_wording_differences_are_possible_not_event_verdicts(left, right, kind):
    result = compare_news_features(left, right)
    (conflict,) = by_kind(result.conflicting_features, kind)
    assert conflict.confidence == "possible_conflict"
    assert result.event_identity == "undetermined"
    assert conflict.evidence_a[0]["span"]["text"] in left
    assert conflict.evidence_b[0]["span"]["text"] in right
    assert conflict.explanation


@pytest.mark.parametrize(
    ("suffix_a", "suffix_b", "kind"),
    [
        ("لغو شد.", "لغو نشد.", "assertion"),
        ("با ۸ نفر برگزار شد.", "با ۹ نفر برگزار شد.", "number"),
    ],
)
def test_explicit_claim_conflict_requires_strict_named_temporal_anchors(
    suffix_a, suffix_b, kind
):
    result = compare_news_features(f"{ANCHOR} {suffix_a}", f"{ANCHOR} {suffix_b}")
    (conflict,) = by_kind(result.conflicting_features, kind)
    assert conflict.confidence == "confirmed_explicit_conflict"
    assert "claim" in conflict.explanation
    assert result.event_identity == "undetermined"


@pytest.mark.parametrize(
    "changed_anchor",
    [
        ANCHOR.replace(" UTC", ""),
        ANCHOR.replace("۱۲ آبان ۱۴۰۵", "۱۴۰۵/۰۸/۱۲"),
        ANCHOR.replace("۱۲ آبان ۱۴۰۵", "۱۲ آبان"),
        ANCHOR.replace("جلسه «سپهر آزمایشی»", "جلسه"),
        ANCHOR.replace("جلسه", "شرکت"),
        ANCHOR.replace("۰۹:۴۵ UTC", "۱۰:۴۵ UTC"),
        ANCHOR + " شاید",
        ANCHOR + " به گفته دبیر",
        ANCHOR + " اگر",
    ],
)
def test_weak_or_uncertain_anchors_never_confirm_a_conflict(changed_anchor):
    result = compare_news_features(f"{ANCHOR} لغو شد.", f"{changed_anchor} لغو نشد.")
    assert not any(
        f.confidence == "confirmed_explicit_conflict"
        for f in result.conflicting_features
    )


def test_question_and_negation_outside_predicate_block_confirmed_claim():
    for ending in ("؟", " بدون مجوز."):
        result = compare_news_features(
            f"{ANCHOR} لغو شد{ending}", f"{ANCHOR} لغو نشد{ending}"
        )
        assert not any(
            f.confidence == "confirmed_explicit_conflict"
            for f in result.conflicting_features
        )


def test_same_event_updates_remain_possible_discrepancies():
    result = compare_news_features(
        f"{ANCHOR} ابتدا با ۸ نفر برگزار شد.",
        f"{ANCHOR} طبق آمار تازه با ۱۰ نفر برگزار شد.",
    )
    (number,) = by_kind(result.conflicting_features, "number")
    assert number.confidence == "possible_conflict"
    assert number.evidence_a[0]["qualifiers"] == ("update_or_change",)
    assert "evolving" in number.explanation


def test_missing_information_is_not_contradiction():
    result = compare_news_features("در تهران ۱۲ نفر آمدند.", "خبری کوتاه منتشر شد.")
    assert result.conflicting_features == ()
    (number,) = by_kind(result.missing_or_unknown_features, "number")
    assert number.values_a[0]["value"] == "12"
    assert number.values_b == ()
    assert number.confidence == "insufficient_information"
    (date,) = by_kind(result.missing_or_unknown_features, "date")
    assert date.alignment == "not_observed_both"


def test_missing_year_and_untyped_numbers_are_insufficient():
    result = compare_news_features("کد ۱۲ در ۲ آبان", "کد ۱۳ در ۳ آبان")
    assert not result.conflicting_features
    assert {f.feature_type for f in result.missing_or_unknown_features} >= {
        "number",
        "date",
    }


def test_generic_negation_and_not_only_do_not_assert_opposite_claims():
    result = compare_news_features("هرگز خبر نداد.", "بدون خبر آمد.")
    (cue,) = by_kind(result.missing_or_unknown_features, "negation")
    assert cue.confidence == "insufficient_information"
    assert not result.conflicting_features
    result = compare_news_features("نه تنها موفق بود.", "نه تنها موفق بود.")
    assert by_kind(result.missing_or_unknown_features, "negation")


def test_distinct_quantity_roles_are_not_compared():
    result = compare_news_features("۱۲ دانشجو آمدند.", "۱۳ استاد آمدند.")
    assert not by_kind(result.conflicting_features, "number")
    (finding,) = by_kind(result.missing_or_unknown_features, "number")
    assert finding.values_a[0]["role"] == "student"
    assert finding.values_b[0]["role"] == "professor"


def test_multiple_numbers_align_by_clause_and_role_instead_of_order():
    result = compare_news_features(
        "۸ دانشجو آمدند. ۳ استاد رفتند. ۲ کیلومتر مسیر ساخته شد.",
        "۳ استاد رفتند. ۹ دانشجو آمدند. ۲۰۰۰ متر مسیر ساخته شد.",
    )
    conflicts = by_kind(result.conflicting_features, "number")
    matches = by_kind(result.matching_features, "number")
    assert len(conflicts) == 1
    assert conflicts[0].values_a[0]["role"] == "student"
    assert {f.values_a[0]["value"] for f in matches} == {"3", "2000"}


def test_repeated_counts_with_ambiguous_alignment_stay_unpaired():
    result = compare_news_features("۸ نفر و ۹ نفر آمدند.", "۱۰ نفر و ۱۱ نفر آمدند.")
    assert not by_kind(result.conflicting_features, "number")
    (finding,) = by_kind(result.missing_or_unknown_features, "number")
    assert len(finding.values_a) == len(finding.values_b) == 2


def test_repeated_identical_evidence_does_not_depend_on_list_removal_equality():
    result = compare_news_features(
        "۱۲ نفر آمدند. ۱۲ نفر آمدند.", "۱۲ نفر آمدند. ۱۲ نفر آمدند."
    )
    # There are several possible span alignments; no arbitrary positional choice.
    (finding,) = by_kind(result.missing_or_unknown_features, "number")
    assert len(finding.evidence_a) == len(finding.evidence_b) == 2


def test_units_calendars_and_clock_precision_are_not_silently_inferred():
    examples = [
        ("۲ متر", "۳ کیلوگرم", "number"),
        ("۱۲ آبان ۱۴۰۵", "۱۴۰۵/۰۸/۱۲", "date"),
        ("۱۲:۳۰ UTC", "۱۲:۳۰ به وقت تهران", "time"),
        ("۱۲:۳۰ UTC", "۱۲:۳۰:۰۰ UTC", "time"),
    ]
    for left, right, kind in examples:
        result = compare_news_features(left, right)
        assert not by_kind(result.matching_features, kind)
        assert not by_kind(result.conflicting_features, kind)
        assert by_kind(result.missing_or_unknown_features, kind)


def test_custom_location_configuration_can_be_reused():
    extractor = EventFeatureExtractor(locations={"شهر آبی": "blue", "شهر سبز": "green"})
    result = compare_news_features("در شهر آبی", "در شهر سبز", extractor=extractor)
    (location,) = by_kind(result.conflicting_features, "location")
    assert location.values_a[0]["value"] == "blue"


def test_empty_comparison_is_deterministic_json_serializable_and_unknown():
    result = compare_news_features(None, "")
    assert not result.matching_features
    assert not result.conflicting_features
    assert len(result.missing_or_unknown_features) == 7
    assert result.to_dict() == compare_news_features(None, "").to_dict()
    json.dumps(result.to_dict())


@pytest.mark.parametrize(
    "filename", ["synthetic_pairs_v1.json", "synthetic_fresh_v1.json"]
)
def test_examined_sets_are_diagnostic_structural_regressions_only(filename):
    # Do not consult labels, categories or expected predictions. No metrics,
    # training, thresholds, artifact writes or rule tuning on examined test sets.
    dataset = load_dataset(files("news_similarity.data").joinpath(filename))
    for pair in dataset.pairs:
        result = compare_news_features(pair.text_a, pair.text_b)
        assert (
            result.to_dict()
            == compare_news_features(pair.text_a, pair.text_b).to_dict()
        )
        payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
        for news in (payload["news_a"], payload["news_b"]):
            for feature in news["features"]:
                for key in ("evidence", "clause"):
                    span = feature[key]
                    assert (
                        news["original_text"][span["start"] : span["end"]]
                        == span["text"]
                    )
        assert payload["event_identity"] == "undetermined"
