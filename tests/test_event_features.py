"""Rule contracts using fictional examples, not a labeled accuracy benchmark."""

import json

import pytest

from news_similarity.event_features import EventFeatureExtractor, extract_event_features


def selected(text, kind):
    return [
        item
        for item in extract_event_features(text).features
        if item.feature_type == kind
    ]


def assert_raw_spans(result):
    for feature in result.features:
        for span in (feature.evidence, feature.clause):
            assert 0 <= span.start < span.end <= len(result.original_text)
            assert result.original_text[span.start : span.end] == span.text
        assert feature.clause.start <= feature.evidence.start
        assert feature.evidence.end <= feature.clause.end


@pytest.mark.parametrize("digits", ["۱۲۳", "123", "١٢٣", "１２３"])
def test_digit_scripts_normalize_with_original_evidence(digits):
    text = f"در تهران {digits} نفر ثبت نام کردند."
    result = extract_event_features(text)
    number = next(item for item in result.features if item.feature_type == "number")
    assert number.normalized["value"] == "123"
    assert number.normalized["unit"] == "person"
    assert number.evidence.text == f"{digits} نفر"
    assert result.original_text == text
    assert_raw_spans(result)


@pytest.mark.parametrize(
    ("text", "value", "unit", "role"),
    [
        ("۱٬۲۵۰ کیلوگرم", "1250", "kilogram", None),
        ("1,250.50 kg", "1250.5", "kilogram", None),
        ("۲٫۵ کیلومتر", "2500", "meter", None),
        ("۵۰۰ گرم", "0.5", "kilogram", None),
        ("۲ تن", "2000", "kilogram", None),
        ("۳ میلیون تومان", "30000000", "IRR", None),
        ("۲۰٪", "20", "percent", None),
        ("−۵ درجه سانتیگراد", "-5", "celsius", None),
        ("+12 نفر", "12", "person", None),
        ("۲ ساعت", "120", "minute", None),
        ("۲ مگاوات", "2000000", "watt", None),
        ("۷ دانش‌آموز", "7", "person", "pupil"),
        ("۸ دانشجو", "8", "person", "student"),
        ("۹ استاد", "9", "person", "professor"),
        ("۸۰ کیلومتر بر ساعت", "80", "km_per_hour", None),
        ("۴ تن در هکتار", "4", "tonne_per_hectare", None),
        ("کد ۱۴۰۵", "1405", None, None),
    ],
)
def test_numeric_units(text, value, unit, role):
    (number,) = selected(text, "number")
    assert number.normalized["value"] == value
    assert number.normalized["unit"] == unit
    assert number.normalized["role"] == role


def test_large_values_are_not_rounded_by_decimal_context():
    digits = "123456789012345678901234567890123456789"
    (number,) = selected(f"{digits} تومان", "number")
    assert number.normalized["value"] == digits + "0"


def test_unknown_compound_units_are_not_reduced_to_the_numerator_unit():
    (number,) = selected("۵ کیلوگرم بر ساعت", "number")
    assert number.normalized["unit"] is None
    assert number.extraction_status == "ambiguous"
    assert number.evidence.text == "۵ کیلوگرم بر ساعت"


@pytest.mark.parametrize(
    "text",
    [
        "۱,۵ نفر",
        "۱/۵ نفر",
        "۱.۲.۳ نفر",
        "۱.۲,۳۰۰ نفر",
        "۳ تا ۵ نفر",
        "۳-۵ نفر",
        "۲ میلیون میلیارد نفر",
    ],
)
def test_ambiguous_numeric_notation_does_not_invent_single_values(text):
    numbers = selected(text, "number")
    assert numbers
    assert all(item.normalized["value"] is None for item in numbers)
    assert all(item.extraction_status == "ambiguous" for item in numbers)


def test_dates_and_times_are_not_also_extracted_as_numbers():
    text = "جلسه در ۱۴۰۵/۰۸/۱۲ ساعت ۰۹:۴۵:۰۲ UTC با ۷ نفر برگزار شد."
    result = extract_event_features(text)
    (date,) = [f for f in result.features if f.feature_type == "date"]
    (time,) = [f for f in result.features if f.feature_type == "time"]
    (number,) = [f for f in result.features if f.feature_type == "number"]
    assert date.normalized["value"] == "1405-08-12"
    assert date.normalized["calendar"] == "unspecified"
    assert time.normalized == {
        "value": "09:45:02",
        "timezone": "UTC",
        "precision": "second",
    }
    assert time.evidence.text == "۰۹:۴۵:۰۲ UTC"
    assert number.normalized["value"] == "7"
    assert_raw_spans(result)


@pytest.mark.parametrize("text", ["۱۲ آبان ۱۴۰۵", "12 آبان 1405"])
def test_named_month_date_is_explicit_but_not_converted(text):
    (date,) = selected(text, "date")
    assert date.normalized == {
        "value": "1405-08-12",
        "calendar": "solar_hijri",
        "year": "1405",
        "month": "8",
        "day": "12",
    }


def test_missing_date_year_and_time_zone_remain_unknown():
    (date,) = selected("۱۲ آبان", "date")
    (time,) = selected("ساعت ۹:۴۵", "time")
    assert date.normalized["year"] is None
    assert time.normalized["timezone"] is None


@pytest.mark.parametrize(
    "text", ["1405/15/12", "۱۴۰۵/۰۱/۳۲", "۳۱ آبان ۱۴۰۵", "۲۵:۴۵", "12:70", "12:30:78"]
)
def test_structurally_invalid_dates_and_times_are_not_facts(text):
    result = extract_event_features(text)
    assert not result.features
    assert result.warnings


def test_clock_identifiers_and_unknown_offset_do_not_claim_utc():
    assert not selected("کد12:30الف", "time")
    (time,) = selected("12:30 UTC+03:30", "time")
    assert time.normalized["timezone"] is None
    assert time.evidence.text == "12:30 UTC+03:30"


def test_newlines_remain_clause_boundaries_with_original_offsets():
    result = extract_event_features("۸ نفر آمدند\n۹ نفر رفتند")
    first, second = result.features
    assert first.clause.text == "۸ نفر آمدند\n"
    assert second.clause.text == "۹ نفر رفتند"
    assert_raw_spans(result)


@pytest.mark.parametrize(
    "cue",
    ["نمی‌رود", "نشد", "نیست", "نبود", "ندارد", "هرگز", "بدون", "عدم", "تکذیب", "هیچ"],
)
def test_negation_is_preserved_without_fabricating_scope(cue):
    (negation,) = selected(f"این خبر {cue} است.", "negation")
    assert negation.normalized["scope"] == "unknown"
    assert negation.evidence.text == cue


@pytest.mark.parametrize(
    ("phrase", "polarity"),
    [
        ("لغو شد", "affirmed"),
        ("لغو نشد", "negated"),
        ("برگزار نشده است", "negated"),
        ("تصویب کرد", "affirmed"),
        ("تأيید نکرد", "negated"),
    ],
)
def test_bounded_predicates_and_arabic_variants(phrase, polarity):
    (assertion,) = selected(f"نشست {phrase}.", "assertion")
    assert assertion.normalized["value"] == polarity


def test_not_only_cue_is_explicitly_ambiguous():
    (negation,) = selected("نه تنها برگزار شد، بلکه موفق بود.", "negation")
    assert negation.extraction_status == "ambiguous"


def test_locations_require_cues_and_support_supplied_aliases():
    assert not selected("دانشگاه تهران و تیم ایران", "location")
    locations = selected("در تهران و از شیراز و شهر رشت", "location")
    assert [item.normalized["value"] for item in locations] == ["تهران", "شیراز", "رشت"]
    result = EventFeatureExtractor(locations={"شهر نمونه": "sample_city"}).extract(
        "در شهر نمونه"
    )
    assert result.features[0].normalized["value"] == "sample_city"
    assert result.features[0].evidence.text == "شهر نمونه"
    assert_raw_spans(result)
    assert not EventFeatureExtractor(locations={}).extract("در تهران").features


@pytest.mark.parametrize("locations", [{"": "city"}, {"تهران": ""}, {7: "city"}])
def test_invalid_gazetteers_fail_explicitly(locations):
    with pytest.raises(ValueError):
        EventFeatureExtractor(locations=locations)


def test_only_explicit_labeled_names_are_identified():
    text = 'شرکت «پارس» و دکتر "مینا نمونه" در تهران بودند؛ علی آمد.'
    entities = selected(text, "entity")
    assert [f.normalized["value"] for f in entities] == ["پارس", "مینا نمونه"]
    assert entities[1].normalized["entity_type"] == "person"
    assert entities[0].evidence.text == "پارس"


@pytest.mark.parametrize("text", ['شرکت «پارس"', 'شرکت "پارس»', "شرکت «  »"])
def test_malformed_or_empty_quoted_names_are_not_entities(text):
    assert not selected(text, "entity")


def test_urls_and_quoted_names_do_not_become_dates_numbers_or_negation():
    result = extract_event_features(
        "شرکت «نه ۱۲» https://example.org/1405/08/12?x=3 test12@example.org"
    )
    assert [f.feature_type for f in result.features] == ["entity"]


def test_unicode_normalization_preserves_original_offsets_and_text():
    text = "📰\u200f در\tشِيراز\n\u200c ۱۲\u00a0کیلوگرم؛ شرکت «\ufdf2»"
    result = extract_event_features(text)
    assert result.original_text == text
    assert selected(text, "location")[0].normalized["value"] == "شیراز"
    assert selected(text, "entity")[0].normalized["value"] == "الله"
    assert_raw_spans(result)
    assert json.dumps(result.to_dict(), ensure_ascii=False) == json.dumps(
        extract_event_features(text).to_dict(), ensure_ascii=False
    )


@pytest.mark.parametrize("text", [None, "", " \t\n", "\u200e\u200f\x00", "\ud800"])
def test_empty_or_malformed_unicode_returns_no_facts(text):
    result = extract_event_features(text)
    assert result.features == ()
    assert result.warnings
    assert result.original_text == (text or "")


@pytest.mark.parametrize("value", [1, b"abc", {}, []])
def test_non_text_input_rejected(value):
    with pytest.raises(TypeError, match="string"):
        extract_event_features(value)
