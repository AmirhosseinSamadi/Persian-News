# Phase 1.1 verification report

Date: 2026-10-28 (Asia/Tehran). Project: `PersianNewsSimilarity`.

## A. Implementation Review

Reviewed the README, `pyproject.toml`, `.env.example`, `.gitignore`,
`config.py`, `records.py`, the collector protocol and Telegram collector,
collection service, database models/repository, CLI and all existing tests.
The original 70 tests passed again before changes. The architecture was retained.

- Configuration loads the explicit `.env` path and gives process environment
  variables precedence. API ID/hash validation occurs without printing values;
  database-only commands do not require Telegram credentials.
- The async collector starts/reuses a Telethon session, resolves a configurable
  channel, requests bounded history, preserves original text/captions, and
  constructs public links from the resolved channel's username.
- Only text-bearing messages become news. Service/empty messages are skipped;
  invalid IDs/timestamps are skipped with an error. Private channels have no
  public message URL.
- Source identity is the numeric Telegram channel ID, independent of its title
  or username. Duplicate news identity is `(source_id, external_id)`.
- The service saves valid partial results after a later API failure and retains
  error details. Database failure rolls back the complete persistence batch.
- SQLite uniqueness and foreign keys enforce integrity. A datetime adapter
  converts publication/collection times to UTC and restores aware UTC values.
- Authentication prompts are local and hidden. Exception payloads are excluded
  from application error messages. Telethon's login greeting goes to stderr so
  successful collection stdout remains JSON.

Exact collection command, using the project's existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram --channel "$channel" --limit 30
```

Confirmed reporting gap: the CLI JSON omitted the requested limit and explicit
error count required by this verification task. Section E records the small fix.
No collector, repository, service or schema change was necessary based on the
executed checks. Offline evidence does not establish real Telegram compatibility.

## B. Authentication Status

Observed locally, without printing sensitive values:

| Check | Result |
| --- | --- |
| Local `.env` exists | No |
| Loaded `TELEGRAM_API_ID` configured | No |
| Loaded `TELEGRAM_API_HASH` configured | No |
| Loaded session name nonempty | Yes; default configuration |
| Configured saved session exists | No |
| Real account authentication | Not attempted; configuration missing |

Session-name loading and process-environment precedence are tested using local
temporary files. Real session creation/reuse and first-time authentication are
not verified. No fake credentials were substituted for a live request. Existing
test fixtures use synthetic values exclusively with mocked clients.

To obtain credentials, sign in at [Telegram's developer portal](https://my.telegram.org),
open **API development tools**, and create an application. Telegram supplies
the API ID and API hash there; see the [official instructions](https://core.telegram.org/api/obtaining_api_id).
Enter these values directly into the local `.env` file, never into chat.
The `.env.example` documents the fields and contains no real credentials.

The real missing-credentials CLI check exited **2**, displayed the configuration
instruction, and did not prompt for login or make a Telegram request.

Ignore rules were verified with Git against this worktree using isolated Git
metadata under ignored `.tmp/`. `.env`, `.env.local`, `.session` files and
session sidecars, local database files/sidecars, virtual environments and logs
are excluded; `.env.example` remains trackable. The project itself is not a Git
repository, so there is no project index/history to audit. No commit or upload
was performed.

## C. Real Collection Results

**Blocked before connection: API credentials and a saved session are absent.**

| Metric | Live run 1 | Live run 2 |
| --- | --- | --- |
| Intended requested limit | 30 | 30 |
| Fetch performed | Not performed | Not performed |
| Fetched messages | Not measured | Not measured |
| Valid text-based news | Not measured | Not measured |
| Newly inserted records | Not measured | Not measured |
| Duplicate records | Not measured | Not measured |
| Skipped messages | Not measured | Not measured |
| Telegram/API error count | Not measured | Not measured |

No channel was selected or contacted. Telegram network reachability was not
tested because the authentication precondition was missing. These results must
not be interpreted as a successful connection or as an empty Telegram response.

The corrected collection JSON includes `requested_limit`, `total_fetched`,
`valid_news_items`, `newly_inserted`, `duplicates`, `skipped`, `error_count`,
`errors`, and `channel_name`. Existing fields and exit codes remain available.

## D. Database Verification

The configured working SQLite database was queried through the repository and
read-only inspection statements. No news records were added, changed or deleted.

| Working-database check | Observed result |
| --- | --- |
| Tables | `sources`, `news` |
| Sources / news rows | 0 / 0 |
| SQLite integrity check | `ok` |
| SQLite encoding | `UTF-8` |
| Foreign keys enabled on repository connection | 1 |
| Foreign-key violations | 0 |
| Source unique constraint | `(platform, external_id)` |
| News unique constraint | `(source_id, external_id)` |
| News foreign-key target | `sources` |
| Duplicate source/news groups | 0 / 0 |

Zero violations in an empty database are schema/health observations, not evidence
of successful live persistence. Existing temporary-database tests separately
exercise actual inserts, database-enforced unique/FK failures, rollback, reopening,
Unicode equality (including whitespace and Persian half-spaces), UTC round trips,
source filtering and public message URL construction.

Executed mocked end-to-end evidence (not live Telegram statistics):

| Scenario | First execution | Second execution |
| --- | --- | --- |
| Same 3-message batch: 2 text posts + 1 empty | Fetched 3, valid 2, inserted 2, duplicates 0, skipped 1, errors 0 | Fetched 3, valid 2, inserted 0, duplicates 2, skipped 1, errors 0; database remains at 2 |
| Changed 2-message batch, with a renamed channel username | IDs 42 and 41: inserted 2, duplicates 0 | IDs 43 and 42: inserted 1, duplicates 1; database grows to 3 |

The changed-batch test compares stored `(source_id, external_id)` sets, proves
that only ID 43 was added, and verifies that the renamed channel remains one
source. It does not assume repeated latest-N requests return identical messages.
No live text-to-database equality, publication timestamp or public-link resolution
was verified because no real news was collected.

## E. Bug Fixes

| Changed file | Reason |
| --- | --- |
| `src/news_similarity/cli.py` | Add `requested_limit` and `error_count` to collection JSON, preserving existing keys and behavior |
| `tests/test_cli.py` | Regression coverage for both summary fields with custom/default limits, success/partial failure, and corrupt session-file construction |
| `tests/test_config.py` | Verify session-name loading from `.env` and process-environment override |
| `tests/test_telegram_collector.py` | Add invalid/revoked session, auth FloodWait, generic API error, and changing-message-set/renamed-channel checks |
| `README.md` | Document the two additional JSON fields |
| `VERIFICATION_REPORT.md` | Record actual checks, blockers and the local completion procedure |

Before the production fix, the focused regression run failed exactly the two
summary assertions for missing fields (60 other focused cases passed). After
the fix and additional custom-limit cases, the entire suite passes.

## F. Automated Test Results

Runtime: Python **3.12.14**. Final suite: **80 passed, 0 failed, 0 skipped**.
The baseline was **70 passed, 0 failed, 0 skipped**.

All commands were executed from the existing project directory:

| Command after `.\.venv\Scripts\python.exe` | Result |
| --- | --- |
| `-m pytest -q --basetemp=.tmp/verification-final -o faulthandler_timeout=30` | 80 passed in 1.98 seconds |
| `-m ruff check .` | All checks passed |
| `-m ruff format --check .` | 20 files already formatted after adding this report |
| `-m pip check` | No broken requirements found |
| `-m news_similarity.cli --help` | Exit 0; expected commands displayed |
| `-m news_similarity.cli init-db` | Exit 0; database initialized |
| `-m news_similarity.cli list-news --limit 10` | Exit 0; `[]` |
| `-m news_similarity.cli stats` | Exit 0; total news 0, sources `[]` |
| `-m news_similarity.cli collect-telegram --channel verification_target --limit 30` | Expected exit 2; missing-credential error, no Telegram request |

All seven PowerShell code blocks in this report were parsed with PowerShell's
parser: zero syntax errors. Live blocks were not executed without credentials.

The tests ran outside the network sandbox because Windows asyncio creates a
local socket pair when initializing its event loop. The sandbox blocked this
OS operation in the previous implementation session. Telegram calls remained
mocked; allowing the local event loop is not evidence of Telegram reachability.
Test temporary files stayed in ignored `.tmp/`.

Failure-scenario coverage:

| Scenario | Verification method / result |
| --- | --- |
| Invalid username syntax | Mocked; rejected before client start |
| Missing/private/inaccessible channel | Mocked resolution errors; reported, disconnected |
| Missing credentials | Actual CLI and tests; exit 2, no login prompt |
| Invalid/revoked/duplicated session authorization | Mocked Telethon auth errors; reported without repeated start |
| Corrupt local session database | Mocked constructor failure; safe storage error, exit 1 |
| Connection failure | Mocked; safe error and disconnect |
| Generic Telegram API error during history | Mocked; partial valid item saved, error preserved without payload |
| Authentication FloodWait | Mocked; requested delay reported, no automatic auth retry |
| History/entity FloodWait | Mocked delays, bounded retries, offset resumption and long-wait stop |
| Database insertion failure | Mocked SQLAlchemy failure and real temporary transaction rollback |

No real rate limits, account restrictions or repeated failed authentication
attempts were deliberately triggered.

## G. Outstanding Issues

1. Configure real API credentials locally and complete interactive authentication.
2. Verify Telegram connectivity and access to a user-selected public Persian news channel.
3. Run two live collections and inspect persisted text, timestamps, links and IDs.
4. The working database is empty, so real Unicode/caption persistence is unverified.
5. No project Git repository is initialized; only ignore-pattern behavior was audited.

No unresolved critical implementation failure was found by the executed offline
checks. Live compatibility remains unknown; it is not inferred from mock results.

## H. Final Verdict

**PARTIAL:** Implementation validated, but real-world verification remains incomplete.

## I. Next Steps

Complete this local procedure before starting Bale integration. The target is
chosen interactively; no news channel is hardcoded into the application.

### Configure and collect locally

In a local interactive Windows PowerShell terminal:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
notepad .env
```

In Notepad, enter the API ID/hash obtained from Telegram. Retain or choose a
persistent `TELEGRAM_SESSION_NAME`. Save and close the file. Do not paste its
contents, login codes, passwords or session files into chat. If process-level
Telegram variables are already set, they override `.env`.

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli init-db
$channel = Read-Host 'Public Persian news channel username you are authorized to read'
$before = .\.venv\Scripts\python.exe -m news_similarity.cli stats | ConvertFrom-Json

$first = .\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram --channel "$channel" --limit 30 | ConvertFrom-Json
$firstExit = $LASTEXITCODE
$first | Format-List
```

Complete the phone/code/2FA prompts directly in the terminal. If `$firstExit`
is nonzero, inspect `errors` and stop before running another collection. For
FloodWait, respect the reported delay. For an authorization problem, resolve
it locally rather than repeatedly retrying.

### Record persisted stable IDs and run the same command again

Once the first run succeeds:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli stats
$sourceId = Read-Host 'Internal source id shown above for the selected channel'

$afterFirst = .\.venv\Scripts\python.exe -m news_similarity.cli stats --source-id "$sourceId" | ConvertFrom-Json
$firstRows = @(.\.venv\Scripts\python.exe -m news_similarity.cli list-news --source-id "$sourceId" --limit 30 | ConvertFrom-Json)
$firstRows | Select-Object source_id, message_id, published_at, url | Format-Table

$second = .\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram --channel "$channel" --limit 30 | ConvertFrom-Json
$secondExit = $LASTEXITCODE
$second | Format-List
```

Stop if `$secondExit` is nonzero. After success:

```powershell
$afterSecond = .\.venv\Scripts\python.exe -m news_similarity.cli stats --source-id "$sourceId" | ConvertFrom-Json
$secondRows = @(.\.venv\Scripts\python.exe -m news_similarity.cli list-news --source-id "$sourceId" --limit 30 | ConvertFrom-Json)
$firstKeys = @($firstRows | ForEach-Object { "$($_.source_id):$($_.message_id)" })
$secondKeys = @($secondRows | ForEach-Object { "$($_.source_id):$($_.message_id)" })

if ($firstKeys.Count -gt 0 -and $secondKeys.Count -gt 0) {
    Compare-Object -ReferenceObject $firstKeys -DifferenceObject $secondKeys
}
[pscustomobject]@{
    FirstExit = $firstExit
    SecondExit = $secondExit
    FirstInserted = $first.newly_inserted
    FirstDuplicates = $first.duplicates
    SecondInserted = $second.newly_inserted
    SecondDuplicates = $second.duplicates
    CountAfterFirst = $afterFirst.total_news
    CountAfterSecond = $afterSecond.total_news
    CountGrowth = $afterSecond.total_news - $afterFirst.total_news
} | Format-List
```

The composite keys above are persisted `(source_id, message_id)` values, not
titles or row positions. The snapshots show the latest 30 stored rows, which
may include older persisted items when skipped messages reduce valid results.
They do not expose the exact incoming Telegram message set. Do not claim that
the two API responses were identical based on equal counts or snapshots alone.

For a successful second collection with no concurrent writer, count growth
must equal `second.newly_inserted`. If the same messages returned, inserted
must be 0, duplicates must equal valid items, and the count stays unchanged.
If new messages arrived, added stable keys and inserted counts may grow; the
second summary must still identify already stored messages as duplicates.
Keep both actual summaries and the stable-key snapshots for the final live report.

### Inspect persisted content and integrity

Display local text and metadata:

```powershell
$secondRows | Select-Object message_id, text, published_at, collected_at, url | Format-List
```

Compare selected text/captions with their original Telegram posts, including
Persian characters and half-spaces. Confirm aware `+00:00` timestamps and open
returned public links locally. Link construction tests alone do not verify
that a live post URL resolves.

Use the repository to check every stored item and SQLite integrity without
modifying records or printing article contents:

```powershell
@'
import json
from datetime import timedelta
from news_similarity.config import Settings
from news_similarity.database.repository import NewsRepository

repo = NewsRepository(Settings.load().database_url)
try:
    sources = {source.id for source in repo.list_sources()}
    rows = repo.recent_news(limit=max(repo.count_news(), 1))
    assert all(row.source_id in sources for row in rows)
    assert all(row.text.strip() and row.text.encode('utf-8').decode('utf-8') == row.text for row in rows)
    assert all(row.published_at.utcoffset() == timedelta(0) for row in rows)
    assert all(row.collected_at.utcoffset() == timedelta(0) for row in rows)
    keys = {(row.source_id, row.external_id) for row in rows}
    assert len(keys) == len(rows)
    with repo.engine.connect() as connection:
        integrity = connection.exec_driver_sql('PRAGMA integrity_check').scalar()
        violations = connection.exec_driver_sql('PRAGMA foreign_key_check').all()
        assert integrity == 'ok' and not violations
    print(json.dumps({'news_rows': len(rows), 'unique_stable_keys': len(keys),
                      'integrity': integrity, 'foreign_key_violations': len(violations)}))
finally:
    repo.close()
'@ | .\.venv\Scripts\python.exe -
```

A UTF-8 round trip checks readable stored strings; equality against the original
live message must be checked separately as described above. An empty database
is not successful collection evidence, even if these integrity assertions pass.

After live authentication, persistence and repeat-collection checks succeed,
record the real per-run statistics and then begin validating Bale's official
API and permission model. Do not start similarity or UI work in this phase.
