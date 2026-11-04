# هم‌خبر — Final UI implementation report

Date: 2026-10-31. Scope: the Streamlit interface and its read-only UI adapter.

## Implemented experience

Two top-level views replace the earlier four-page navigation. Native page links
remain visible at desktop and mobile widths; Streamlit's automatic mobile sidebar
fallback is avoided. No permanent sidebar or new frontend framework is used.

**مقایسه اخبار** is the default. Telegram and Bale each have a searchable SQLite
selector, original full-text preview, stored source and UTC publication time.
Telegram is on the right on desktop; panels stack on mobile. Only the explicit
compare button invokes the existing hybrid model. The selected pair and its
result survive navigation and reruns. Changing the pair/search invalidates the
previous result. Identical IDs, wrong platforms and missing records are rejected.

The result shows actual raw scores, the backend's event decision, extracted
evidence when present, and actual model metadata in a secondary expander. Missing
scores/metadata are identified explicitly. No percentages, confidence estimates,
illustrations, source URLs or shared-word explanations are invented. JSON export
uses the actual comparison output. Manual text comparison remains optional.

**آرشیو و منابع** provides platform/source filters, literal text/source-name
search, pagination, full original text, and an action to select a stored article
for comparison. The source tab reuses durable collection history. Benchmark
results and CLI collection guidance are secondary. No collection or queue
acknowledgement action is executed by page loading or navigation.

Typography uses bundled Vazirmatn regular/bold WOFF2 files with Tahoma/sans-serif
fallbacks. Warm white, navy, restrained blue, consistent bordered panels and
native controls implement the requested editorial direction. CSS uses named
application containers, semantic elements and a main-layout test ID; it does not
depend on generated Streamlit class names.

## Changed files

Paths below are relative to the project root.

| File | Change |
| --- | --- |
| `src/news_similarity/ui/app.py` | Two-view routing, shared Persian brand, persistent top page links and footer |
| `src/news_similarity/ui/theme.css` | New scoped RTL styling, responsive layout and local font declarations |
| `src/news_similarity/ui/components/stored_selection.py` | New native selectors, full previews and durable selection state |
| `src/news_similarity/ui/components/score_display.py` | Raw score/decision presentation and missing-output states |
| `src/news_similarity/ui/components/evidence_panel.py` | Shared evidence/differences cards with original evidence spans |
| `src/news_similarity/ui/pages/comparison.py` | Stored cross-platform comparison; retained optional manual comparison |
| `src/news_similarity/ui/pages/archive.py` | New archive/source view, filters, pagination and article selection |
| `src/news_similarity/ui/pages/sources.py` | Supports embedded source-status rendering |
| `src/news_similarity/ui/pages/insights.py` | Supports secondary embedded benchmark rendering |
| `src/news_similarity/ui/services/ui_facade.py` | Read-only filtered SQLite selection and guarded stored-pair comparison |
| `src/news_similarity/ui/static/fonts/Vazirmatn-Regular.woff2` | Bundled regular font |
| `src/news_similarity/ui/static/fonts/Vazirmatn-Bold.woff2` | Bundled bold font |
| `src/news_similarity/ui/static/fonts/OFL.txt` | Font license |
| `.streamlit/config.toml` | Light palette and local static asset serving |
| `pyproject.toml` | Includes UI stylesheet/font assets in package data; dependencies unchanged |
| `tests/test_ui_redesign.py` | Eleven focused UI/adapter regression cases |
| `tests/test_ui_app.py` | Updates existing UI tests to two-view routing and distinct compare buttons |
| `tests/test_bot_collection.py` | Existing collection/UI integration test navigates to the new archive route |
| `README.md` | Current UI workflow and launch documentation |
| `docs/FINAL_UI_REPORT.md` | This implementation and verification report |
| `docs/images/final-ui-*.jpg` | Desktop/mobile browser screenshots listed below |

The bundled font is Vazirmatn v33.003 from the
[official font repository](https://github.com/rastikerdar/vazirmatn/tree/master/fonts/webfonts),
distributed under the included SIL Open Font License. Runtime font loading is
local through Streamlit's static serving; there is no font CDN dependency.

## Verification

Final complete suite: **680 passed in 50.37 seconds**, including the existing
actual cached MiniLM integration test with offline mode enabled. No test skipped
in that run. Ruff lint passed; Ruff formatting reported **111 files already
formatted**; dependency validation reported **No broken requirements found**.
The original 669-test suite remains covered, with eleven additional regressions.

New regression coverage includes empty/missing databases, stored news selection,
cross-platform restrictions, real HybridMatcher result binding with controlled
test scorers, uncertainty, missing metadata/URLs/scores, SQL literal wildcard
escaping, no inference or SQLite mutation on load, archive-to-comparison
selection, navigation/session persistence, and duplicate-record prevention.
Test data is synthetic and temporary. Controlled scores in tests are not model
accuracy claims or production display values.

Browser review used the actual local archive at **1440 × 1050** and **390 × 844**.
It checked navigation, stacked mobile panels, text wrapping, local font loading,
and horizontal overflow (none at the checked widths). An explicit comparison of
two stored items ran the existing cached models and returned raw combined score
**0.6704**, decision **uncertain**, and no matching/conflicting evidence. The UI
displayed those actual values without upgrading the decision. This is a binding
smoke test, not an evaluation of model quality or verification of news origin.

Screenshots:

- [Desktop comparison](images/final-ui-comparison-desktop.jpg)
- [Desktop actual result](images/final-ui-result-desktop.jpg)
- [Desktop archive](images/final-ui-archive-desktop.jpg)
- [Desktop source status](images/final-ui-sources-desktop.jpg)
- [Mobile comparison](images/final-ui-comparison-mobile.jpg)
- [Mobile archive](images/final-ui-archive-mobile.jpg)

SHA-256 comparison of 54 protected files against the pre-change snapshot verified no changes to
production `data/news.db`, collectors, messaging integrations, persistence,
preprocessing, similarity algorithms, thresholds/freezes, datasets or existing
evaluation artifacts. No API acknowledgement or collection was performed.

## Reproduction in Windows PowerShell

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m streamlit run src/news_similarity/ui/app.py
```

Open `http://127.0.0.1:8501/`. Run from the project root so `.streamlit/config.toml`
and the existing `.env` apply. If needed, install the existing optional UI extra
with `.\.venv\Scripts\python.exe -m pip install -e '.[dev,ui]'`. Inference requires
the established frozen artifacts and cached MiniLM resources; browsing does not.

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

The cached-model opt-in requires the already installed semantic extra and local
model cache. Existing HTTP fixture tests also require permission to bind local
loopback sockets. Initial restricted-environment test attempts hit temporary
directory/access restrictions; the final complete run passed with the necessary
local access and an explicit workspace temporary directory.

## Remaining limitations

- No visual mockup image was available in the supplied attachments, so the
  implementation follows the written layout/palette specification; exact mockup
  fidelity could not be assessed.
- Model behavior and thresholds are unchanged. Uncertain results remain common;
  high textual similarity does not establish the same event or news truth.
- Comparison selectors show up to 100 search matches per messenger (plus a
  previously selected older article). Search runs across the archive; archive
  browsing paginates 20 items. Search is literal, not semantic or Persian-normalized.
- Full text is scrollable. The established 30,000-character inference limit still
  applies. UTC dates are displayed without inventing missing dates or converting
  an unspecified calendar. Native technical model metadata remains unmodified.
- Source status reflects saved collection runs, not current connection health.
  Collection stays in the established CLI; the UI has no acknowledgement control.
- Session state survives reruns and in-app navigation, not a server restart or a
  new browser session. Synthetic demo archives remain clearly separated and do
  not populate Telegram/Bale selectors.
- Browser checks cover two representative viewport sizes, not every device or
  browser. Legacy page modules remain available internally but only the two
  requested views are registered in the application navigation.
