# Synthetic Persian news evaluation dataset v1

**All 72 pairs and all described events are synthetic.** They were authored for
software testing in Phase 1.2. No example was collected from Telegram, Bale or
verified real reporting. Names, dates, locations, counts and amounts are story
ingredients; they do not establish that any event occurred.

The checked-in UTF-8 fixture is
`src/news_similarity/data/synthetic_pairs_v1.json`. It is included as package
data, so the default dataset loads from an installed wheel as well as an
editable checkout, independently of the current directory.

## Label definition

`1` means the same event-claim with compatible central facts, despite wording,
punctuation or length differences. `0` means different events or a conflicting
central date, number or asserted status, as well as unrelated stories.

This is **strict factual/event matching**, not broad topical relatedness.
Conflicting attendance counts or a positive statement versus its denial are
hard negatives even when they might describe competing reports of one broader
event. `event_id_a`/`event_id_b` therefore identify event-claims, including those
facts; `event_group_id` groups the entire family of related alternatives.
Future scoring rules must adopt this definition or explicitly re-annotate the
fixture. No inter-annotator agreement or external expert review is claimed.

## Distribution

| Partition | Pairs | Negative (`0`) | Positive (`1`) | Event groups |
| --- | ---: | ---: | ---: | ---: |
| Development | 48 | 30 | 18 | 16 |
| Test | 24 | 15 | 9 | 8 |
| Total | 72 | 45 | 27 | 24 |

| Scenario category | Label | Total | Development | Test |
| --- | ---: | ---: | ---: | ---: |
| `same_event_paraphrase` | 1 | 9 | 6 | 3 |
| `near_identical` | 1 | 9 | 6 | 3 |
| `same_topic_different_events` | 0 | 9 | 6 | 3 |
| `same_location_different_dates` | 0 | 9 | 6 | 3 |
| `different_numbers` | 0 | 9 | 6 | 3 |
| `negation_difference` | 0 | 9 | 6 | 3 |
| `unrelated` | 0 | 9 | 6 | 3 |
| `short_long` | 1 | 9 | 6 | 3 |

Short headlines appear throughout; the `short_long` category pairs compact
headlines with multi-sentence accounts of the same synthetic event. The corpus
includes Arabic/Persian spelling variants, half-spaces, Persian dates, time
values and numerical contrasts.

## Schema

The document requires `schema_version: 1`, `name`, `description`, `language: fa`,
`synthetic: true` and a nonempty `pairs` array. Every pair requires:

| Field | Meaning |
| --- | --- |
| `pair_id` | Unique synthetic pair identifier |
| `text_a`, `text_b` | Nonempty original Persian news strings |
| `label` | Integer 0 or 1 (booleans and string digits are rejected) |
| `category` | One of the eight scenario names above |
| `event_group_id` | Related family kept entirely in one split |
| `event_id_a`, `event_id_b` | Same for positive pairs, different for negative claims |
| `split` | `development` or `test` |
| `explanation` | Optional nonempty explanation or null |

The loader rejects missing/unknown fields, malformed JSON/Unicode, empty text,
invalid labels/categories/splits, duplicate IDs, reversed or repeated text
pairs, duplicate JSON object fields, contradictory event/category metadata,
and group/event/text reuse that would allow leakage. Text identity checks use
NFKC, Arabic-letter mapping and collapsed whitespace. They cannot detect every
unannotated paraphrase or independently verify a human label.

The default fixture has 72 pairs; custom datasets may be smaller, which permits
valid focused fixtures in tests. Validation never silently drops bad rows.
The CLI exits 2 with an explanation when a custom dataset is invalid.

## Reproducible generation and splits

`scripts/build_synthetic_dataset.py` contains the authored Persian stories and
explanations. It deterministically expands each of 24 families into three
pairs. No language model, random sampling, live API or network call is used
when rebuilding the authored fixture.

`assign_group_splits` groups by category and ranks group IDs by
SHA-256 of `persian-news-v1:<category>:<group>`. It holds out one third of the
groups per category, rounded down with at least one held-out group. With three
groups per scenario, two go to development and one to test. Input row order
does not affect assignment. Related stories, event-claim IDs and repeated
article text never cross partitions. Do not split individual pairs randomly.

Canonical content SHA-256 for v1:

```text
b547f8ed1378217c0aa7dc91bcaff8c8b5cd71b78add91635f9b6a32bec88dfd
```

This hashes the complete parsed document serialized with sorted keys, UTF-8,
no ASCII escaping and compact separators. Indentation and object-key order
do not affect it; pair order, annotations, text or split changes do. The builder
also checks exact fixture serialization with stable LF line endings.

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m news_similarity.cli dataset-stats
.\.venv\Scripts\python.exe -m news_similarity.cli dataset-stats --path .\src\news_similarity\data\synthetic_pairs_v1.json
.\.venv\Scripts\python.exe scripts\build_synthetic_dataset.py --check
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation.py -q
```

To intentionally regenerate the fixture from its authored source:

```powershell
.\.venv\Scripts\python.exe scripts\build_synthetic_dataset.py
```

Review text/annotation changes, checksum and partition membership together.
Changing the set of groups can change the hash-ranked partition; v1's checked-in
memberships should stay frozen for comparable experiments.

## Limits and Phase 1.3

This small, partly templated fixture is a regression/evaluation starting point,
not a representative Persian-news benchmark. Pairs within a family are
correlated, classes are imbalanced, and lexical cues may make some categories
easy. Geographic name overlap across different families is possible; the split
guarantee concerns the annotated event families, not held-out cities or topics.

Use development groups for future feature fitting, threshold selection and
error analysis. Reserve test groups for final evaluation. Do not report these
synthetic results as performance on real collected news. Add independently
reviewed, authorized real examples later, keeping provenance and event groups
explicit. Phase 1.3 can build a TF-IDF baseline using these contracts; no TF-IDF,
cosine similarity or embeddings are implemented in Phase 1.2.
