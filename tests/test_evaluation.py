import copy
import json
import runpy
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

import pytest

from news_similarity.evaluation import (
    CATEGORY_LABELS,
    DatasetValidationError,
    assign_group_splits,
    load_dataset,
    validate_dataset,
)


@pytest.fixture
def document():
    return json.loads(
        files("news_similarity")
        .joinpath("data/synthetic_pairs_v1.json")
        .read_text(encoding="utf-8")
    )


def test_packaged_dataset_distribution_and_provenance():
    dataset = load_dataset()
    summary = dataset.summary()
    assert dataset.synthetic is True
    assert summary["total_pairs"] == 72
    assert summary["labels"] == {"0": 45, "1": 27}
    assert summary["event_groups"] == 24
    assert summary["categories"] == dict.fromkeys(CATEGORY_LABELS, 9)
    assert summary["splits"]["development"]["pairs"] == 48
    assert summary["splits"]["test"]["pairs"] == 24
    assert "ساختگی" in dataset.description
    assert all("ساختگی" in pair.explanation for pair in dataset.pairs)


def test_group_event_and_article_separation():
    pairs = load_dataset().pairs
    for key in ("event_group_id", "event_id_a", "event_id_b", "text_a", "text_b"):
        development = {
            getattr(pair, key) for pair in pairs if pair.split == "development"
        }
        test = {getattr(pair, key) for pair in pairs if pair.split == "test"}
        assert development.isdisjoint(test)
    development_events = {
        event
        for pair in pairs
        if pair.split == "development"
        for event in (pair.event_id_a, pair.event_id_b)
    }
    test_events = {
        event
        for pair in pairs
        if pair.split == "test"
        for event in (pair.event_id_a, pair.event_id_b)
    }
    assert development_events.isdisjoint(test_events)


def test_builder_reproduces_fixture_and_splits_are_order_independent(document):
    builder_path = (
        Path(__file__).resolve().parents[1] / "scripts/build_synthetic_dataset.py"
    )
    builder = runpy.run_path(str(builder_path))
    assert builder["build_document"]() == document
    forward = assign_group_splits(document["pairs"])
    backward = assign_group_splits(list(reversed(document["pairs"])))
    assert {row["pair_id"]: row["split"] for row in forward} == {
        row["pair_id"]: row["split"] for row in backward
    }
    assert forward == document["pairs"]


def test_canonical_hash_is_independent_of_json_indentation(document, tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    assert load_dataset(path) == load_dataset()
    assert len(load_dataset().sha256) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("text_a", ""),
        ("text_b", " \n"),
        ("text_a", None),
        ("text_b", 12),
        ("text_a", "\u200b"),
        ("text_b", "bad\ud800text"),
        ("label", True),
        ("label", "1"),
        ("label", 2),
        ("label", 1.0),
        ("category", "unknown"),
        ("split", "training"),
        ("explanation", ""),
        ("explanation", []),
        ("event_group_id", ""),
        ("event_id_a", None),
    ],
)
def test_invalid_rows_are_rejected(document, field, value):
    document["pairs"][0][field] = value
    with pytest.raises(DatasetValidationError):
        validate_dataset(document)


@pytest.mark.parametrize("field", ["text_a", "pair_id", "split", "event_id_b"])
def test_missing_pair_fields(document, field):
    del document["pairs"][0][field]
    with pytest.raises(DatasetValidationError, match="fields"):
        validate_dataset(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", False),
        ("synthetic", "true"),
        ("schema_version", True),
        ("schema_version", 2),
        ("language", "en"),
        ("description", ""),
        ("pairs", []),
        ("pairs", {}),
    ],
)
def test_invalid_metadata(document, field, value):
    document[field] = value
    with pytest.raises(DatasetValidationError):
        validate_dataset(document)


def test_duplicate_identifier(document):
    document["pairs"][1]["pair_id"] = document["pairs"][0]["pair_id"]
    with pytest.raises(DatasetValidationError, match="duplicate pair identifier"):
        validate_dataset(document)


def test_reversed_duplicate_pair(document):
    duplicate = copy.deepcopy(document["pairs"][0])
    duplicate["pair_id"] = "new-id"
    duplicate["text_a"], duplicate["text_b"] = duplicate["text_b"], duplicate["text_a"]
    document["pairs"].append(duplicate)
    with pytest.raises(DatasetValidationError, match="unordered text pair"):
        validate_dataset(document)


def test_contradictory_event_metadata(document):
    document["pairs"][0]["event_id_b"] = "another-event"
    with pytest.raises(DatasetValidationError, match="event-claim IDs"):
        validate_dataset(document)


def test_contradictory_category_label(document):
    document["pairs"][0]["label"] = 0
    with pytest.raises(DatasetValidationError, match="category"):
        validate_dataset(document)


def test_group_leakage_rejected(document):
    document["pairs"][1]["split"] = (
        "test" if document["pairs"][0]["split"] == "development" else "development"
    )
    with pytest.raises(DatasetValidationError, match="leaks"):
        validate_dataset(document)


def test_article_leakage_under_new_event_ids_rejected(document):
    row = copy.deepcopy(document["pairs"][0])
    row.update(
        pair_id="other",
        event_group_id="other-group",
        event_id_a="other-event",
        event_id_b="other-event",
    )
    document["pairs"].append(row)
    with pytest.raises(DatasetValidationError, match="multiple groups"):
        validate_dataset(document)


def test_incomplete_unknown_and_malformed_entries(document):
    for entry in (None, [], "text"):
        altered = copy.deepcopy(document)
        altered["pairs"][0] = entry
        with pytest.raises(DatasetValidationError, match="object"):
            validate_dataset(altered)
    document["pairs"][0]["typo_field"] = True
    with pytest.raises(DatasetValidationError, match="unknown fields"):
        validate_dataset(document)


@pytest.mark.parametrize("content", ["{", "[]", "null", '{"pairs": []}'])
def test_bad_json_document(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DatasetValidationError):
        load_dataset(path)


def test_optional_explanation_and_missing_file(document, tmp_path):
    del document["pairs"][0]["explanation"]
    assert validate_dataset(document).pairs[0].explanation is None
    with pytest.raises(DatasetValidationError, match="UTF-8 JSON"):
        load_dataset(tmp_path / "missing.json")


def test_both_profiles_keep_hard_negatives_distinct():
    from news_similarity.preprocessing import preprocess_text

    for pair in load_dataset().pairs:
        if pair.category in {
            "different_numbers",
            "negation_difference",
            "same_location_different_dates",
        }:
            for profile in ("lexical", "semantic"):
                assert (
                    preprocess_text(pair.text_a, profile).tokens
                    != preprocess_text(pair.text_b, profile).tokens
                )


def test_small_valid_custom_dataset_is_supported(document):
    document["pairs"] = document["pairs"][:1]
    assert asdict(validate_dataset(document).pairs[0]) == document["pairs"][0]


def test_duplicate_json_fields_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"synthetic": true, "synthetic": false}', encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="Duplicate JSON field"):
        load_dataset(path)


@pytest.mark.parametrize("field", ["name", "description"])
def test_malformed_metadata_unicode_is_rejected(document, field):
    document[field] = "bad\ud800metadata"
    with pytest.raises(DatasetValidationError, match="Unicode"):
        validate_dataset(document)


def test_malformed_explanation_unicode_is_rejected(document):
    document["pairs"][0]["explanation"] = "bad\ud800explanation"
    with pytest.raises(DatasetValidationError, match="Unicode"):
        validate_dataset(document)


def test_negative_identical_claims_are_rejected(document):
    row = next(row for row in document["pairs"] if row["label"] == 0)
    row["text_b"] = row["text_a"]
    with pytest.raises(DatasetValidationError, match="conflicting event-claim"):
        validate_dataset(document)
