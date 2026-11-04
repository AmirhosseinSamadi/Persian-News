"""Interpretable score fusion with conservative, abstaining event decisions."""

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Protocol

from news_similarity.event_comparison import EventComparison, compare_news_features
from news_similarity.semantic import SemanticModelError, SemanticSimilarity
from news_similarity.tfidf import MAX_THRESHOLD

POLICY_VERSION = "hybrid-event-v1"


class HybridModelError(RuntimeError):
    """A component failed; scores must not be fabricated or silently substituted."""


def policy_fingerprint() -> str:
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in (
        "hybrid.py",
        "event_features.py",
        "event_comparison.py",
        "preprocessing.py",
    ):
        digest.update(name.encode())
        digest.update((root / name).read_text(encoding="utf-8").encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class HybridConfig:
    semantic_weight: float = 0.5
    word_weight: float = 0.5
    confirmed_penalty: float = 0.35
    same_threshold: float = 0.75
    different_threshold: float = 0.375

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            upper = MAX_THRESHOLD if name.endswith("threshold") else 1.0
            if (
                type(value) not in (float, int)
                or not math.isfinite(value)
                or not 0 <= value <= upper
            ):
                raise ValueError(f"{name} must be a finite number in [0, {upper}].")
        if self.different_threshold >= self.same_threshold:
            raise ValueError("different_threshold must be below same_threshold.")

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_version": POLICY_VERSION,
                    "configuration": asdict(self),
                },
                allow_nan=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "HybridConfig":
        document = read_json(path)
        if (
            type(document.get("schema_version")) is not int
            or document.get("schema_version") != 1
            or document.get("policy_version") != POLICY_VERSION
        ):
            raise ValueError("Unsupported hybrid configuration format.")
        try:
            return cls(**document["configuration"])
        except (KeyError, TypeError):
            raise ValueError("Malformed hybrid configuration.") from None


def read_json(path: str | Path) -> dict[str, Any]:
    def unique(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError("Duplicate hybrid JSON field.")
            result[key] = value
        return result

    try:
        document = json.loads(
            Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique
        )
        if not isinstance(document, dict):
            raise ValueError("Hybrid JSON must be an object.")
        return document
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("Malformed hybrid JSON.") from None


def fused_score(
    word: float, character: float, semantic: float, config: HybridConfig
) -> tuple[float, float]:
    for score, lower in ((word, 0), (character, 0), (semantic, -1)):
        if (
            type(score) not in (float, int)
            or not math.isfinite(score)
            or not lower <= score <= 1
        ):
            raise ValueError("Invalid component cosine score.")
    lexical = config.word_weight * word + (1 - config.word_weight) * character
    # Negative semantic cosine supplies no positive ranking support. The raw
    # cosine is retained in the public result, not transformed to a probability.
    combined = (
        config.semantic_weight * max(0, semantic)
        + (1 - config.semantic_weight) * lexical
    )
    return lexical, combined


def relevant_contradictions(evidence: EventComparison):
    return tuple(
        finding
        for finding in evidence.conflicting_features
        if finding.confidence == "confirmed_explicit_conflict"
        and finding.feature_type in {"number", "assertion"}
        and finding.values_a
        and finding.values_b
        and finding.evidence_a
        and finding.evidence_b
        and not any(
            item["qualifiers"] for item in (*finding.evidence_a, *finding.evidence_b)
        )
    )


def _anchor_type(finding) -> str | None:
    kind = finding.feature_type
    if kind not in {"entity", "location", "date", "time"}:
        return None
    if any(item["qualifiers"] for item in (*finding.evidence_a, *finding.evidence_b)):
        return None
    values = (*finding.values_a, *finding.values_b)
    if kind == "date" and any(value.get("year") is None for value in values):
        return None
    if kind == "time" and any(value.get("timezone") is None for value in values):
        return None
    return kind


def event_decision(
    score: float,
    lexical: float,
    semantic: float,
    evidence: EventComparison,
    config: HybridConfig,
    *,
    use_event_evidence: bool = True,
) -> tuple[str, str]:
    if not use_event_evidence:
        if score > 0 and score >= config.same_threshold:
            return (
                "likely_same_event",
                "Score-only ablation exceeds the positive threshold; "
                "factual evidence is disabled.",
            )
        if score <= config.different_threshold:
            return (
                "likely_different_event",
                "Score-only ablation is below the lower threshold; "
                "factual evidence is disabled.",
            )
        return (
            "uncertain",
            "Score lies between the two development-selected boundaries.",
        )
    if relevant_contradictions(evidence):
        return (
            "uncertain",
            "Explicit anchored claims contradict. They may concern the same "
            "event or a correction; the ranking is penalized without "
            "inferring separate events.",
        )
    distinct_anchors = {
        kind
        for finding in evidence.conflicting_features
        if (kind := _anchor_type(finding)) is not None
    }
    if (
        len(distinct_anchors) >= 2
        and lexical <= config.different_threshold
        and semantic <= config.different_threshold
        and score <= config.different_threshold
        and not any(_anchor_type(finding) for finding in evidence.matching_features)
    ):
        return (
            "likely_different_event",
            "Low lexical and semantic support agrees with discrepancies in at "
            "least two distinct anchor types; this is a tentative event decision.",
        )
    if evidence.conflicting_features:
        return (
            "uncertain",
            "Possible factual differences require review; dates, quantities "
            "and places alone do not prove distinct events.",
        )
    if any(
        finding.values_a or finding.values_b
        for finding in evidence.missing_or_unknown_features
    ):
        return (
            "uncertain",
            "Some observed evidence is missing or cannot be uniquely aligned; "
            "a factual decision is unsupported.",
        )
    matching_anchors = {
        kind
        for finding in evidence.matching_features
        if (kind := _anchor_type(finding)) is not None
    }
    if len(matching_anchors) >= 2 and score > 0 and score >= config.same_threshold:
        return (
            "likely_same_event",
            "High fused similarity and at least two matching contextual "
            "anchor types support the same event; this is not verification.",
        )
    return (
        "uncertain",
        "Similarity or matching event anchors are insufficient for an event decision.",
    )


@dataclass(frozen=True)
class HybridResult:
    word_similarity: float | None
    character_similarity: float | None
    lexical_similarity: float | None
    semantic_similarity: float | None
    unpenalized_score: float | None
    combined_ranking_score: float | None
    applied_penalty: float
    event_evidence: EventComparison
    conflict_warnings: tuple[dict[str, Any], ...]
    decision: str
    explanation: str
    metadata: dict[str, Any]
    score_interpretation: str = (
        "Ranking support, not a calibrated probability or percentage."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_scores(
    word: float,
    character: float,
    semantic: float,
    evidence: EventComparison,
    config: HybridConfig,
    *,
    use_event_evidence: bool = True,
    metadata: dict[str, Any] | None = None,
) -> HybridResult:
    lexical, base = fused_score(word, character, semantic, config)
    penalty = (
        config.confirmed_penalty
        if use_event_evidence and relevant_contradictions(evidence)
        else 0.0
    )
    score = max(0.0, base - penalty)  # One bounded penalty per pair, not per mention.
    decision, explanation = event_decision(
        score,
        lexical,
        semantic,
        evidence,
        config,
        use_event_evidence=use_event_evidence,
    )
    return HybridResult(
        word,
        character,
        lexical,
        semantic,
        base,
        score,
        penalty,
        evidence,
        tuple(asdict(finding) for finding in evidence.conflicting_features),
        decision,
        explanation,
        {
            "policy_version": POLICY_VERSION,
            "configuration": asdict(config),
            "event_evidence_enabled": use_event_evidence,
            "models": metadata or {},
        },
    )


class BatchScorer(Protocol):
    def compare_batch(
        self, pairs: Sequence[tuple[str | None, str | None]]
    ) -> list[float]: ...


@dataclass(frozen=True)
class RankedHybrid:
    index: int
    text: str
    result: HybridResult


class HybridMatcher:
    def __init__(
        self,
        word: BatchScorer,
        character: BatchScorer,
        semantic: BatchScorer,
        config: HybridConfig | None = None,
        *,
        model_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.word, self.character, self.semantic = word, character, semantic
        self.config = config or HybridConfig()

        def declared(scorer):
            config = getattr(scorer, "config", None)
            return {
                "type": type(scorer).__name__,
                "configuration": asdict(config) if is_dataclass(config) else None,
                "provenance": getattr(scorer, "provenance", None),
            }

        self.model_metadata = model_metadata or {
            "parameter_source": "manual_unvalidated",
            "word": declared(word),
            "character": declared(character),
            "semantic": declared(semantic),
        }

    def compare_batch(
        self, pairs: Sequence[tuple[str | None, str | None]]
    ) -> list[HybridResult]:
        evidence, active = [], []
        for index, (left, right) in enumerate(pairs):
            if any(
                value is not None and not isinstance(value, str)
                for value in (left, right)
            ):
                raise TypeError("News inputs must be strings or None.")
            evidence.append(compare_news_features(left, right))
            try:
                SemanticSimilarity.prepare(left)
                SemanticSimilarity.prepare(right)
            except ValueError:
                continue
            active.append(index)
        scores = {}
        if active:
            selected = [pairs[index] for index in active]
            try:
                components = [
                    scorer.compare_batch(selected)
                    for scorer in (self.word, self.character, self.semantic)
                ]
                if any(len(values) != len(active) for values in components):
                    raise ValueError("Component score count mismatch.")
                for index, values in zip(
                    active, zip(*components, strict=True), strict=True
                ):
                    scores[index] = assess_scores(
                        *values,
                        evidence[index],
                        self.config,
                        metadata=self.model_metadata,
                    )
            except (SemanticModelError, OSError, ValueError, RuntimeError) as error:
                raise HybridModelError(
                    f"Hybrid inference unavailable ({type(error).__name__}); "
                    "check frozen artifacts and the pinned model cache."
                ) from None
        return [
            scores[index]
            if index in scores
            else HybridResult(
                None,
                None,
                None,
                None,
                None,
                None,
                0.0,
                item,
                (),
                "uncertain",
                "At least one text is empty after existing semantic "
                "preprocessing; no scores were generated.",
                {
                    "policy_version": POLICY_VERSION,
                    "configuration": asdict(self.config),
                    "models": self.model_metadata,
                },
            )
            for index, item in enumerate(evidence)
        ]

    def compare(self, text_a: str | None, text_b: str | None) -> HybridResult:
        return self.compare_batch([(text_a, text_b)])[0]

    def rank(
        self, query: str, candidates: Sequence[str], top_k: int | None = None
    ) -> list[RankedHybrid]:
        SemanticSimilarity.prepare(query)
        if top_k is not None and (type(top_k) is not int or top_k < 1):
            raise ValueError("top_k must be a positive integer or None.")
        results = self.compare_batch([(query, text) for text in candidates])
        ranked = sorted(
            (
                RankedHybrid(index, text, result)
                for index, (text, result) in enumerate(
                    zip(candidates, results, strict=True)
                )
            ),
            key=lambda row: (
                row.result.combined_ranking_score is None,
                -(row.result.combined_ranking_score or 0),
                row.index,
            ),
        )
        return ranked if top_k is None else ranked[:top_k]
