"""Compare extracted evidence, without predicting similarity or event identity."""

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from news_similarity.event_features import (
    RULES_VERSION,
    EventFeature,
    EventFeatureExtractor,
    NewsFeatures,
)

FEATURE_TYPES = (
    "number",
    "date",
    "time",
    "location",
    "entity",
    "assertion",
    "negation",
)


@dataclass(frozen=True)
class FeatureFinding:
    feature_type: str
    values_a: tuple[dict[str, str | None], ...]
    values_b: tuple[dict[str, str | None], ...]
    evidence_a: tuple[dict[str, Any], ...]
    evidence_b: tuple[dict[str, Any], ...]
    confidence: str
    explanation: str
    alignment: str


@dataclass(frozen=True)
class EventComparison:
    news_a: NewsFeatures
    news_b: NewsFeatures
    matching_features: tuple[FeatureFinding, ...]
    conflicting_features: tuple[FeatureFinding, ...]
    missing_or_unknown_features: tuple[FeatureFinding, ...]
    rules_version: str = RULES_VERSION
    event_identity: str = "undetermined"
    interpretation: str = (
        "Evidence discrepancies describe extracted claims, not event identity. "
        "Confidence categories are rule conditions, not calibrated probabilities."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(
    kind: str,
    left: list[EventFeature],
    right: list[EventFeature],
    confidence: str,
    explanation: str,
    alignment: str,
) -> FeatureFinding:
    def evidence(feature: EventFeature) -> dict[str, Any]:
        return {
            "span": asdict(feature.evidence),
            "clause": asdict(feature.clause),
            "rule": feature.rule,
            "qualifiers": feature.qualifiers,
            "extraction_status": feature.extraction_status,
        }

    return FeatureFinding(
        kind,
        tuple(feature.normalized.copy() for feature in left),
        tuple(feature.normalized.copy() for feature in right),
        tuple(evidence(feature) for feature in left),
        tuple(evidence(feature) for feature in right),
        confidence,
        explanation,
        alignment,
    )


def _key(feature: EventFeature) -> tuple[str | None, ...]:
    """Compatibility, not event coreference; roles/units must remain distinct."""
    values = feature.normalized
    kind = feature.feature_type
    if kind == "number":
        return values.get("unit"), values.get("role")
    if kind == "date":
        return (values.get("calendar"),)
    if kind == "time":
        return values.get("timezone"), values.get("precision")
    if kind == "entity":
        return values.get("entity_type"), values.get("label")
    if kind == "assertion":
        return (values.get("predicate"),)
    if kind == "location":
        return (values.get("role"),)
    return ()


def _value(feature: EventFeature) -> tuple[str | None, ...]:
    # Surface digit spelling, magnitude and equivalent unit spellings do not
    # change canonical quantity equality. Calendar/role distinctions stay in _key.
    return (*_key(feature), feature.normalized.get("value"))


def _strict_anchors(
    left: EventFeature, right: EventFeature, a: NewsFeatures, b: NewsFeatures
) -> bool:
    """Require identical explicit event name, complete calendar date and zoned clock.

    All anchors must occur inside each aligned clause, be unique per type, and
    carry no uncertainty/update/attribution cue. This deliberately has low recall.
    """
    if (
        left.context_template != right.context_template
        or left.qualifiers
        or right.qualifiers
    ):
        return False
    for target, news in ((left, a), (right, b)):
        if any(
            feature.feature_type == "negation"
            and feature.clause == target.clause
            and not (
                target.evidence.start <= feature.evidence.start
                and target.evidence.end >= feature.evidence.end
            )
            for feature in news.features
        ):
            return False
    for kind in ("entity", "date", "time"):
        anchors = []
        for target, news in ((left, a), (right, b)):
            candidates = [
                feature
                for feature in news.features
                if feature.feature_type == kind
                and feature.clause.start == target.clause.start
                and feature.clause.end == target.clause.end
            ]
            if len(candidates) != 1 or candidates[0].extraction_status != "explicit":
                return False
            feature = candidates[0]
            if kind == "entity" and feature.normalized.get("label") not in {
                "نشست",
                "جلسه",
                "رویداد",
            }:
                return False
            if kind == "date" and (
                feature.normalized.get("calendar") != "solar_hijri"
                or feature.normalized.get("year") is None
            ):
                return False
            if kind == "time" and feature.normalized.get("timezone") is None:
                return False
            if feature.qualifiers:
                return False
            anchors.append(_value(feature))
        if anchors[0] != anchors[1]:
            return False
    return True


def _discrepancy(
    left: EventFeature,
    right: EventFeature,
    a: NewsFeatures,
    b: NewsFeatures,
    alignment: str,
) -> FeatureFinding:
    kind = left.feature_type
    confidence = "possible_conflict"
    explanation = (
        "Different extracted values; reporting updates, different roles or distinct "
        "events remain possible. This does not establish different event identity."
    )
    if left.extraction_status != "explicit" or right.extraction_status != "explicit":
        confidence = "insufficient_information"
        explanation = (
            "At least one span is ambiguous; a definite value comparison "
            "is unavailable."
        )
    elif kind == "negation":
        confidence = "insufficient_information"
        explanation = (
            "Negation cues have unresolved scope and cannot establish opposite claims."
        )
    elif kind == "number" and left.normalized.get("unit") is None:
        confidence = "insufficient_information"
        explanation = (
            "Untyped numbers cannot reliably be assigned to the same measured quantity."
        )
    elif kind == "date" and any(
        feature.normalized.get("year") is None for feature in (left, right)
    ):
        confidence = "insufficient_information"
        explanation = "A year is missing; no year or temporal conflict is inferred."
    elif kind in {"number", "assertion"} and _strict_anchors(left, right, a, b):
        confidence = "confirmed_explicit_conflict"
        explanation = (
            "The same clause, explicit event name, full Persian-month date and "
            "zoned clock anchor incompatible explicit claims. This is a claim "
            "contradiction, not proof of separate events or which report is true."
        )
    elif left.qualifiers or right.qualifiers:
        explanation = (
            "Different values occur with update, uncertainty or attribution cues; "
            "they may describe evolving or differently qualified reports."
        )
    elif kind == "assertion":
        explanation = (
            "Opposite polarities of the same bounded predicate; event, subject "
            "and temporal alignment are not sufficiently established."
        )
    elif kind == "time":
        explanation = (
            "Different clock readings; timezone, scheduling changes and temporal "
            "roles must be checked before claiming an event conflict."
        )
    elif kind == "date":
        explanation = (
            "Different explicit date components; numeric calendars may be unknown "
            "and dates may describe scheduling, publication or updates."
        )
    return _finding(kind, [left], [right], confidence, explanation, alignment)


def compare_news_features(
    text_a: str | None,
    text_b: str | None,
    *,
    extractor: EventFeatureExtractor | None = None,
) -> EventComparison:
    """Align only unambiguous feature pairs; preserve unaligned alternatives."""
    extractor = extractor if extractor is not None else EventFeatureExtractor()
    a, b = extractor.extract(text_a), extractor.extract(text_b)
    matches, conflicts, unknown = [], [], []
    for kind in FEATURE_TYPES:
        left = [feature for feature in a.features if feature.feature_type == kind]
        right = [feature for feature in b.features if feature.feature_type == kind]
        if not left and not right:
            unknown.append(
                _finding(
                    kind,
                    [],
                    [],
                    "insufficient_information",
                    "No reliable evidence of this feature was extracted "
                    "from either text.",
                    "not_observed_both",
                )
            )
            continue
        # Pair only mutually unique candidates. Never zip by appearance order or
        # form a Cartesian product of several counts/dates/places in one article.
        for alignment in (
            "same_clause_template",
            "same_normalized_value",
            "unique_compatible_type",
        ):

            def eligible(
                x: EventFeature, y: EventFeature, mode: str = alignment
            ) -> bool:
                if _key(x) != _key(y):
                    return False
                if mode == "same_clause_template":
                    return x.context_template == y.context_template
                if mode == "same_normalized_value":
                    return (
                        x.extraction_status == y.extraction_status == "explicit"
                        and _value(x) == _value(y)
                    )
                return True

            candidates = [(x, y) for x in left for y in right if eligible(x, y)]
            left_degrees = Counter(id(x) for x, _ in candidates)
            right_degrees = Counter(id(y) for _, y in candidates)
            pairs = [
                (x, y)
                for x, y in candidates
                if left_degrees[id(x)] == 1 and right_degrees[id(y)] == 1
            ]
            for x, y in pairs:
                left.remove(x)
                right.remove(y)
                if (
                    _value(x) == _value(y)
                    and x.extraction_status == y.extraction_status == "explicit"
                ):
                    matches.append(
                        _finding(
                            kind,
                            [x],
                            [y],
                            "explicit_match",
                            "Shared normalized evidence only; matching features "
                            "do not establish the same event or resolved "
                            "negation scope.",
                            alignment,
                        )
                    )
                else:
                    finding = _discrepancy(x, y, a, b, alignment)
                    (
                        unknown
                        if finding.confidence == "insufficient_information"
                        else conflicts
                    ).append(finding)
        if left or right:
            explanation = (
                "Evidence occurs only on one side; absence of extraction "
                "is not a factual contradiction."
                if not left or not right
                else "Multiple or incompatible roles, units, calendars or "
                "time precisions prevent unique alignment."
            )
            unknown.append(
                _finding(
                    kind,
                    left,
                    right,
                    "insufficient_information",
                    explanation,
                    "unaligned_or_missing",
                )
            )
    return EventComparison(a, b, tuple(matches), tuple(conflicts), tuple(unknown))
