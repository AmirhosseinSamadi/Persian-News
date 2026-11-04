# Telegram configuration fix and final UX refinement

Date: 2026-11-04. Scope: configuration routing/diagnostics and Streamlit result
presentation. No model, checkpoint policy or database migration changes.

## Exact root cause

`UiConfig.bot_env_file` previously defaulted to `.env.bot-probes` for both
messengers. The collection action passed that path to `BotCollectionConfig.load`.
The actual local `.env.bot-probes` contains Bale settings but lacks Telegram's
token and authorized channel IDs. Telegram's working fields are in `.env`;
this is why CLI collection with `--bot-env-file .env` succeeded while the UI
reported a generic configuration failure. Presence was checked without displaying
or logging any credential values or channel identifiers.

There was also a launch-location defect: the UI's default root came from
`Path.cwd()`. Relative bot files could therefore select another directory, and
relative lock directories could differ from the repository-root CLI's locks.

## Configuration correction

- The UI's source-checkout repository root is derived from the existing module
  location. Explicit root injection remains available for tests.
- Default files are `.env` for Telegram and `.env.bot-probes` for Bale.
- `NEWS_UI_BOT_ENV_FILE` and the existing `UiConfig.bot_env_file` override remain
  supported. Relative overrides resolve against the repository root; absolute
  overrides are used as supplied. The global override applies to both providers.
  No automatic fallback merges credentials from a different file.
- The UI still calls the existing `BotCollectionConfig.load`, also used by CLI
  collection. There is no second credential parser or validation implementation
  in the UI. The shared loader continues using python-dotenv and `ProbeConfig`.
- Shared-loader diagnostics now use fixed `BotConfigurationError` codes:
  `file_load`, `missing_token`, `missing_channels`, `invalid_token`,
  `invalid_channels`, or `configuration`. UI messages contain no raw exception,
  token, file contents or channel values.
- UTF-8/BOM files are supported. Malformed dotenv syntax, decoding errors and
  unreadable/missing files produce a file-loading diagnostic. Complete process
  token/channel configuration remains usable without a file. Existing valid
  process variables take precedence, and loading never mutates `os.environ`.
- Existing accepted trailing separators in channel lists remain supported.
- Relative lock paths are anchored to the same repository root as archive and
  bot files, preserving the normal repository-root CLI lock identity.
- Bale's default file and valid collection behavior are retained. File/field
  diagnostics apply consistently to both messengers.

The existing ownership gate, preflight, webhook refusal, per-bot OS lock, bounded
reads, blocked-update handling and SQLite transaction service are reused. The UI
still passes `acknowledge_stored=False`; it has no acknowledgement control.

Both actual local provider configurations validated successfully after the fix,
each with one authorized channel. This was a local configuration check only:
no live API request, collection, offset acknowledgement or database write occurred.

## One coherent result

The stored and manual comparison paths now use the same result section:

1. Backend decision, a single prominent hybrid similarity score, one horizontal
   bar, and a short interpretation based only on the decision/available evidence.
2. Two compact columns for shared evidence and differences/potential conflicts.
   Values and categories come directly from backend findings. HTML is escaped.
   At most four findings per column are summarized; additional records remain
   available in technical details. Empty evidence is stated explicitly.
3. One collapsed **جزئیات فنی تحلیل** expander containing secondary component
   scores, existing metadata/thresholds, full structured evidence, source metadata
   and JSON export. The primary hybrid score is not repeated in the score table.

The gauge, component charts, lexical-overlap explorer and separate evidence cards
are no longer rendered in the comparison result. Existing helper functions used
by legacy/internal components remain compatible. The original news previews and
selection/session behavior are retained. Scope is limited to the existing UI.

Uncertain remains uncertain even with a high score. Missing/unavailable scores
show a dash and no filled bar. The scale is 0–1 and explicitly not a confidence
percentage. No decision thresholds or model weights were changed.

## Files changed

| File | Change |
| --- | --- |
| `src/news_similarity/collectors/bot_api.py` | Shared configuration loader diagnostics and safe file reading only; polling/classification/lock implementation unchanged |
| `src/news_similarity/ui/services/ui_facade.py` | Repository-root resolution and messenger-specific default bot paths |
| `src/news_similarity/ui/services/collection.py` | Existing loader routing, fixed diagnostic codes, root-anchored lock path |
| `src/news_similarity/ui/app.py` | Sanitized UI error for an unreadable main environment file |
| `src/news_similarity/ui/components/score_display.py` | Unified primary result, evidence and one technical expander |
| `src/news_similarity/ui/components/evidence_panel.py` | Compact backend-bound evidence summaries |
| `src/news_similarity/ui/pages/comparison.py` | Reuses unified result for stored/manual comparisons |
| `src/news_similarity/ui/theme.css` | Removed gauge/chart styles; compact score/bar/evidence styling |
| `tests/test_ux_refinement.py` | Nineteen configuration and result-rendering regression cases |
| `tests/test_ui_completion.py` | Updated messenger-default and result-layout expectations |
| `tests/test_ui_app.py` | Secondary score table no longer duplicates primary score |
| `tests/test_ui_redesign.py` | Secondary score table no longer duplicates primary score |
| `README.md` | Current configuration, result workflow and launch instructions |
| `docs/UX_REFINEMENT_TELEGRAM_FIX.md` | This report |

## Verification

- Focused UI/configuration checks: **73 passed in 14.44 seconds**.
- Complete suite, including the existing cached MiniLM integration test:
  **709 passed in 68.93 seconds**. All prior 690 cases remain covered, with 19
  added regression cases.
- Ruff lint: passed. Ruff formatting: **118 files already formatted**.
- Dependency validation: **No broken requirements found**.
- Read-only Streamlit smoke test with actual stored news and cached models:
  **0.6704133227, uncertain**, exactly one technical-details expander, no rendered
  gauges or evidence-mode controls, and no UI exceptions before/after rerun.
- Mocked API integration reproduces the original Telegram wrong-file failure,
  then collects both Telegram and Bale successfully through the real UI action,
  real configuration loader and existing storage service in temporary SQLite.
- Tests cover launch-directory independence, relative/absolute overrides,
  process-environment precedence/non-mutation, environment-only configuration,
  missing tokens/IDs, malformed tokens/IDs, malformed/unreadable/missing files,
  empty/unavailable results, all three decisions, negative semantic scores in
  technical output, HTML-safe evidence, no duplicate primary score, a collapsed
  technical expander and reruns that do not repeat collection.

Production SQLite, NLP files, frozen thresholds, datasets and historical
evaluation artifacts match the pre-change SHA-256 snapshot: **54 protected files
unchanged**, including the complete production database. The shared
configuration section is the only collector file change; acknowledgement,
checkpoint, parsing and collection-service logic are not changed.

Browser availability and any new screenshots are reported with the final delivery.
Historical screenshots describe prior layouts and are not evidence for this one.

## Launch and checks in Windows PowerShell

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m streamlit run src/news_similarity/ui/app.py
```

Open `http://127.0.0.1:8501/`. If that port hosts an older instance, stop it and
restart, or add an unused `--server.port` value. Start from the repository root
so Streamlit also loads its local theme/static-serving configuration.

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
```

## Remaining limits

Configuration validation does not establish present network reachability or bot
permissions. Those are checked by the existing service after an explicit fetch.
Unacknowledged backlog may still return duplicates and obscure newer posts.
Independent external consumers cannot be excluded by a local OS lock alone.
The existing models may legitimately abstain, and missing event evidence cannot
be reconstructed by the presentation layer. Browser/device visual coverage is
conditional on the available browser verification tools.
