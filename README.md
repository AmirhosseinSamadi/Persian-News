# Persian News Similarity Detector

A university Data Mining project for collecting Persian news and comparing
stories across Telegram and Bale Messenger. The application provides
SQLite storage, bounded bot collection, Persian preprocessing, a synthetic
evaluation dataset, TF-IDF and multilingual MiniLM baselines, interpretable
event evidence comparison, and a CLI. Existing course PDFs remain outside this
project and are untouched.

## Requirements and Windows installation

Install **Python 3.11 or newer** with pip. Check the interpreter version first;
some Windows machines map `python` to an older installation. These commands use
Python 3.12 via the Windows launcher; substitute another installed version >=3.11
if needed. Run in Windows PowerShell:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
```

Using the venv's executable directly avoids PowerShell activation-policy issues.
Optional activation: `.\.venv\Scripts\Activate.ps1`. After activation, `python`
means that venv's interpreter. For runtime-only installation, `pip install -e .`
is sufficient; the `dev` extra adds pytest, pytest-asyncio and Ruff.

The checkout supplied with this implementation already has a verified `.venv`
using bundled Python 3.12. Use `.\.venv\Scripts\python.exe` directly on this
machine; recreating it requires a working Python 3.11+ installation.

## Configuration

Edit `.env` locally. Never publish it or a Telethon session file.

| Variable | Meaning / default |
| --- | --- |
| `TELEGRAM_API_ID` | Positive integer API ID; required only for collection |
| `TELEGRAM_API_HASH` | 32-character hexadecimal API hash; required only for collection |
| `TELEGRAM_SESSION_NAME` | Persistent session basename/path, default `telegram_news` |
| `DATABASE_URL` | Local SQLite URL, default `sqlite:///./data/news.db` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`; default `INFO` |

The process environment overrides `.env`; loading does not mutate the process
environment. The default `.env`, relative database paths and relative session
paths resolve against the current working directory, so run commands from this
project folder. Parent directories for the database and session are created.
Only local SQLite URLs without query options are supported. In-memory SQLite is
supported for tests; a file is necessary to retain data between CLI invocations.

Use an explicit environment file with the global option **before** the command:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli --env-file .env init-db
```

### Telegram API credentials and first-time authentication

1. Sign in with your Telegram account at [my.telegram.org](https://my.telegram.org).
2. Open **API development tools**, create an application, and obtain `api_id`
   and `api_hash`. See Telegram's [API registration instructions](https://core.telegram.org/api/obtaining_api_id).
3. Set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in `.env`.
4. Run `collect-telegram` in an interactive terminal. The first login prompts
   for your phone number (including country code), Telegram login code, and,
   when enabled, your two-step verification password. These inputs are hidden.
5. Later runs reuse `telegram_news.session` (or the configured path). Keep this
   file private: it grants access to your account. Use the same working directory
   and session name to reuse it. Do not run two collectors on the same session
   file concurrently.

Authentication **requires user interaction** unless a valid session already
exists. No login code, API hash or password is written to application logs.
This uses a user account through Telethon, not a Telegram bot token. It does not
join channels, accept invites or bypass access restrictions.

## Commands

Run local commands without Telegram credentials:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli --help
.\.venv\Scripts\python.exe -m news_similarity.cli init-db
.\.venv\Scripts\python.exe -m news_similarity.cli list-news --limit 10
.\.venv\Scripts\python.exe -m news_similarity.cli stats
```

After configuring credentials, explicitly collect from a public channel or
one your account is already authorized to read. Replace `CHANNEL_USERNAME`
with its real username:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram --channel CHANNEL_USERNAME --limit 30
.\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram --channel 'https://t.me/CHANNEL_USERNAME' --limit 30
```

Accepted references: username, `@username`, public `https://t.me/username` URL,
or a `-100...` channel peer ID. To pass a negative ID unambiguously, use
`--channel=-1001234567890`. A numeric ID can resolve only if Telethon already
knows the entity/access hash from the saved session. Invite URLs and individual
message URLs are not channel references. Private channels have no public
message URL. Channels and supergroups are accepted; users and basic groups
are rejected.

`--limit` bounds the latest **messages inspected**, including empty/service
messages, rather than promising that many text articles. Text and media
captions are preserved exactly, including Persian characters, whitespace,
punctuation and zero-width non-joiners. Media binaries are not downloaded.

Find a source's internal SQLite `id` through `stats`, then filter:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli list-news --source-id 1 --limit 10
.\.venv\Scripts\python.exe -m news_similarity.cli stats --source-id 1
```

All commands create missing database tables automatically. `init-db` is safe to
repeat. `list-news` sorts by publication time descending, then internal row ID.
The installed console entry point `news-similarity` supports the same commands.

### Collection results and failures

Collection prints a JSON summary with `channel_name`, `total_fetched`,
`valid_news_items`, `newly_inserted`, `duplicates`, `skipped`, `errors`,
`requested_limit` and `error_count`. The last two fields record the CLI's
requested message limit and the number of entries in `errors`.
Empty/unsupported messages count as skipped. Malformed message timestamps/IDs
also count as skipped and produce a message-specific error.

On a partial API failure, records fetched so far are saved and the error remains
in the summary. A persistence failure rolls back **the entire batch and its
source changes**, reports zero inserted/duplicate records and adds an error.
Therefore `newly_inserted + duplicates == valid_news_items` holds after a
successful save, but not after a database failure. Duplicates do not count as
skipped messages. Edited Telegram messages already stored under the same ID
are skipped as duplicates; their text is not overwritten.

Telethon requests are paced, and the collector waits for Telegram's reported
FloodWait delay up to 60 seconds, with at most two automatic retries for entity
resolution and two for history iteration. History resumes below the last
fetched message ID. Longer or repeated waits stop collection and return a clear
error; do not repeatedly rerun before Telegram's requested wait expires.
Authentication FloodWait errors stop and report the requested delay without
retrying authentication automatically. See [Telethon's rate-limit documentation](https://docs.telethon.dev/en/stable/concepts/errors.html).

Exit codes: `0` success, `1` collection/storage errors (including partial
failure), `2` invalid configuration/arguments, `130` Ctrl+C cancellation.
Diagnostic logs go to stderr; summaries/listings go to stdout as Unicode JSON.

## Architecture

```text
PersianNewsSimilarity/
|-- pyproject.toml
|-- .env.example
|-- .gitignore
|-- README.md
|-- src/news_similarity/
|   |-- __init__.py
|   |-- config.py
|   |-- records.py
|   |-- cli.py
|   |-- preprocessing.py
|   |-- evaluation.py
|   |-- tfidf.py
|   |-- benchmark.py
|   |-- baseline_reporting.py
|   |-- semantic.py
|   |-- semantic_evaluation.py
|   |-- semantic_reporting.py
|   |-- data/synthetic_pairs_v1.json
|   |-- data/synthetic_fresh_v1.json
|   |-- data/synthetic_fresh_v1.manifest.json
|   |-- collectors/
|   |   |-- __init__.py
|   |   |-- base.py
|   |   `-- telegram.py
|   |-- database/
|   |   |-- __init__.py
|   |   |-- models.py
|   |   `-- repository.py
|   `-- services/
|       |-- __init__.py
|       `-- collection.py
|-- tests/
|   |-- conftest.py
|   |-- test_config.py
|   |-- test_repository.py
|   |-- test_telegram_collector.py
|   |-- test_collection_service.py
|   |-- test_cli.py
|   |-- test_preprocessing.py
|   |-- test_preprocessing_cli.py
|   |-- test_evaluation.py
|   |-- test_tfidf.py
|   |-- test_benchmark.py
|   |-- test_tfidf_cli.py
|   |-- test_semantic.py
|   |-- test_semantic_evaluation.py
|   `-- test_semantic_cli.py
|-- scripts/build_synthetic_dataset.py
|-- scripts/build_fresh_semantic_dataset.py
|-- docs/PREPROCESSING.md
|-- docs/DATASET.md
|-- docs/PHASE_1_2_REPORT.md
|-- docs/PHASE_1_3A_REPORT.md
|-- docs/PHASE_1_3B_REPORT.md
|-- docs/FRESH_DATASET.md
`-- data/.gitkeep
```

`config` loads and validates environment settings. `records.py` holds the
platform-independent typed news record and collection summaries, deliberately
separate from ORM classes and Telethon. A small collector protocol defines the
service boundary. The async Telegram collector owns authentication, fetches and
conversion; the service coordinates persistence and reporting. The repository
uses short synchronous SQLAlchemy transactions after each bounded collection.
There are no database transactions held open during network requests or login.
The CLI loads configuration and assembles these components in one async loop.

### SQLite structure

| Table | Fields | Constraints |
| --- | --- | --- |
| `sources` | `id`, `platform`, `external_id`, `name`, `url`, `created_at` | Unique `(platform, external_id)` |
| `news` | `id`, `source_id`, `external_id`, `text`, `published_at`, `collected_at`, `url` | Unique `(source_id, external_id)`; FK to `sources.id` |

Stable Telegram numeric channel IDs are source external IDs; usernames/titles
can change without creating duplicate sources. Source metadata is refreshed
when a non-null name/URL is supplied. News IDs are unique within each source,
so the same message ID from two channels is retained twice. Unique constraints
and SQLite `ON CONFLICT DO NOTHING` enforce duplicate protection in the database.
Foreign keys are enabled on every connection. Publication time is indexed both
globally and within each source for recent-news queries.

All Python timestamps are aware UTC. A dedicated SQLAlchemy adapter converts
aware datetimes to UTC before storing SQLite's timezone-free datetime values
and restores `timezone.utc` on reads. Naive publication timestamps are rejected.
This avoids silently assuming the Windows local timezone. There is no migration
framework yet; `create_all` initializes missing tables, not schema upgrades.

## TF-IDF baseline (Phase 1.3A)

Fit and evaluate both classical models, then compare using their saved state:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,persian]'
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-tfidf --model both --report-path docs/PHASE_1_3A_REPORT.md
.\.venv\Scripts\python.exe -m news_similarity.cli compare --text-a 'خبر اول' --text-b 'خبر دوم'
.\.venv\Scripts\python.exe -m news_similarity.cli compare --model character --text-a 'خبر اول' --text-b 'خبر دوم'
```

`evaluate-tfidf` defaults to both methods; `--model word` or `--model character`
runs one independently. Four shuffled, seeded development group folds select
word (1,1)/(1,2) or character `char_wb` (3,5)/(4,6) n-grams and a decision
threshold using pooled out-of-fold development F1. Each fold fits vocabulary
and IDF only on its training groups. Final models fit only unique development
articles. Test news/labels are excluded from fitting and selection. Configurations
and thresholds are locked before final test scoring. The seed defaults to 42.

`artifacts/tfidf/` stores ignored local `word.model.json`, `character.model.json`,
`evaluation.json` and `report.md`. Use `--output-dir` to choose another local
artifact folder and `--model-path` to load a specific model with `compare`.
The compare command requires a previously fitted artifact and never trains on
its two input texts. Neither baseline command reads `.env` or opens SQLite.

Models use validated JSON containing vocabulary/IDF and metadata, with no
pickle/joblib deserialization. Load only locally generated artifacts. Runtime
versions and the preprocessing fingerprint must match; otherwise regenerate.
Empty/OOV vectors score zero, even for identical unseen inputs. Cosine is not
a calibrated probability, and a high score does not establish factual agreement.

Read [the measured Phase 1.3A report](docs/PHASE_1_3A_REPORT.md) for equations,
selected configurations/thresholds, development and held-out metrics, confusion
matrices, every test error ID, per-scenario analysis and exact runtime versions.
The JSON report additionally contains all per-pair scores and fold audits.

Reusable API:

```python
from news_similarity.tfidf import TfidfSimilarity

model = TfidfSimilarity.load("artifacts/tfidf/word.model.json")
score = model.compare("خبر اول", "خبر دوم")
scores = model.compare_batch([("خبر اول", "خبر دوم"), ("", "خبر سوم")])
```

For explicit training, create `TfidfSimilarity(TfidfConfig(...))` and call
`fit_development` with validated development pairs and dataset identity/checksum.
Mixed or test pairs and refitting an already fitted instance are rejected.

## Semantic baseline (Phase 1.3B)

The optional `semantic` extra installs Sentence Transformers and PyTorch.
The encoder is fixed to `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
at commit `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. It is loaded lazily,
uses local safetensors with remote code disabled, and defaults to CPU/cache-only.
Existing Hugging Face snapshots are reused. `--allow-download` explicitly permits
fetching a missing pinned snapshot into ignored `artifacts/semantic/model-cache`.

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,persian,semantic]'
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-semantic --freeze-only
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-semantic --fresh-dataset src/news_similarity/data/synthetic_fresh_v1.json --report-path docs/PHASE_1_3B_REPORT.md
.\.venv\Scripts\python.exe -m news_similarity.cli compare-semantic --text-a 'خبر اول' --text-b 'خبر دوم'
```

Keep the existing Phase 1.3A artifacts: semantic evaluation loads their fitted
vocabularies/IDFs/thresholds without retraining. `--baseline-dir` overrides their
location; `--output-dir` defaults to `artifacts/semantic`. The semantic threshold
uses only original development labels. `freeze.json` is immutable within an
artifact directory; changing the model/protocol requires a new directory.
An absent fresh dataset is reported explicitly; historical evaluation remains
exploratory because the original test set was previously inspected.

The [fresh dataset card](docs/FRESH_DATASET.md) records 32 additional synthetic
pairs in 16 new event families. It was authored after threshold freezing and
surface-screened against all original splits. Labels are same-author, not
independently human annotated. Neither comparison establishes unbiased real-news
performance. The [Phase 1.3B report](docs/PHASE_1_3B_REPORT.md) contains actual
CPU measurements, comparative metrics, confusion matrices, FPR/FNR and errors.

Both new commands operate without Telegram credentials or database writes.
`--device cpu|cuda|auto`, `--batch-size` and `--cache-folder` are configurable.
A requested unavailable CUDA device falls back to CPU and is recorded. Empty
text is rejected; raw cosine is in [-1,1], never a calibrated probability.
Without a matching saved development freeze, `compare-semantic` returns a
score with no binary prediction; it never tunes a threshold on the input pair.

Reusable API:

```python
from news_similarity.semantic import SemanticConfig, SemanticSimilarity

model = SemanticSimilarity(SemanticConfig(device="cpu"))
score = model.compare("خبر اول", "خبر دوم")
scores = model.compare_batch([("خبر اول", "خبر دوم")])
ranked = model.rank("پرسش خبری", ["گزارش اول", "گزارش دوم"], top_k=1)
```

The model caches normalized embeddings in memory with a bounded LRU, batches
uncached unique text and reads embedding dimension from model metadata. Long
inputs can be truncated at the model's recorded token limit. No fine-tuning is
performed. Optional real-model integration is separate from ordinary tests:

```powershell
$env:RUN_SEMANTIC_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q -m semantic_integration
Remove-Item Env:RUN_SEMANTIC_INTEGRATION
```

## Tests and checks

Phase 1.2 adds independent text and dataset commands, requiring no Telegram
credentials or database connection:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --text 'علي در كاشان نمی‌رود؛ تعداد ۱۲ نفر است.'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --profile semantic --text 'خبر آزمایشی با #نیم‌فاصله'
.\.venv\Scripts\python.exe -m news_similarity.cli dataset-stats
.\.venv\Scripts\python.exe scripts\build_synthetic_dataset.py --check
```

Read [the preprocessing guide](docs/PREPROCESSING.md) for options, profile
differences and safe token use. Read [the synthetic dataset card](docs/DATASET.md)
for schema, label definitions, distributions, group splits and reproduction.
All 72 dataset pairs are fictional; none are collected or verified platform news.

Optional Hazm tokenization, available on Python 3.12–3.13:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,persian]'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --tokenizer hazm --text 'نمی‌رود؛ تاریخ ۱۴۰۵/۰۷/۱۰ است.'
```

The default tokenizer needs no additional dependencies. The Hazm extra uses
local bundled dictionaries, without downloading models or NLTK corpora. On
Python 3.11 or 3.14+, use the default `builtin` tokenizer. Selecting `hazm`
explicitly requires the supported interpreter and extra; it never silently
falls back to a different tokenizer.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

Tests use temporary SQLite files and mocked Telegram interactions, with no
credentials, real sessions or network access. Coverage includes environment
validation, schema creation, database uniqueness, rollback, UTC round trips,
Persian/caption conversion, unsupported messages, inaccessible channels,
FloodWait timing/resumption, partial failures, statistics, CLI behavior,
preprocessing, protected dates/numbers/negation, dataset validation and splits,
model persistence, metrics, grouped development-only fitting and selection,
held-out invariance, batching and baseline CLI behavior.
Hazm-specific cases skip only when the optional extra is absent; install the
extra above to exercise both tokenizers.

`.gitignore` excludes `.env` variants, Telethon sessions and sidecars, virtual
environments, SQLite databases/sidecars, logs, caches and build artifacts.
`.env.example` remains trackable. Never put secrets in source files.

## Event evidence comparison (Phase 1.4A)

Compare explicit numbers and units, dates, clocks, location mentions, labeled
quoted names and negation evidence without loading a similarity model:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli compare-features --text-a 'در تهران ۱۲ نفر ثبت نام کردند.' --text-b 'در تهران ۱۴ نفر ثبت نام کردند.'
```

These examples are fictional. JSON includes original evidence spans, normalized
values, matching features, discrepancies and missing/unknown information.
Different counts, dates or places generally produce `possible_conflict`.
`confirmed_explicit_conflict` requires strictly aligned explicit claims with
a named event, full Persian-month date and zoned clock in the same clause.
It describes contradictory claims, without establishing different events or
which report is correct. No similarity percentage or event prediction is emitted.

This command needs no credentials, database, Hazm or model downloads. Python
callers can use `extract_event_features()` from `news_similarity.event_features`
or `compare_news_features()` from `news_similarity.event_comparison`, followed
by `.to_dict()`. Source texts and stored rows are preserved.
See [the Phase 1.4A report](docs/PHASE_1_4A_REPORT.md) for rules, JSON contracts,
limitations, integrity checks and reproduction commands.

## Hybrid event matching (Phase 1.4B)

The hybrid service combines the existing word/character TF-IDF and pinned
MiniLM scores with Phase 1.4A evidence. It supports pairwise comparison, batch
inference and candidate ranking. Decisions are `likely_same_event`, `uncertain`
or `likely_different_event`; ranking scores are not calibrated probabilities.
Missing or conflicting evidence can cause abstention even at high similarity.

With the previous baseline artifacts and cached semantic model available:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-hybrid --freeze-only
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-hybrid
.\.venv\Scripts\python.exe -m news_similarity.cli compare-hybrid --text-a 'در تهران ۱۲ نفر ثبت نام کردند.' --text-b 'در تهران ۱۴ نفر ثبت نام کردند.'
```

`evaluate-hybrid` selects fusion parameters only on development groups, freezes
them in `artifacts/hybrid/hybrid.freeze.json`, and writes diagnostic results
for five models to `hybrid.evaluation.json` and `hybrid.report.md` in that same
directory. Previous artifacts are read only. Both existing test sets have
already been examined; no independent evaluation is claimed. Reports account
for abstentions separately and count them as errors in primary accuracy.
The measured full engine abstained on all 56 diagnostic test pairs: coverage
and strict accuracy were zero. Its zero FPR is an abstention outcome, not an
improvement in event discrimination. Automatic real-world matching is not ready.
Comparison requires an existing freeze and never trains on the supplied text.
Use a separate `--output-dir` for a new protocol; freezes are never overwritten.

Python callers can use `HybridMatcher.compare()`, `.compare_batch()` and
`.rank(query, candidates, top_k=...)` from `news_similarity.hybrid`.
See [the Phase 1.4B report](docs/PHASE_1_4B_REPORT.md) for measured results,
configuration selection, API contracts, limits and reproduction commands.

## Persian Streamlit workspace — هم‌خبر

The Streamlit app has two Persian RTL views with visible top navigation:

- **مقایسه اخبار** selects one stored Telegram item and one stored Bale item,
  searches their original text/source names, previews the full text and stored
  metadata, and compares them only after an explicit button click. The result
  binds to the existing hybrid backend: raw score, event decision, available
  evidence, model metadata and downloadable JSON. One result section shows the
  actual decision, a single raw score, one horizontal similarity bar and compact
  shared/differing evidence columns. Model scores, thresholds, structured evidence
  and export live in the collapsed **جزئیات فنی تحلیل** expander.
  `uncertain` stays visible in a neutral treatment;
  scores are not confidence percentages. Optional manual text comparison remains
  in a collapsed section.
- **آرشیو و منابع** filters the SQLite archive by messenger/source and text,
  displays full articles, and lets an article be selected for comparison.
  The source tab reads stored collection history. Research benchmarks and
  collection instructions are secondary, collapsed details.

Warm white surfaces, navy text, restrained blue accents and locally bundled
Vazirmatn provide a responsive editorial layout. Mobile uses stacked panels
and the same two top links, without a sidebar. Fonts require no external request.

Run from the project directory in Windows PowerShell:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m pip install -e '.[dev,ui]'
# Optional when the existing cache is not found automatically:
$env:NEWS_UI_MODEL_CACHE = 'C:\Users\p Lenovo\.cache\huggingface\hub'
.\.venv\Scripts\python.exe -m streamlit run src/news_similarity/ui/app.py
```

Open [the local app](http://127.0.0.1:8501/) at its root URL, then use its top
navigation. The existing semantic extra/cache, lexical models, semantic freeze
and hybrid freeze are required for inference. Missing resources show an
informative error; the UI does not train or download models. Benchmark viewing
and archive browsing work without loading MiniLM. The UI extra is pinned to the
tested Streamlit 1.66.1 release and does not add another NLP model.

`DATABASE_URL` and `.env` select the SQLite archive. Browsing uses read-only
connections and never initializes a missing database. Only the explicit fetch
action uses the established writable collection service. Collection settings
are not editable in the UI. Viewing pages and ordinary reruns never collect,
acknowledge queues or check a messaging connection. Source status reflects stored
history, not a new live connectivity test. Optional server-side
`NEWS_UI_ARTIFACT_DIR` selects another artifact root; it defaults to `artifacts`.

### Five-minute demonstration

1. Keep Telegram's `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_CHANNEL_IDS` in `.env`;
   keep Bale's `BALE_BOT_TOKEN` and `BALE_BOT_CHAT_IDS` in `.env.bot-probes`.
   The UI reuses the CLI's bot loader, and process environment variables take
   precedence without being overwritten. The existing `NEWS_UI_BOT_ENV_FILE`
   override selects one explicit file for **both** messengers; leave it unset
   for the messenger-specific defaults. Relative file, archive and lock paths
   resolve against the repository root, independently of the launch directory.
   Missing tokens, missing channel IDs, invalid fields, and file-loading failures
   have distinct sanitized UI messages. An unreadable/malformed explicit file
   is not silently replaced with another file. Complete process-only bot
   configuration remains supported if the selected file is absent.
   Do not put credentials into UI text fields or screenshots.
2. Start the app with the PowerShell command above. Open **انتخاب پیام‌رسان و
   اجازهٔ دریافت**, choose messengers, and confirm that the dedicated bots have
   no other active consumers. The normal collectors' per-bot locks still apply.
3. Press **دریافت اخبار جدید** once. Watch progress and review each messenger's
   inserted, duplicate and blocked counts. The action inspects at most 30 updates
   per provider, with a 30-second provider budget, and **never acknowledges** them.
   Missing credentials or an API failure on one provider does not stop the other.
4. The selectors refresh in the same request. Choose one Telegram and one Bale
   record, read their complete texts, and press **مقایسه اخبار**. The frozen
   models run locally. No training, model download or automatic matching occurs.
5. Read the decision, single similarity score and compact evidence comparison.
   A high score does not override `uncertain`. Open **جزئیات فنی تحلیل** for
   secondary model scores, thresholds, complete structured evidence or JSON.
   No lexical overlap is presented as a model explanation.
   Use **آرشیو و منابع** to browse all news
   and the recorded collection status.

Repeated fetches can return old queued posts as duplicates because acknowledgements
are deliberately absent. A full first batch can hide newer updates. Queue review
and any irreversible acknowledgement remain separate owner-operated procedures;
this UI does not clear backlogs. Do not run the CLI and UI collectors concurrently.
Publish a new authorized test post only when the queue conditions allow it; the
application cannot create or promise new messages from either channel.

On 2026-11-04, a real in-app check returned two Bale duplicates, zero inserts,
and no acknowledgement. The then-selected bot file lacked Telegram settings;
the Telegram file selection has since been corrected. A real local-model
comparison of stored news returned `uncertain`. These are smoke-test outcomes,
not new-message freshness verification or model accuracy measurements.

For a separate, explicitly synthetic archive demonstration:

```powershell
.\.venv\Scripts\python.exe scripts/create_ui_demo_archive.py --output .tmp/ui-demo.db
$env:DATABASE_URL = 'sqlite:///./.tmp/ui-demo.db'
$env:NEWS_UI_DEMO_MODE = '1'
.\.venv\Scripts\python.exe -m streamlit run src/news_similarity/ui/app.py --server.port 8502
```

This opt-in helper copies 16 texts from the existing synthetic fixture into a
new database under platform `synthetic`. Sources and publication timestamps
are fictional demonstration metadata. Existing files and the normal database
are never overwritten. The UI shows a persistent synthetic-data banner.
After stopping the demo, remove those overrides with
`Remove-Item Env:DATABASE_URL, Env:NEWS_UI_DEMO_MODE` before launching the normal
app. It never populates the real archive or claims platform collection.
Synthetic-platform records can be browsed in the archive; they do not populate
the Telegram/Bale comparison selectors. Manual comparison is available for demos.

See [the UX refinement and Telegram fix report](docs/UX_REFINEMENT_TELEGRAM_FIX.md)
for current verification and limitations. The
[project completion report](docs/FINAL_PROJECT_COMPLETION.md) describes the previous
result layout. The [earlier UI report](docs/FINAL_UI_REPORT.md)
contains historical screenshots of the previous version. The
[historical Phase 1.5 report](docs/PHASE_1_5_REPORT.md) describes the earlier UI.

## Messaging feasibility probes (Phase 1.6A)

Isolated Telegram and Bale Bot API probes support a no-network default,
synthetic offline parsing and an explicitly bounded live experiment. Both
platforms currently have status **BLOCKED**: bot credentials and authorized
test IDs are unavailable. Telegram documents channel updates for member bots;
Bale's channel reception contract remains unclear. Neither platform was live
verified, and the probes are not connected to production collection or the UI.

```powershell
.\.venv\Scripts\python.exe -m news_similarity.integrations.telegram_bot_probe
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_bot_probe
.\.venv\Scripts\python.exe -m news_similarity.integrations.telegram_bot_probe --offline tests/fixtures/telegram_bot_updates.json --chat-id=-100123
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_bot_probe --offline tests/fixtures/bale_bot_updates.json --chat-id=345
```

Offline fixtures are synthetic and never establish live connectivity. Missing
configuration returns exit code 2. The optional blank credential template is
[BOT_PROBE_ENV.example](docs/BOT_PROBE_ENV.example); probes use a separate ignored
`.env.bot-probes` file. Tokens are never command arguments. Probes preserve
webhooks and update subscriptions, send no offset acknowledgements, and write
no database records. See the [Phase 1.6A feasibility report](docs/PHASE_1_6A_FEASIBILITY.md)
for official sources, permission requirements, actual observations, limitations,
controlled live commands, verification and the Phase 1.6B plan.

For repeated queued posts with successful authentication but no fresh-post
verification, see the [Telegram probe investigation](docs/TELEGRAM_PROBE_VERIFICATION_INVESTIGATION.md).
The probe inspects one batch; its JSON now explains timing exclusions and batch
limits. It still never acknowledges or advances the queue.

For a dedicated experimental **Bale** bot, the separate
[queue-management workflow](docs/BALE_QUEUE_MANAGEMENT.md) can inspect pending
updates and explicitly acknowledge a reviewed prefix. It requires a saved
inspection receipt, a signed review with individual approval of every prefix
update, the exact boundary, and irreversible-action confirmation. Recognized
zero-ID membership services stay separate from news; channel variants and
unauthorized chats require explicit acknowledgement-only review. The normal
probes remain non-acknowledging; Telegram is excluded.

The [Bale blocker investigation](docs/BALE_QUEUE_BLOCKER_INVESTIGATION.md)
explains zero-ID membership service notifications and provides an offline
`bale_queue diagnose --receipt ...` command. Queue summaries now omit chat IDs
and expose only structural diagnostics; malformed or unrecognized services remain blocked.

## One-shot Bot API collection (Phase 1.6B)

Separate Telegram and Bale collectors store authorized channel text/captions in
the existing SQLite Source/News tables. An additive checkpoint table commits
news, pending envelopes and safe offsets together. Telethon support is retained.
The default mode sends no offset acknowledgements:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram-bot --limit 30 --exclusive-test-bot
.\.venv\Scripts\python.exe -m news_similarity.cli collect-bale --limit 30 --exclusive-test-bot
.\.venv\Scripts\python.exe -m news_similarity.cli collection-status
```

Database configuration comes from `.env`; bot tokens and numeric authorized IDs
default to the existing private `.env.bot-probes`. Only a dedicated exclusively
owned bot may be used. `--acknowledge-stored` is a separate irreversible opt-in:
it confirms only a durable safe prefix. It was not executed live during this
phase. Unknown, unauthorized, service and edit events retain explicit blockers;
authorized recognized file media has a documented non-news skip outcome. No backlog
drop, daemon, automatic retry or experimental approval bypass is added.

The existing explorer displays stored text and comparison candidates. The source
page reads checkpoint history and distinguishes mocked test records from real
HTTP history; it does not perform a connection check. The owner's successful
probe results are separate from production-path verification. Production live
collection was not run in this implementation session. See the
[Phase 1.6B report](docs/PHASE_1_6B_REPORT.md) for schema, recovery, commands,
actual test results, lock limitations and the remaining service/edit policies.

## Current limitations and future phases

- Account-based Telethon history collection requires legitimate application
  credentials, account interaction and connectivity. The Bot API paths use
  separate owner-authorized bot tokens and channel lists.
- Collection is bounded and explicitly triggered. Telethon buffers a batch;
  Bot API collection uses a durable inbox/checkpoint. There is no background
  scheduler, continuous ingestion, edit synchronization, media download or
  automatic channel discovery.
- Cancelling Telethon can lose its unsaved batch. Bot recovery retains committed
  news/checkpoints; uncommitted results still depend on provider queue retention.
- Stored text can include non-news posts; editorial classification is future work.
- The small synthetic fixture is a correctness suite, not a representative
  real-news benchmark. Labels use strict event-and-fact matching.
- TF-IDF scores can miss paraphrases and confuse changes in numbers, dates,
  locations or negation. Synthetic test performance is not real-world evidence.
- Semantic proximity can also confuse factual differences. The fresh challenge
  is synthetic and has no independent annotation agreement study.
- Event evidence uses a small gazetteer and bounded patterns, without general
  entity recognition, full negation scope, calendar conversion or event coreference.
  Its categories are rule conditions, not calibrated probabilities. A hybrid
  matching quality still needs independent evaluation on untouched event groups.
- Hybrid decisions deliberately abstain when factual support is weak. A lower
  false-positive rate caused by abstention does not establish improved binary
  discrimination or real-world event matching accuracy.
- Bot collection runs through the CLI or an explicit UI action; the local app has no
  authentication, background collection, automatic matching or production
  deployment controls.

**Cross-platform readiness:** the scoring interfaces and comparative evaluation
contracts are implemented. Reliable matching still requires authorized real
texts, independently reviewed event-level labels and a new untouched test set.
Both synthetic sets have now been inspected. The owner reports successful live
Bot API probes for both platforms. New production-path storage and checkpoint
handling still need a controlled live smoke test; no real acknowledgement was
executed during implementation.
#   P e r s i a n - N e w s  
 