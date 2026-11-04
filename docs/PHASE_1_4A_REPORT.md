# Phase 1.4A: Event-aware news evidence

Implemented on 2026-10-28. Rules version: `event-features-v1`.
This phase adds deterministic evidence extraction and structured comparison.
It does not implement a hybrid classifier, event identity prediction, calibrated
confidence, a similarity percentage or an accuracy benchmark.

## Scope and architecture

The existing package separates collection, persistence, preprocessing, TF-IDF,
semantic inference, evaluation and CLI operations. `News.text` stores the original
body; `NewsItem` is the shared collection record. The new module accepts strings
directly and never writes either representation. No database schema, dependency,
collector, preprocessing profile, model, threshold or previous evaluation changed.

| File | Change |
| --- | --- |
| `src/news_similarity/event_features.py` | Extraction, offset mapping and feature records |
| `src/news_similarity/event_comparison.py` | Conservative alignment, findings and comparison records |
| `src/news_similarity/cli.py` | Added `compare-features` before config/database/model operations |
| `tests/test_event_features.py` | Extraction, Unicode, dates, units and raw spans |
| `tests/test_event_comparison.py` | Evidence alignment, conflicts, updates and diagnostic regressions |
| `tests/test_event_features_cli.py` | Structured CLI, isolation and existing command preservation |
| `README.md` | Usage and current capabilities/limitations |
| `docs/PHASE_1_4A_REPORT.md` | This implementation and verification report |

## Extraction rules

An internal NFKC view translates Persian/Arabic digits to Western digits and
Arabic yeh/kaf to Persian forms. It removes Arabic vowel marks, tatweel and
unnecessary control/format characters. Half-spaces become matching spaces;
line boundaries are retained for clause segmentation. Normalization never
replaces the original text. Each normalized character maps back to its original
base/mark cluster, including compatibility expansions and combining marks.

| Feature | Supported rules | Conservative behavior |
| --- | --- | --- |
| Numbers | Signed digit values, decimal dot/Arabic decimal mark, validated thousands separators | Ambiguous comma grouping, slash notation and ranges have no inferred scalar value |
| Quantities | One `هزار`, `میلیون` or `میلیارد` multiplier plus an explicit supported unit | Repeated multipliers are ambiguous; unsupported compound units remain unresolved |
| Dates | Year-first `YYYY/MM/DD` or `YYYY-MM-DD`; day plus a Persian month name, optionally year | Numeric calendar is `unspecified`; missing year stays null; no calendar conversion |
| Clocks | `HH:MM` and `HH:MM:SS`, 24-hour structural checks | Unspecified timezone stays null; explicit UTC/GMT or `به وقت تهران` retained; offsets remain unresolved evidence |
| Locations | Small built-in place-name list with an explicit cue: `در`, `از`, `به`, `شهر`, `استان`, `شهرستان` | No geocoding, inferred city/province relations or standalone ambiguous name guesses |
| Entities | Explicit labels and paired quotes, e.g. `شرکت «پارس»`, `جلسه «سپهر»`, `دکتر "مینا نمونه"` | No inferred names, fuzzy aliases or general person/organization NER |
| Negation | Bounded cues including `نمی‌…`, `نیست`, `نبود`, `نشد`, `هرگز`, `بدون`, `عدم`, `تکذیب` | General scope stays `unknown`; `نه تنها` is ambiguous |
| Assertion polarity | Limited explicit predicates: cancellation, approval, confirmation, holding, success, closure and opening | Positive/negative polarity of the matched phrase only, without full sentence interpretation |

Canonical units are kilograms (grams and tonnes converted), meters (kilometers
converted), IRR (tomans multiplied by 10), percent, persons, watts (megawatts
converted), Celsius and minutes (hours converted). Student, professor and pupil
counts retain separate roles; generic `نفر` has no inferred role. Supported
compound units `کیلومتر بر/در ساعت` and `تن در هکتار` have distinct canonical
units. Other detected rate suffixes are left unresolved rather than reduced to
their numerator. Numeric values use decimal strings and exact decimal arithmetic,
avoiding floating-point rounding and ambient Decimal-context rounding.

Date checks reject impossible component ranges and obvious named-month day
overflow. They are **structural checks**, without Gregorian/Jalali leap-year
validation. A numeric year never determines the calendar. Relative dates,
time-of-day phrases and spelled-out quantities are not resolved.

URLs/email addresses and labeled quoted names are excluded from numeric,
temporal and negation extraction inside their spans. This avoids treating URL
paths, product names or a person named `نه` as event facts.

The built-in location list is the explicit `LOCATIONS` constant. Applications
can supply a local mapping with
`EventFeatureExtractor(locations={"شهر نمونه": "sample_city"})` and reuse it
through `compare_news_features(..., extractor=extractor)`. An empty mapping
disables location extraction. No aliases or places are fetched from a service.

## Comparison and confidence categories

Comparison operates separately on each feature type. It first tries mutually
unique clause templates (the feature span replaced by a placeholder), then
unique shared normalized values, then a unique compatible feature on each side.
Quantity roles/units, entity labels, date calendars and clock precision/timezones
must be compatible. Several unresolved candidates remain grouped as unknown;
they are never paired by article order. Matching a number or name is evidence
agreement only and cannot establish event identity.

| Category | Conditions and interpretation |
| --- | --- |
| `explicit_match` | Compatible explicit normalized evidence agrees; event identity remains unknown |
| `confirmed_explicit_conflict` | Number or bounded predicate differs under identical clause templates, with one identical explicitly quoted event name (`جلسه`, `نشست`, `رویداد`), one complete Persian-month date, and one identical zoned clock in that clause |
| `possible_conflict` | Unambiguously aligned but differing extracted values, without sufficient support for a confirmed claim contradiction |
| `insufficient_information` | Missing features, ambiguous scalar values, missing years, untyped quantities, unresolved negation scope or non-unique/incompatible alignment |

The confirmed category additionally requires no update, uncertainty, question,
conditional or attribution cue in either clause, and no negation outside the
compared predicate span. Conflicting counts or positive/negative phrases at the
same anchors are contradictory **claims**, potentially about the same event.
The rules do not determine whether the reports refer to separate events,
whether one is a correction, or which statement is true. Confidence strings
describe satisfied rule conditions; they are not estimated probabilities.

Dates, clocks, names and places can produce possible discrepancies, never
confirmed event conflicts. Count changes with `ابتدا`, `تازه`, `افزایش`, `کاهش`,
uncertainty such as `حدود`, or attribution such as `به گفته` remain possible.
Missing evidence is not evidence that a fact is absent from the real world.

## API and JSON contract

```python
from news_similarity.event_features import extract_event_features
from news_similarity.event_comparison import compare_news_features

features = extract_event_features("در تهران ۱۲ نفر ثبت نام کردند.")
result = compare_news_features(
    "در تهران ۱۲ نفر ثبت نام کردند.",
    "در تهران ۱۴ نفر ثبت نام کردند.",
)
payload = result.to_dict()  # serializable with json.dumps
```

These and all examples in this report are fictional, not platform reporting.
`None` is treated as empty text, empty/formatting-only text produces warnings,
and non-string objects raise `TypeError`. Repeated calls are deterministic.

Each extracted feature includes `feature_type`, `normalized`, `evidence`,
`clause`, `context_template`, `qualifiers`, `extraction_status` and `rule`.
Evidence records contain `start`, `end` (exclusive) and the exact original
`text`. Offsets count **Python Unicode code points**, not UTF-8 bytes or
JavaScript UTF-16 units. A future browser UI must convert offsets when astral
characters such as emoji precede a span. Original span text is also supplied.

Comparison contains `news_a`, `news_b`, `matching_features`,
`conflicting_features`, `missing_or_unknown_features`, `rules_version`,
`interpretation` and always `event_identity: "undetermined"`.
Every finding has `feature_type`, `values_a`, `values_b`, `evidence_a`,
`evidence_b`, `confidence`, `explanation` and `alignment`. Evidence includes
the span, enclosing clause, extraction rule, qualifiers and extraction status.
Unknown findings may have empty lists on one or both sides. No score is added.

## Fictional examples

| Text A / text B | Expected evidence behavior |
| --- | --- |
| `در تهران ۱۲ نفر ثبت نام کردند.` / `در تهران ۱۴ نفر ثبت نام کردند.` | Location agrees; person counts have a possible discrepancy |
| `۲٫۵ کیلومتر مسیر ساخته شد.` / `2500 متر مسیر ساخته شد.` | Canonical meter values agree |
| `نشست لغو شد.` / `نشست لغو نشد.` | Possible predicate contradiction; event/time anchors unresolved |
| `جلسه «سپهر آزمایشی» در ۱۲ آبان ۱۴۰۵ ساعت ۰۹:۴۵ UTC لغو شد.` / same clause with `لغو نشد` | Confirmed contradiction between explicitly anchored claims; event identity remains undetermined |
| `ابتدا ۸ نفر آمدند.` / `طبق آمار تازه ۱۰ نفر آمدند.` | Possible update-related discrepancy, not a different-event decision |
| `۸ نفر و ۹ نفر آمدند.` / `۱۰ نفر و ۱۱ نفر آمدند.` | Counts remain unknown because their alignment is ambiguous |
| `در تهران ۱۲ نفر آمدند.` / `خبری منتشر شد.` | Missing quantity/location evidence, without a contradiction |

## Evaluation integrity

No new classifier, threshold, labeled evaluation dataset or performance claim
was introduced. New tests use fictional rule-contract examples; they are
implementation tests, not an independent statistical evaluation.

The historical 72-pair set and previously examined fresh 32-pair set are used
only in diagnostic regressions over 104 pairs: exact span slicing, deterministic
JSON and no event verdict. No labels/categories are consulted by the feature
comparison checks. There is no rule fitting, accuracy calculation or unbiased
generalization claim from these datasets. Their existing annotations and model
evaluation artifacts remain untouched. Future evaluation must freeze these
rules and any hybrid design **before** obtaining independent event groups.

Before implementation, SHA-256 digests were recorded for 33 existing source,
dataset, evaluation/report and database files. Verification showed only the
authorized CLI source changed. All other 32 files, including both datasets,
their manifest, prior model results/freezes, previous phase reports, collection
code, database models and `data/news.db`, retained their original bytes.
This workspace is not a Git checkout; file hashes provided the integrity check.

## Verification and Windows reproduction

Final verification on the existing Windows Python 3.12.14 virtual environment:

| Check | Actual result |
| --- | --- |
| `python -m pytest -q`, with cached semantic integration enabled | **392 passed in 16.89s**, no skips or failures |
| Added Phase 1.4A tests | **113 passed**; all 279 previous tests also passed in the full run |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 53 files already formatted |
| `python -m pip check` | No broken requirements found |
| CLI subprocess smoke test | Valid JSON, possible count discrepancy, exact raw spans, event identity undetermined |
| Protected-file integrity after final tests | 32 existing files unchanged; only the authorized CLI source changed among 33 recorded files |

No verification failures remain unresolved. The final full-suite rerun succeeded
after an automatic permission-review timeout on the preceding attempt.
The rules were not evaluated as a similarity classifier. Source SHA-256 digests
for this implementation, including the current Windows file bytes:

```text
event_features.py    0f15e9192bd9e95a420e5dc06163ea72bd50c47806cbcb5f38beac0862fc1ba4
event_comparison.py  d2714c2ccc194014553f33ee3e9eb378b57f46aa20236060bf56fb1a9d6d957a
```

Run from the existing checkout in PowerShell:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null

.\.venv\Scripts\python.exe -m news_similarity.cli compare-features --text-a 'در تهران ۱۲ نفر ثبت نام کردند.' --text-b 'در تهران ۱۴ نفر ثبت نام کردند.'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

The normal suite skips the existing opt-in pretrained integration test. With
the already installed semantic extra and cached pinned MiniLM model, include it:

```powershell
$env:RUN_SEMANTIC_INTEGRATION = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:RUN_SEMANTIC_INTEGRATION
```

The feature pipeline itself uses only the standard library and existing
character-normalization constants; it requires no model files or new packages.
Windows asynchronous collector tests require the normal local socket-pair
capability. They were run outside the restricted sandbox to permit that local
operation. Tests use temporary databases/mocked Telegram interactions. Live
Telegram collection remains unverified.

## Limitations and hybrid-engine readiness

- The limited gazetteer, explicit quote requirements and narrow predicate
  patterns intentionally miss many names, places, verbal forms and paraphrases.
- Clause templates are surface alignment, not subject/object parsing, event
  coreference, full negation scope, quote attribution or fact verification.
  Qualifier detection is deliberately broad and may weaken valid findings.
- Untyped counts and unsupported units/compounds cannot reliably be assigned to
  a measurement role. Abbreviations, number words, scientific notation and
  unusual numeric punctuation need additional conservative rules.
- Numeric date calendars, relative dates, timezone offsets, equivalent clock
  precision and leap days remain unresolved. Dates/times may refer to reporting,
  publication, planning or the event itself.
- Multiple mentions without unique alignment remain unknown. A small number of
  strictly anchored claim contradictions does not establish classifier quality.

The extractor and JSON evidence contract are ready to be consumed by a future
hybrid matching engine alongside frozen TF-IDF/semantic scores. That engine
still needs an explicit update policy, event/role alignment, development-only
selection and independent event-group evaluation. This phase provides no
justification for a production similarity threshold or accuracy claim.
