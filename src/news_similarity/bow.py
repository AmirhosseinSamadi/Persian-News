"""Pair-local raw word counts and explicit cosine; independent of trained models."""

from dataclasses import asdict, dataclass

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from news_similarity.preprocessing import preprocess_text


@dataclass(frozen=True)
class BagOfWordsResult:
    cosine_similarity: float
    vocabulary: tuple[str, ...]
    counts_a: tuple[int, ...]
    counts_b: tuple[int, ...]

    def to_dict(self):
        return {"method": "bow_cosine", **asdict(self)}


class BagOfWordsSimilarity:
    """Unigram frequencies, not binary indicators or TF-IDF weights.

    Vocabulary is the union of the two preprocessed texts, rebuilt per call.
    Zero vectors have score 0 by explicit convention, including two empty texts.
    No event decision, threshold, persistent fitting or external model is used.
    """

    def analyze(self, text_a: str | None, text_b: str | None) -> BagOfWordsResult:
        for text in (text_a, text_b):
            if text is not None and not isinstance(text, str):
                raise TypeError("BoW inputs must be strings or None.")
        texts = [
            " ".join(preprocess_text(text, "lexical").tokens)
            for text in (text_a, text_b)
        ]
        if not any(texts):
            return BagOfWordsResult(0.0, (), (), ())
        vectorizer = CountVectorizer(
            tokenizer=str.split,
            token_pattern=None,
            lowercase=False,
            ngram_range=(1, 1),
            binary=False,
        )
        counts = vectorizer.fit_transform(texts)
        score = float(cosine_similarity(counts[0], counts[1])[0, 0])
        # Round-off can produce 1 + epsilon for identical nonzero vectors.
        score = float(np.clip(score, 0.0, 1.0))
        rows = counts.toarray()
        return BagOfWordsResult(
            score,
            tuple(vectorizer.get_feature_names_out().tolist()),
            tuple(int(value) for value in rows[0]),
            tuple(int(value) for value in rows[1]),
        )

    def compare(self, text_a: str | None, text_b: str | None) -> float:
        return self.analyze(text_a, text_b).cosine_similarity
