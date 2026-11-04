# Final university project completion

Implementation and verification date: **2026-11-04**.

## Delivered application

The existing two-view Persian RTL Streamlit app now has an explicit
**دریافت اخبار جدید** action, a smooth circular raw-score gauge, model comparison
bars, and an interactive original-text evidence explorer. The established warm
editorial palette, local Vazirmatn, top navigation and stacked small-screen layout
are retained. No new framework or dependency was introduced.

The shared collection header is available in both views. A collapsed section
selects Telegram/Bale and requires the owner to assert exclusive dedicated-bot
use before enabling the button. Configuration comes from the explicit bot
environment file, default `.env.bot-probes`; `NEWS_UI_BOT_ENV_FILE` selects an
alternative. No credential, token, channel ID, message content or raw API exception
is stored in UI collection reports or logged by the UI adapter.

Each selected provider runs sequentially through its existing collector and
`BotCollectionService`, with the existing per-bot OS lock, preflight authorization,
webhook refusal, transactional persistence and blocked-event policy. Bounds are
30 updates, 5-second polling and a 30-second provider budget. The adapter always
passes `acknowledge_stored=False`; it has no acknowledgement parameter or control.
Fetching never advances an offset, clears a queue, or alters webhook settings.

Progress identifies the current provider. Sanitized summaries show received,
inserted, duplicate and blocked counts, no-update states, and fixed error guidance.
Each provider fails independently. Selectors and archive queries read fresh SQLite
data after the button run; valid existing selections/results remain available.
Ordinary widget reruns and navigation cannot trigger collection.

The score ring displays the actual combined ranking value to four decimals on
its existing 0–1 scale, without a probability percentage. Its sweep respects
reduced-motion settings. Uncertain decisions receive neutral slate styling.
Actual policy/model identifiers and development-selected boundaries are shown
when metadata supplies them. Boundaries are rounded for presentation, with exact
values in model details. Evidence requirements still govern event decisions.

Four horizontal bars show actual word/character TF-IDF, MiniLM and hybrid values.
The semantic bar retains its signed -1–1 scale. Missing/invalid values are labeled
unavailable. Bars compare outputs, not causal model contributions.

The explorer offers three modes: extracted evidence, descriptive lexical overlap,
and original text. Feature-type filters and an optional insufficient-information
toggle control extracted highlights. Every model-evidence span must match exact
original text offsets before display. Shared, possible, explicitly conflicting,
and insufficient findings have different colors and labels. Overlapping spans are
split safely; all article text is HTML-escaped and preserved. Existing structured
evidence cards retain normalized values and original evidence clauses.

When aligned evidence spans are unavailable, lexical overlap is the initial view.
It uses the existing character/digit normalization with raw-offset mapping and
literal shared tokens of at least three characters, or numeric tokens. It is
explicitly labeled descriptive: it is neither attention/attribution nor an
explanation of the model decision. It never changes scores or event rules.

## Changed files

All paths are relative to the project root.

| File | Purpose |
| --- | --- |
| `src/news_similarity/ui/app.py` | Shared explicit collection header |
| `src/news_similarity/ui/services/ui_facade.py` | Explicit bot-env option and lazy collection adapter entry |
| `src/news_similarity/ui/services/collection.py` | New bounded non-acknowledging service adapter and sanitized report boundary |
| `src/news_similarity/ui/components/collection_panel.py` | New ownership gate, fetch action, progress and durable session summary |
| `src/news_similarity/ui/components/analysis_visuals.py` | New gauge, signed bars, validated original spans, lexical visualization and interactive explorer |
| `src/news_similarity/ui/components/score_display.py` | Integrated gauge/bars, neutral uncertainty, actual model metadata and boundaries |
| `src/news_similarity/ui/pages/comparison.py` | Interactive evidence for stored/manual comparisons; clarified action wording |
| `src/news_similarity/ui/pages/archive.py` | Collection guidance updated for shared UI action |
| `src/news_similarity/ui/theme.css` | Scoped gauge, bars, evidence/uncertainty colors and responsive styling |
| `tests/test_ui_completion.py` | Ten mocked-API and visualization regression tests |
| `README.md` | Current setup and five-minute demonstration instructions |
| `docs/FINAL_PROJECT_COMPLETION.md` | This report |

Collectors, database schema/model definitions, NLP algorithms, thresholds,
freeze files, historical reports and evaluation artifacts were not modified.

## Validation

Complete automated suite: **690 passed in 60.38 seconds**, including the existing
cached actual MiniLM test with offline mode enabled. This includes all 680 prior
tests and ten new cases. Final Ruff lint passed, Ruff formatting reported
**116 files already formatted**, and pip reported **No broken requirements found**.
SHA-256 checks confirmed all **53 protected backend and artifact files** remained
unchanged. Only the normal Bale collection checkpoint changed in production
SQLite; all four original news rows were verified unchanged by content hashes.

New tests use synthetic provider envelopes and temporary SQLite databases. They
exercise both collection services through the UI button, storage, selector refresh,
comparison with the real HybridMatcher and controlled component scores, repeated
collection, session reruns/navigation, no updates, missing configuration, API
failure sanitization, locks, webhook refusal, blocked records, no acknowledgement,
negative semantic cosine, missing scores, offset validation and HTML/text fidelity.
Existing UI tests continue to cover missing models, missing evidence, uncertainty,
empty archives and selection persistence. Mocked scores are never production data
or evaluation measurements.

The authorized live smoke test used Streamlit AppTest with the real configured
providers and cached models; it injected no mocked collection/model services:

| Check | Actual result |
| --- | --- |
| Initial stored news | 4 records |
| Telegram | BLOCKED: required bot/channel configuration absent |
| Bale | STORED: 2 updates received, 0 inserts, 2 duplicates, 0 blocked |
| API acknowledgement | None for either provider |
| Actual word TF-IDF | 0.7766881773 |
| Actual character TF-IDF | 0.5916147991 |
| Actual MiniLM cosine | 0.9068088938 |
| Actual hybrid score | 0.6704133227 |
| Actual decision | uncertain |
| Matched / conflicting / insufficient evidence groups | 0 / 0 / 7 |
| After lexical/original-mode reruns | No UI exceptions |
| Final stored news | 4; every original news row preserved |

The Bale request verified retrieval of already pending authorized updates, not
publication of fresh news during the run. The service refreshed its normal durable
collection checkpoint; no news record was overwritten. A complete new-message live
demonstration for both providers remains conditional on Telegram configuration,
new posts and reachable queue positions. Neither inserts nor live freshness are
fabricated. Mocked tests verify inserts for both providers reproducibly.

Visual browser verification was attempted using the computer-use skill, but its
safety check could not confidently determine the current browser URL and stopped
browser interaction before the app could be inspected. No new browser screenshots
or final desktop/mobile visual approval are claimed. Historical screenshots in
`FINAL_UI_REPORT.md` show the earlier UI and are not evidence for this version.

## Launch and demonstrate

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m streamlit run src/news_similarity/ui/app.py
```

Open `http://127.0.0.1:8501/`. If that port already hosts another Streamlit process,
stop that process yourself or add `--server.port 8504`. Configure tokens and numeric
channel allowlists outside Git as described in the README, stop other consumers,
confirm dedicated ownership in the UI, and fetch explicitly. Select a Telegram and
Bale record, compare, inspect model bars/evidence modes, and browse source history.

Verification commands:

```powershell
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Path .tmp -Force | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
$env:RUN_SEMANTIC_INTEGRATION = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

## Remaining limits

- Non-acknowledging reads can return the same earliest batch repeatedly. A full
  backlog may prevent inspection of newer posts. Owner-controlled queue review
  stays separate; there is no unsafe workaround or automatic offset advancement.
- Exclusive ownership must be true in practice. Local locks cannot protect against
  unrelated external bot consumers or workers using different lock directories.
- Live retrieval depends on credentials, channel authorization, platform service,
  queue retention and new posts. This session lacked Telegram configuration.
- The app remains a local university tool, without accounts, deployment controls,
  background workers or model training. Inference requires existing local models.
- Long original texts are readable in scrollable panes; the established manual/
  stored comparison input limit and encoder context window remain unchanged.
- Conservative event extraction and imperfect matching deliberately allow uncertain
  outcomes. Lexical overlap can include boilerplate and is not evidence of event
  identity. Existing development thresholds are not retuned by this UI work.
- Results/selections persist across reruns and navigation, not server restarts.
  Browser visual QA remains outstanding because the safety check stopped it.
