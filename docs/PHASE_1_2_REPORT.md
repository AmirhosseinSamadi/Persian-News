# Phase 1.2 implementation and verification

Completed on 2026-10-28 (Asia/Tehran) in the existing project.

## Files

Created:

- `src/news_similarity/preprocessing.py`: immutable results and configurable profiles.
- `src/news_similarity/evaluation.py`: strict dataset loading, validation, summaries and grouped splitting.
- `src/news_similarity/data/synthetic_pairs_v1.json`: 72 explicitly synthetic labeled pairs, packaged with the application.
- `scripts/build_synthetic_dataset.py`: authored examples and deterministic rebuilding/checking.
- `tests/test_preprocessing.py`, `tests/test_preprocessing_cli.py`, `tests/test_evaluation.py`: new regression coverage.
- `docs/PREPROCESSING.md`, `docs/DATASET.md`, this report: behavior, schema, reproduction and verification details.

Modified:

- `src/news_similarity/cli.py`: added independent `preprocess` and `dataset-stats` commands; existing commands preserved.
- `pyproject.toml`: optional pinned Hazm extra, package-data inclusion, generated-build exclusions for Ruff.
- `README.md`: Phase 1.2 setup, commands, structure and scope.

SHA-256 comparisons confirmed that the Telegram collector, ORM models,
repository implementation and existing `data/news.db` match their pre-phase
contents. No database migration, source-text update or live collection occurred.

## Preprocessing

Both profiles offer Unicode and Arabic-letter normalization, whitespace and
formatting cleanup, explicit half-space handling, URL extraction/removal,
hashtag/mention policies and tokenization. Stopwords are optional. Dates, signed
numbers, time values, names and negation are preserved under the defaults.
Original input is retained separately and never replaced in storage.

`lexical` uses NFKC, removes vowel marks and URL noise, strips hashtag markers,
removes mentions and excludes punctuation-only tokens. `semantic` uses NFC and
retains vowel marks, URLs, social markers and punctuation. Stopword removal,
stemming, lemmatization and verb joining are disabled by default.

The dependency-free tokenizer is the stable default for Python 3.11+. The
optional Hazm 0.12.1 tokenizer was installed and exercised on Python 3.12.14;
its Python 3.12–3.13 restriction is declared with an environment marker. No
transformers, models or external corpora were downloaded. Backend selection is
explicit and does not depend on package availability.

## Dataset statistics

All examples are fictional; none are verified Telegram/Bale reporting.

| Split | Pairs | Positive | Negative | Event groups |
| --- | ---: | ---: | ---: | ---: |
| Development | 48 | 18 | 30 | 16 |
| Test | 24 | 9 | 15 | 8 |
| Total | 72 | 27 | 45 | 24 |

Eight categories have nine pairs each, with six development and three test
pairs per category. Categories cover paraphrases, near-identical reporting,
different events within a topic, date contrasts, number contrasts, negation,
unrelated stories and short/long versions.

Labels indicate compatible event-claims rather than broad topical similarity.
Whole annotated families are held together; event IDs and duplicate article
text cannot cross splits. The deterministic builder and committed fixture
match exactly. Canonical dataset SHA-256:

```text
b547f8ed1378217c0aa7dc91bcaff8c8b5cd71b78add91635f9b6a32bec88dfd
```

## Verification results

Runtime: Python 3.12.14. All original 80 tests remain included in the suite.

| Executed check | Result |
| --- | --- |
| `python -m pytest -q --basetemp=.tmp/phase12-release -o faulthandler_timeout=30` | **181 passed, 0 failed, 0 skipped**, 2.91 seconds |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed |
| `python -m pip check` | No broken requirements |
| Editable installation with `.[dev,persian]` | Passed |
| Dataset builder `--check` | Exact fixture match |
| New CLI commands and existing help/statistics | Passed |
| Built wheel installed into a separate local target | Passed |
| Import and dataset load from installed wheel | 72 pairs, expected canonical checksum |
| Installed-wheel preprocessing of Persian date | Passed |
| Protected module and existing database hashes | All unchanged |

The first isolated wheel-install attempt encountered sandbox temp-directory
permissions; rerunning with project-local `TEMP`/`TMP` completed successfully.
Async tests were executed outside the local-socket restriction needed for
Windows event-loop creation. Telegram interactions remained mocked. No live
Telegram collection is claimed.

Coverage includes character variants, half-spaces, malformed/empty inputs,
Unicode controls, numbers/dates/negation, URL boundaries, optional stopwords,
both tokenizer backends, determinism, database compatibility, strict schema
errors, duplicate JSON fields, contradictory labels and event/split leakage.

## Windows PowerShell

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --text 'علي در كاشان نمی‌رود؛ تاریخ ۱۴۰۵/۰۷/۱۰ است.'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --profile semantic --text 'خَبَر #خبر_فوری'
.\.venv\Scripts\python.exe -m news_similarity.cli dataset-stats
.\.venv\Scripts\python.exe scripts\build_synthetic_dataset.py --check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

For Python 3.12–3.13, install `.[dev,persian]` and add `--tokenizer hazm` to
exercise the optional backend. Without that extra, two Hazm-specific test
cases skip; all core functionality remains available.

## Limits and Phase 1.3 readiness

Ready for a future reproducible TF-IDF baseline and evaluation using the
development/test contracts. No TF-IDF, cosine similarity or embedding model
has been implemented. Future feature fitting and threshold selection should
use development groups, keeping test groups held out.

The fixture is small, partly templated, correlated within families, imbalanced
and not independently annotated. Its strict number/date/negation labels need
to remain explicit in future evaluation. Preprocessing is surface-based and
does not resolve entities, facts or all linguistic negation. URL recognition
is heuristic, and custom stopwords can discard meaningful terms if chosen
poorly. Live Telegram remains unverified because credentials are unavailable.
