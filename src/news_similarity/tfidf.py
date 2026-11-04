"""Reusable development-only TF-IDF models with non-executable JSON persistence."""

import hashlib
import json
import math
import platform
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from news_similarity import preprocessing
from news_similarity.evaluation import EvaluationPair
from news_similarity.preprocessing import preprocess_text

ModelKind = Literal["word", "character"]
MAX_THRESHOLD = float(np.nextafter(1.0, math.inf))


def _artifact_fields(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in entries:
        if key in result:
            raise ValueError("Duplicate JSON field in model artifact.")
        result[key] = value
    return result


def runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "unicode": unicodedata.unidata_version,
        **{name: version(name) for name in ("scikit-learn", "numpy", "scipy")},
    }


def preprocessing_fingerprint() -> str:
    source = Path(preprocessing.__file__).read_text(encoding="utf-8")
    return hashlib.sha256(
        ("lexical:builtin:joined-tokens:v1\n" + source).encode()
    ).hexdigest()


def prepared_text(text: str | None) -> str:
    return " ".join(preprocess_text(text, "lexical").tokens)


@dataclass(frozen=True)
class TfidfConfig:
    kind: ModelKind = "word"
    ngram_min: int = 1
    ngram_max: int = 2
    min_df: int = 1
    sublinear_tf: bool = True

    def __post_init__(self) -> None:
        if self.kind not in {"word", "character"}:
            raise ValueError("Model kind must be word or character.")
        if (
            any(
                type(value) is not int or value < 1
                for value in (self.ngram_min, self.ngram_max, self.min_df)
            )
            or self.ngram_max < self.ngram_min
        ):
            raise ValueError(
                "N-gram bounds and min_df must be valid positive integers."
            )
        if type(self.sublinear_tf) is not bool:
            raise ValueError("sublinear_tf must be boolean.")

    def vectorizer(self, vocabulary: dict[str, int] | None = None) -> TfidfVectorizer:
        return TfidfVectorizer(
            analyzer="word" if self.kind == "word" else "char_wb",
            tokenizer=str.split if self.kind == "word" else None,
            token_pattern=None,
            lowercase=False,
            ngram_range=(self.ngram_min, self.ngram_max),
            min_df=self.min_df,
            sublinear_tf=self.sublinear_tf,
            smooth_idf=True,
            norm="l2",
            dtype=np.float64,
            vocabulary=vocabulary,
        )


class TfidfSimilarity:
    def __init__(self, config: TfidfConfig | None = None) -> None:
        self.config = config or TfidfConfig()
        self._vectorizer: TfidfVectorizer | None = None
        self.provenance: dict[str, Any] = {}
        self.threshold: float | None = None

    def _fitted(self) -> TfidfVectorizer:
        if self._vectorizer is None:
            raise ValueError("Model is not fitted. Run evaluate-tfidf first.")
        return self._vectorizer

    @property
    def features(self) -> tuple[str, ...]:
        return tuple(self._fitted().get_feature_names_out())

    @property
    def idf(self) -> tuple[float, ...]:
        return tuple(float(value) for value in self._fitted().idf_)

    def fit_development(
        self, pairs: Sequence[EvaluationPair], *, dataset_name: str, dataset_sha256: str
    ) -> "TfidfSimilarity":
        if self._vectorizer is not None:
            raise ValueError(
                "A fitted model cannot be refitted; create a new model explicitly."
            )
        if not pairs or any(pair.split != "development" for pair in pairs):
            raise ValueError(
                "Fitting accepts nonempty development pairs only; "
                "test news are forbidden."
            )
        # One normalized article is one document, regardless of pair repetition.
        corpus = sorted(
            {
                prepared_text(value)
                for pair in pairs
                for value in (pair.text_a, pair.text_b)
            }
            - {""}
        )
        if not corpus:
            raise ValueError("Development corpus has no usable text.")
        vectorizer = self.config.vectorizer()
        try:
            vectorizer.fit(corpus)
        except ValueError:
            raise ValueError(
                "Development corpus has no features under this configuration."
            ) from None
        self._vectorizer = vectorizer
        self.provenance = {
            "fit_split": "development",
            "dataset_name": dataset_name,
            "dataset_sha256": dataset_sha256,
            "document_count": len(corpus),
            "corpus_sha256": hashlib.sha256(
                json.dumps(corpus, ensure_ascii=False).encode()
            ).hexdigest(),
            "fit_pair_ids": sorted(pair.pair_id for pair in pairs),
            "fit_group_ids": sorted({pair.event_group_id for pair in pairs}),
        }
        return self

    def compare_batch(
        self, pairs: Sequence[tuple[str | None, str | None]]
    ) -> list[float]:
        vectorizer = self._fitted()
        if not pairs:
            return []
        left = vectorizer.transform([prepared_text(a) for a, _ in pairs])
        right = vectorizer.transform([prepared_text(b) for _, b in pairs])
        # L2-normalized row dot products equal cosine similarity. A zero/OOV
        # row has dot product zero, including when both inputs are empty.
        scores = np.asarray(left.multiply(right).sum(axis=1)).ravel()
        return np.clip(scores, 0.0, 1.0).tolist()

    def compare(self, text_a: str | None, text_b: str | None) -> float:
        return self.compare_batch([(text_a, text_b)])[0]

    def save(self, path: str | Path) -> None:
        vectorizer = self._fitted()
        document = {
            "schema_version": 1,
            "format": "persian-news-tfidf-json",
            "configuration": asdict(self.config),
            "runtime": runtime_versions(),
            "preprocessing_fingerprint": preprocessing_fingerprint(),
            "provenance": self.provenance,
            "threshold": self.threshold,
            "features": list(self.features),
            "idf": vectorizer.idf_.tolist(),
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "TfidfSimilarity":
        """Load locally generated JSON only; no pickle/joblib or executable code."""
        source = Path(path)
        if not source.is_file():
            raise ValueError("Fitted model file is missing. Run evaluate-tfidf first.")
        if source.stat().st_size > 50_000_000:
            raise ValueError("Model artifact exceeds the supported size limit.")
        try:
            document = json.loads(
                source.read_text(encoding="utf-8"), object_pairs_hook=_artifact_fields
            )
            if (
                type(document["schema_version"]) is not int
                or document["schema_version"] != 1
                or document["format"] != "persian-news-tfidf-json"
            ):
                raise ValueError("Unsupported model artifact format.")
            if document["preprocessing_fingerprint"] != preprocessing_fingerprint():
                raise ValueError("Model preprocessing differs; regenerate the model.")
            current = runtime_versions()
            if any(
                document["runtime"][key] != current[key]
                for key in ("scikit-learn", "numpy", "scipy", "unicode")
            ):
                raise ValueError(
                    "Model runtime versions differ; regenerate in this environment."
                )
            config = TfidfConfig(**document["configuration"])
            features, weights = document["features"], document["idf"]
            if (
                not isinstance(features, list)
                or not features
                or any(not isinstance(term, str) or not term for term in features)
            ):
                raise ValueError("Invalid model feature vocabulary.")
            if (
                len(set(features)) != len(features)
                or not isinstance(weights, list)
                or len(weights) != len(features)
            ):
                raise ValueError("Model feature/IDF dimensions are inconsistent.")
            if any(
                type(value) not in (int, float) or not math.isfinite(value) or value < 1
                for value in weights
            ):
                raise ValueError("Model IDF values must be finite and at least one.")
            threshold = document["threshold"]
            if threshold is not None and (
                type(threshold) not in (int, float)
                or not math.isfinite(threshold)
                or not 0 <= threshold <= MAX_THRESHOLD
            ):
                raise ValueError("Invalid saved threshold.")
            provenance = document["provenance"]
            if (
                not isinstance(provenance, dict)
                or provenance.get("fit_split") != "development"
            ):
                raise ValueError(
                    "Model must record development-only fitting provenance."
                )
            if (
                not isinstance(provenance.get("dataset_name"), str)
                or not provenance["dataset_name"]
            ):
                raise ValueError("Model must identify its fitting dataset.")
            if any(
                not isinstance(provenance.get(key), str)
                or not re.fullmatch(r"[a-f0-9]{64}", provenance[key])
                for key in ("dataset_sha256", "corpus_sha256")
            ):
                raise ValueError("Model fitting checksums are invalid.")
            if (
                type(provenance.get("document_count")) is not int
                or provenance["document_count"] < 1
            ):
                raise ValueError("Model fitting document count is invalid.")
            for key in ("fit_pair_ids", "fit_group_ids"):
                values = provenance.get(key)
                if (
                    not isinstance(values, list)
                    or not values
                    or any(not isinstance(value, str) or not value for value in values)
                    or len(set(values)) != len(values)
                ):
                    raise ValueError("Model fitting pair/group IDs are invalid.")
            model = cls(config)
            vocabulary = {term: index for index, term in enumerate(features)}
            vectorizer = config.vectorizer(vocabulary)
            vectorizer.vocabulary_ = vocabulary
            vectorizer.fixed_vocabulary_ = True
            vectorizer.idf_ = np.asarray(weights, dtype=np.float64)
            model._vectorizer = vectorizer
            model.provenance = provenance
            model.threshold = threshold
            return model
        except (KeyError, TypeError, json.JSONDecodeError, UnicodeError):
            raise ValueError(
                "Malformed TF-IDF JSON artifact; use a locally generated model."
            ) from None
