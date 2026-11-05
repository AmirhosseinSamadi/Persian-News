"""True unigram frequency vectors and explicit cosine on known small examples."""

import pytest

from news_similarity.bow import BagOfWordsSimilarity


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("باران تهران", "باران تهران", 1.0),
        ("باران تهران", "باران شیراز", 0.5),
        ("باران تهران", "فوتبال تبریز", 0.0),
        ("باران باران تهران", "باران تهران تهران", 0.8),
        ("", "باران", 0.0),
        (None, None, 0.0),
        ("؟ !", "...", 0.0),
    ],
)
def test_count_cosine_examples(first, second, expected):
    assert BagOfWordsSimilarity().compare(first, second) == pytest.approx(expected)


def test_raw_counts_are_not_binary_or_tfidf_and_calls_are_independent():
    model = BagOfWordsSimilarity()
    result = model.analyze("باران باران تهران", "باران تهران تهران")
    assert result.vocabulary == ("باران", "تهران")
    assert result.counts_a == (2, 1) and result.counts_b == (1, 2)
    model.compare("خبر جدید", "خبر تازه")
    assert model.analyze("باران باران تهران", "باران تهران تهران") == result
    assert result.to_dict()["method"] == "bow_cosine"


def test_existing_persian_normalization_is_reused_without_changing_original():
    original = "كيش خبر"
    model = BagOfWordsSimilarity()
    assert model.compare(original, "کیش خبر") == pytest.approx(1.0)
    assert original == "كيش خبر"
    with pytest.raises(TypeError):
        model.compare(42, "خبر")
