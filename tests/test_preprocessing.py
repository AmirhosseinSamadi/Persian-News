from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from importlib.util import find_spec

import pytest

from news_similarity.preprocessing import (
    PersianPreprocessor,
    PreprocessingOptions,
    preprocess_text,
)
from news_similarity.records import NewsItem


@pytest.mark.parametrize("profile", ["lexical", "semantic"])
def test_arabic_letters_and_original_preservation(profile):
    original = "علي و موسى در كاشان خبر را تأیید نکردند."
    result = preprocess_text(original, profile)
    assert result.original_text == original
    assert result.normalized_text == "علی و موسی در کاشان خبر را تأیید نکردند."
    assert "نکردند" in result.tokens
    assert "تأیید" in result.tokens
    with pytest.raises(FrozenInstanceError):
        result.normalized_text = "changed"


def test_unicode_whitespace_and_presentation_forms():
    result = preprocess_text(
        "\ufeff  ﮐتاب\u00a0\u200bفارسي\n\t  آبی \u202eجدید\u202c\x00 "
    )
    assert result.normalized_text == "کتاب فارسی آبی جدید"
    assert result.tokens == ("کتاب", "فارسی", "آبی", "جدید")
    assert preprocess_text("ا\u0653ب", "semantic").normalized_text == "آب"


@pytest.mark.parametrize("profile", ["lexical", "semantic"])
def test_half_spaces_are_preserved_and_redundant_ones_cleaned(profile):
    result = preprocess_text(
        "\u200cخبر\u200c  نمی\u200c\u200cرود و داده\u200cکاوی\u200c", profile
    )
    assert result.normalized_text == "خبر نمی‌رود و داده‌کاوی"
    assert "نمی‌رود" in result.tokens
    assert "داده‌کاوی" in result.tokens


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("preserve", "نمی‌رود"),
        ("space", "نمی رود"),
        ("remove", "نمیرود"),
    ],
)
def test_configurable_half_space_policy(policy, expected):
    options = PreprocessingOptions(zwnj=policy)
    assert (
        PersianPreprocessor(options=options).process("نمی‌رود").normalized_text
        == expected
    )


@pytest.mark.parametrize("profile", ["lexical", "semantic"])
@pytest.mark.parametrize("tokenizer", ["builtin", "hazm"])
def test_preserve_numbers_dates_names_and_negation(profile, tokenizer):
    if tokenizer == "hazm" and find_spec("hazm") is None:
        pytest.skip("Optional Hazm extra is not installed.")
    text = (
        "علی رضایی در تبریز در ۱۴۰۵/۰۷/۱۰ و 2026-10-28 ساعت ۱۰:۳۰ "
        "عدد -۵ و −۳ و +۱۲ و ۳٫۵ و ۱۲٬۰۰۰ و ۴۲% را ثبت نکرد و نمی‌رود."
    )
    options = PreprocessingOptions.for_profile(profile, tokenizer=tokenizer)
    result = PersianPreprocessor(profile, options).process(text)
    for token in (
        "علی",
        "رضایی",
        "تبریز",
        "۱۴۰۵/۰۷/۱۰",
        "2026-10-28",
        "۱۰:۳۰",
        "-۵",
        "−۳",
        "+۱۲",
        "۳٫۵",
        "۱۲٬۰۰۰",
        "۴۲%",
        "نکرد",
        "نمی‌رود",
    ):
        assert token in result.tokens
        assert token in result.normalized_text


def test_balanced_url_parentheses_and_adjacent_persian_punctuation():
    text = "خبر (https://example.test/a(b))،خبر دوم"
    removed = preprocess_text(text)
    assert removed.urls == ("https://example.test/a(b)",)
    assert "خبر دوم" in removed.normalized_text
    kept = preprocess_text(text, "semantic")
    assert "https://example.test/a(b)" in kept.tokens
    assert ")" in kept.tokens


def test_url_placeholder_collision_is_avoided():
    text = "PNSURLTOKEN0END https://example.test/x"
    assert preprocess_text(text, "semantic").normalized_text == text


def test_compatibility_normalization_cannot_create_url_marker_collision():
    text = "ＰＮＳＵＲＬＴＯＫＥＮ0END https://example.test/x"
    options = PreprocessingOptions(urls="keep")
    result = PersianPreprocessor(options=options).process(text)
    assert result.normalized_text == "PNSURLTOKEN0END https://example.test/x"


def test_arabic_indic_digits_remain_distinct_from_persian_digit_spellings():
    text = "٢٠٢٦/١٠/٢٨ در برابر ۲۰۲۶/۱۰/۲۸"
    result = preprocess_text(text)
    assert "٢٠٢٦/١٠/٢٨" in result.tokens
    assert "۲۰۲۶/۱۰/۲۸" in result.tokens


def test_semantic_half_space_next_to_diacritic_is_preserved():
    text = "نمی\u200cرَوَد"
    assert preprocess_text(text, "semantic").normalized_text == text


def test_profile_differences_and_no_stemming():
    text = "خَبَر کــتاب‌ها! #خبر_فوری @news https://example.test/x"
    lexical = preprocess_text(text)
    semantic = preprocess_text(text, "semantic")
    assert lexical.normalized_text == "خبر کتاب‌ها! خبر_فوری"
    assert lexical.tokens == ("خبر", "کتاب‌ها", "خبر_فوری")
    assert (
        semantic.normalized_text == "خَبَر کتاب‌ها! #خبر_فوری @news https://example.test/x"
    )
    assert "!" in semantic.tokens
    assert "خَبَر" in semantic.tokens
    assert "کتاب‌ها" in semantic.tokens


@pytest.mark.parametrize("text", ["", None, " \n\t ", "\ufeff\u200b\x00"])
def test_empty_inputs(text):
    result = preprocess_text(text)
    assert result.original_text == text
    assert result.normalized_text == ""
    assert result.tokens == ()
    assert result.urls == ()


@pytest.mark.parametrize("text", [123, b"text", {}, [], True])
def test_invalid_types_are_rejected_without_coercion(text):
    with pytest.raises(TypeError, match="string or None"):
        preprocess_text(text)


def test_malformed_unicode_is_safe():
    assert preprocess_text("خبر\ud800جدید").normalized_text == "خبر جدید"


def test_url_extraction_and_removal_does_not_remove_adjacent_words():
    text = "خبر https://example.test/a?x=1#part، سپس www.example.test/b. پایان"
    result = preprocess_text(text)
    assert result.urls == ("https://example.test/a?x=1#part", "www.example.test/b")
    assert result.normalized_text == "خبر ، سپس . پایان"
    assert result.tokens == ("خبر", "سپس", "پایان")


def test_kept_urls_are_not_transliterated_or_treated_as_hashtags():
    url = "https://example.test/ك?name=علي#part"
    options = PreprocessingOptions(urls="keep", hashtags="remove", mentions="remove")
    result = PersianPreprocessor(options=options).process(f"خبر {url} @news #خبر")
    assert result.urls == (url,)
    assert result.normalized_text == f"خبر {url}"
    assert url in result.tokens


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("keep", "#خبر_فوری @news"),
        ("strip", "خبر_فوری news"),
        ("remove", ""),
    ],
)
def test_social_policies(policy, expected):
    options = PreprocessingOptions(hashtags=policy, mentions=policy)
    assert (
        PersianPreprocessor(options=options).process("#خبر_فوری @news").normalized_text
        == expected
    )


def test_email_is_not_mistaken_for_mention():
    assert (
        "name@example.test"
        in preprocess_text("نشانی name@example.test").normalized_text
    )


def test_stopwords_are_optional_and_do_not_change_normalized_text():
    text = "علی در قم و تهران نیست و نمی‌رود و هرگز بدون ۱۲ کتاب نخواهد رفت"
    baseline = preprocess_text(text)
    options = PreprocessingOptions(remove_stopwords=True)
    result = PersianPreprocessor(options=options).process(text)
    assert result.normalized_text == baseline.normalized_text
    assert "در" not in result.tokens and "و" not in result.tokens
    assert "در" in baseline.tokens and "و" in baseline.tokens
    for word in (
        "علی",
        "قم",
        "تهران",
        "نیست",
        "نمی‌رود",
        "هرگز",
        "بدون",
        "۱۲",
        "نخواهد",
    ):
        assert word in result.tokens


def test_custom_stopwords_cannot_remove_protected_negations_or_numbers():
    words = frozenset({"نیست", "نمی‌رود", "نخواهد", "۱۲", "نه", "عدم", "در"})
    options = PreprocessingOptions(remove_stopwords=True, stopwords=words)
    result = PersianPreprocessor(options=options).process(
        "در نه نیست نمی‌رود نخواهد ۱۲ عدم"
    )
    assert result.tokens == ("نه", "نیست", "نمی‌رود", "نخواهد", "۱۲", "عدم")


@pytest.mark.parametrize("profile", ["lexical", "semantic"])
def test_deterministic_and_idempotent_normalization(profile):
    processor = PersianPreprocessor(profile)
    text = "  خبر كاشان در ۱۴۰۵/۰۷/۱۰؛ نمی‌روم! #خبر https://example.test/1 "
    first = processor.process(text)
    assert processor.process(text) == first
    second = processor.process(first.normalized_text)
    assert second.normalized_text == first.normalized_text
    assert second.tokens == first.tokens


def test_hazm_missing_error_is_actionable(monkeypatch):
    import builtins

    from news_similarity import preprocessing

    preprocessing._hazm_tokenizer.cache_clear()
    original_import = builtins.__import__

    def without_hazm(name, *args, **kwargs):
        if name == "hazm":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_hazm)
    with pytest.raises(ValueError, match="persian"):
        PersianPreprocessor(options=PreprocessingOptions(tokenizer="hazm")).process(
            "خبر"
        )
    preprocessing._hazm_tokenizer.cache_clear()


@pytest.mark.parametrize(
    "name,value",
    [
        ("zwnj", "invalid"),
        ("unicode_form", "NFD"),
        ("urls", "extract"),
        ("tokenizer", "auto"),
        ("hashtags", "erase"),
        ("stopwords", "word"),
    ],
)
def test_invalid_options(name, value):
    with pytest.raises(ValueError):
        PreprocessingOptions(**{name: value})


def test_operations_can_be_disabled():
    options = PreprocessingOptions(
        unicode_form=None,
        normalize_arabic_letters=False,
        normalize_whitespace=False,
        remove_formatting=False,
        remove_diacritics=False,
        remove_tatweel=False,
        urls="keep",
        hashtags="keep",
        mentions="keep",
    )
    text = "  كِتابـ\tي\u202e "
    assert PersianPreprocessor(options=options).process(text).normalized_text == text


def test_original_database_record_is_unchanged(repository, item):
    repository.save_news(
        item.platform, item.channel_id, item.channel_name, None, [item]
    )
    before = repository.recent_news()[0]
    original = before.text
    result = preprocess_text(original)
    assert result.original_text == original
    assert repository.recent_news()[0].text == original
    assert repository.count_news() == 1
    news = NewsItem("telegram", "1", None, "2", "كاشان", datetime.now(UTC))
    assert preprocess_text(news.text).normalized_text == "کاشان"
    assert replace(news).text == "كاشان"
