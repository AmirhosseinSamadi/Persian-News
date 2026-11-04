"""Strict loading and validation for explicitly synthetic evaluation pairs."""

import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from news_similarity.preprocessing import ARABIC_TO_PERSIAN

CATEGORY_LABELS = {
    "same_event_paraphrase": 1,
    "near_identical": 1,
    "same_topic_different_events": 0,
    "same_location_different_dates": 0,
    "different_numbers": 0,
    "negation_difference": 0,
    "unrelated": 0,
    "short_long": 1,
}
SPLITS = ("development", "test")


class DatasetValidationError(ValueError):
    """A dataset is malformed or contains inconsistent annotations."""


@dataclass(frozen=True)
class EvaluationPair:
    pair_id: str
    text_a: str
    text_b: str
    label: int
    category: str
    event_group_id: str
    event_id_a: str
    event_id_b: str
    split: str
    explanation: str | None = None


@dataclass(frozen=True)
class EvaluationDataset:
    name: str
    description: str
    pairs: tuple[EvaluationPair, ...]
    sha256: str
    synthetic: bool = True
    schema_version: int = 1
    language: str = "fa"

    def summary(self) -> dict[str, Any]:
        by_split = {}
        for split in SPLITS:
            pairs = [pair for pair in self.pairs if pair.split == split]
            by_split[split] = {
                "pairs": len(pairs),
                "event_groups": len({pair.event_group_id for pair in pairs}),
                "labels": dict(
                    sorted(Counter(str(pair.label) for pair in pairs).items())
                ),
                "categories": dict(
                    sorted(Counter(pair.category for pair in pairs).items())
                ),
            }
        return {
            "name": self.name,
            "schema_version": self.schema_version,
            "synthetic": self.synthetic,
            "language": self.language,
            "sha256": self.sha256,
            "total_pairs": len(self.pairs),
            "event_groups": len({pair.event_group_id for pair in self.pairs}),
            "labels": dict(
                sorted(Counter(str(pair.label) for pair in self.pairs).items())
            ),
            "categories": dict(
                sorted(Counter(pair.category for pair in self.pairs).items())
            ),
            "splits": by_split,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DatasetValidationError(message)


def _canonical_text(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).translate(ARABIC_TO_PERSIAN).split()
    )


def assign_group_splits(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stratify by category, then assign whole groups by a stable SHA-256 rank.

    Each group belongs to one category. Hold out one third of groups (at least
    one) per category. No random generator or dependence on input row order.
    """
    groups: dict[str, set[str]] = {}
    group_categories: dict[str, str] = {}
    for pair in pairs:
        category, group = pair["category"], pair["event_group_id"]
        _require(category in CATEGORY_LABELS, "Unknown split category.")
        _require(
            group_categories.setdefault(group, category) == category,
            "One event group cannot span categories in the stratified splitter.",
        )
        groups.setdefault(category, set()).add(group)
    assignments = {}
    for category, category_groups in sorted(groups.items()):
        _require(
            len(category_groups) >= 2, "Each category needs at least two event groups."
        )
        ranked = sorted(
            category_groups,
            key=lambda group: (
                hashlib.sha256(
                    f"persian-news-v1:{category}:{group}".encode()
                ).hexdigest(),
                group,
            ),
        )
        held_out = max(1, len(ranked) // 3)
        assignments.update(
            {
                group: "test" if index < held_out else "development"
                for index, group in enumerate(ranked)
            }
        )
    return [{**pair, "split": assignments[pair["event_group_id"]]} for pair in pairs]


def validate_dataset(document: object) -> EvaluationDataset:
    """Reject invalid rows and explicit leakage; never silently drop a pair."""
    _require(isinstance(document, dict), "Dataset must be a JSON object.")
    required = {
        "schema_version",
        "name",
        "description",
        "language",
        "synthetic",
        "pairs",
    }
    _require(
        set(document) == required, "Dataset metadata fields are incomplete or unknown."
    )
    _require(
        type(document["schema_version"]) is int and document["schema_version"] == 1,
        "Only schema_version 1 is supported.",
    )
    _require(
        document["synthetic"] is True,
        "Dataset must be explicitly marked synthetic=true.",
    )
    _require(document["language"] == "fa", "Dataset language must be fa.")
    for field in ("name", "description"):
        _require(
            isinstance(document[field], str) and bool(document[field].strip()),
            f"Missing or invalid metadata: {field}.",
        )
        _require(
            not any(unicodedata.category(char) == "Cs" for char in document[field]),
            f"Metadata {field} contains malformed Unicode.",
        )
    rows = document["pairs"]
    _require(
        isinstance(rows, list) and bool(rows), "pairs must be a nonempty JSON array."
    )
    pair_fields = set(EvaluationPair.__dataclass_fields__) - {"explanation"}
    identifiers: set[str] = set()
    text_pairs: dict[tuple[str, str], int] = {}
    group_splits: dict[str, str] = {}
    event_groups: dict[str, str] = {}
    text_groups: dict[str, str] = {}
    text_events: dict[str, str] = {}
    event_pairs: dict[tuple[str, str], int] = {}
    pairs = []
    for index, row in enumerate(rows):
        prefix = f"Pair at index {index}"
        _require(isinstance(row, dict), f"{prefix} must be an object.")
        _require(
            pair_fields <= set(row) <= pair_fields | {"explanation"},
            f"{prefix} has missing or unknown fields.",
        )
        for name in sorted(pair_fields - {"label"}):
            _require(
                isinstance(row[name], str) and bool(row[name].strip()),
                f"{prefix}: {name} must be a nonempty string.",
            )
            _require(
                not any(unicodedata.category(char) == "Cs" for char in row[name]),
                f"{prefix}: {name} contains malformed Unicode.",
            )
            if name in {"text_a", "text_b"}:
                _require(
                    any(char.isalnum() for char in row[name]),
                    f"{prefix}: missing text content.",
                )
            elif name in {"pair_id", "event_group_id", "event_id_a", "event_id_b"}:
                _require(
                    row[name] == row[name].strip(),
                    f"{prefix}: identifiers cannot have edge whitespace.",
                )
        explanation = row.get("explanation")
        _require(
            explanation is None
            or isinstance(explanation, str)
            and bool(explanation.strip()),
            f"{prefix}: explanation must be null or a nonempty string.",
        )
        if explanation is not None:
            _require(
                not any(unicodedata.category(char) == "Cs" for char in explanation),
                f"{prefix}: explanation contains malformed Unicode.",
            )
        pair = EvaluationPair(**row)
        _require(
            type(pair.label) is int and pair.label in {0, 1},
            f"{prefix}: invalid binary label.",
        )
        _require(pair.category in CATEGORY_LABELS, f"{prefix}: unknown category.")
        _require(
            pair.label == CATEGORY_LABELS[pair.category],
            f"{prefix}: label contradicts category.",
        )
        _require(pair.split in SPLITS, f"{prefix}: unknown split.")
        _require(
            pair.pair_id not in identifiers, f"{prefix}: duplicate pair identifier."
        )
        identifiers.add(pair.pair_id)
        _require(
            (pair.event_id_a == pair.event_id_b) == bool(pair.label),
            f"{prefix}: label contradicts event-claim IDs.",
        )
        _require(
            group_splits.setdefault(pair.event_group_id, pair.split) == pair.split,
            f"{prefix}: event group leaks across splits.",
        )
        for event_id, value in (
            (pair.event_id_a, pair.text_a),
            (pair.event_id_b, pair.text_b),
        ):
            _require(
                event_groups.setdefault(event_id, pair.event_group_id)
                == pair.event_group_id,
                f"{prefix}: event ID appears in multiple groups.",
            )
            canonical = _canonical_text(value)
            _require(
                text_groups.setdefault(canonical, pair.event_group_id)
                == pair.event_group_id,
                f"{prefix}: reused article text appears in multiple groups.",
            )
            _require(
                text_events.setdefault(canonical, event_id) == event_id,
                f"{prefix}: identical text has conflicting event-claim IDs.",
            )
        key = tuple(
            sorted((_canonical_text(pair.text_a), _canonical_text(pair.text_b)))
        )
        _require(
            key not in text_pairs,
            f"{prefix}: duplicate or contradictory unordered text pair.",
        )
        text_pairs[key] = pair.label
        event_key = tuple(sorted((pair.event_id_a, pair.event_id_b)))
        _require(
            event_pairs.setdefault(event_key, pair.label) == pair.label,
            f"{prefix}: contradictory labels for event-claim IDs.",
        )
        pairs.append(pair)
    canonical_document = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    checksum = hashlib.sha256(canonical_document.encode("utf-8")).hexdigest()
    return EvaluationDataset(
        document["name"], document["description"], tuple(pairs), checksum
    )


def _unique_json_fields(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in entries:
        _require(key not in result, "Duplicate JSON field in dataset.")
        result[key] = value
    return result


def load_dataset(path: str | Path | None = None) -> EvaluationDataset:
    try:
        if path is None:
            content = (
                files("news_similarity")
                .joinpath("data/synthetic_pairs_v1.json")
                .read_text(encoding="utf-8")
            )
        else:
            content = Path(path).read_text(encoding="utf-8")
        document = json.loads(content, object_pairs_hook=_unique_json_fields)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DatasetValidationError("Dataset cannot be read as UTF-8 JSON.") from None
    return validate_dataset(document)
