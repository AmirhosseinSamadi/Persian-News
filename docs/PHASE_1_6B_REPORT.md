# Phase 1.6B — Production news collection integration

Implementation date: **2026-10-29**. This phase adds bounded, explicitly invoked
Bot API collection into the existing archive. Telethon, NLP algorithms, frozen
thresholds, datasets and prior evaluation reports are preserved.

## Live evidence versus implementation tests

The owner reports both experimental probes received new authorized Persian
channel posts with `VERIFIED`, authenticated real HTTP evidence. That is the
Phase 1.6A prerequisite supplied by the user. This implementation session did
**not** repeat a live production collection or acknowledge any real queue.
All new collection/acknowledgement tests use synthetic fixtures or mocked APIs
and isolated real SQLite databases. Production `data/news.db` was not migrated
or populated during implementation. No fabricated live collection is claimed.

The new commands report storage/checkpoint outcomes, not the probe's freshness
status. Older pending authorized posts can be stored with their original dates;
this does not establish a new during-run live verification.

## Architecture and changed files

Added:

- `src/news_similarity/collectors/bot_api.py`: environment configuration, bounded
  sanitized transport, per-bot OS lock and provider-aware update classification.
- `src/news_similarity/collectors/telegram_bot.py`: Telegram Bot API collector,
  separate from the retained account-based Telethon collector.
- `src/news_similarity/collectors/bale.py`: Bale Bot API collector using Bale's
  documented `message` envelope and actual receiving channel identity.
- `src/news_similarity/database/bot_storage.py`: additive checkpoint table,
  durable inbox, transactional insertion/checkpoints and read-only status.
- `src/news_similarity/services/bot_collection.py`: one-shot preflight,
  store-before-confirm orchestration, recovery and CLI handlers.
- `tests/test_bot_collection.py`: persistence, offset, failure, restart, lock,
  CLI and UI integration tests with synthetic clients.
- `tests/fixtures/production_bot_updates.json`: explicitly synthetic realistic
  Telegram/Bale text and caption envelopes; never verified reporting.
- This report.

Modified:

- `src/news_similarity/cli.py`: three new commands; every old command retained.
- `src/news_similarity/ui/services/ui_facade.py`: read-only checkpoint history.
- `src/news_similarity/ui/pages/sources.py`: durable collection outcomes,
  timestamps and pending/blocked counts, without network activity or redesign.
- `tests/test_ui_app.py`: source page's current-status wording expectation.
- `tests/test_event_features_cli.py`: command inventory includes the three new
  names while retaining all prior names.
- `README.md`: commands, policy, checkpoint behavior and current live limits.

The existing explorer already reads Source/News records, platform labels,
original text, channel names, dates and candidates through the facade. It needs
no alternative archive or matching algorithm. A new cross-platform test stores
both providers in one temporary archive and passes cross-source candidates to
the existing ranking interface. Its model response is mocked, not a quality
measurement. Synthetic demo archives remain separate; CLI production loading
refuses `NEWS_UI_DEMO_MODE=1`.

The old `CollectionService` owns independent batch commits and is retained for
Telethon. It cannot safely coordinate a bot's global queue checkpoint with news
insertion. `BotCollectionService` therefore uses the same `NewsRepository` engine,
Source/News models, source helper and validated `NewsItem` contract, while owning
the combined transaction. This is a separate collection coordinator rather than
a rewrite of the old collector interface.

## Provider contracts

The [Telegram Bot API](https://core.telegram.org/bots/api#getupdates) documents
`channel_post`/`edited_channel_post`, earliest unconfirmed polling without an
offset, confirmation of IDs below a requested offset, batches up to 100 and
24-hour update retention. Existing webhooks prevent polling. Omitted
`allowed_updates` retains the previous subscription. Telegram channel membership
is checked during preflight. Sources: [API](https://core.telegram.org/bots/api),
[membership FAQ](https://core.telegram.org/bots/faq), accessed 2026-10-29.

The [official Bale reference](https://docs.bale.ai/) documents `message` and
`edited_message`, channel chat metadata, token-authenticated
`https://tapi.bale.ai/bot<TOKEN>/METHOD_NAME`, positive-offset confirmation and
earliest unconfirmed polling, limit 1–100 and a 2,000-message/24-hour queue. It
does not document Telegram's channel-post envelope or `allowed_updates` filter.
Sources: [reference](https://docs.bale.ai/), [official developer landing linking
that reference](https://bale.ai/dev), accessed 2026-10-29.

The collectors share transport only. Telegram selects `channel_post`; Bale
selects `message` with `chat.type=channel`. No Telegram fields or public-link
formula are assumed for Bale. Both omit subscription filters and refuse active
webhooks. Redirects and raw exception/provider descriptions are withheld by the
existing HTTP layer; rate errors stop the run, without automatic retry. Sending
limits are not treated as polling quotas.

## Checkpoint strategy and justified schema addition

Exactly one additive table, `bot_checkpoints`, is created by the bot collector
after preflight. It has composite `(platform, bot_id)` identity, a fingerprint of
the authorized channel scope, committed next-offset candidate, status, UTC
update time and a JSON state. The state holds:

- Complete pending envelopes, their content digests, IDs and processing outcomes.
- Last confirmed offset, any durable acknowledgement intent, and ordering errors.
- Evidence origin (`live_http` for the real client path, `mocked` for injected
  clients). No credential is stored in the checkpoint.

Source and News are reused without changing their schema. Their existing
uniqueness constraints remain `(platform, source external ID)` and
`(source ID, message external ID)`. Text is not a deduplication key: identical
texts with different message IDs are preserved. Incoming text/caption is copied
without Persian preprocessing. Dates remain aware UTC. Private Telegram links
are null; public links require actual valid username metadata; Bale links remain
null. A repeated message identity with differing text/publication is blocked
rather than silently overwriting the original.

The extra table uses separate SQLAlchemy metadata so old archive initialization
and synthetic demo generation retain their existing behavior. Bot collection
creates the table on demand; no existing rows/tables are deleted. Status/UI
reads recognize legacy archives without the table and do not create it. Back
up the archive before the first production collector run; SQLite DDL creation
precedes the news/checkpoint transaction.

## One-shot processing and acknowledgement

1. Require legitimate bot credentials, explicit numeric authorized channel IDs
   and `--exclusive-test-bot`. Authenticate, take the per-bot lock, inspect the
   webhook, resolve every authorized channel, and check Telegram membership.
2. Fetch **one bounded earliest batch without an offset**, even on restart. This
   operation cannot acknowledge older events. The default limit is 30, maximum
   100; polling defaults to 15 seconds, maximum 20; the total request budget is
   30 seconds, configurable 5–60. There is no daemon or retry loop.
3. In one SQLite transaction, merge the full batch into the durable inbox,
   process up to the configured limit of new pending records, insert valid news
   idempotently, and compute/store the safe prefix's next offset. An exception
   rolls back sources, news and checkpoint together.
4. **Default: return without acknowledging.** Repeated runs may re-read the
   same events and report duplicates. A checkpoint candidate is informational
   until a separate explicitly enabled acknowledgement call.
5. With `--acknowledge-stored`, commit an acknowledgement intent for exactly the
   durably processed safe prefix, then issue one offset request. It cannot cover
   an unknown/blocked/pending event. This is an irreversible opt-in flag and the
   CLI prints a warning before the action. This session never used it live.
6. The confirming request asks for at most **one** next update. Its response is
   journaled without processing or confirming that new update in this run. Safe
   acknowledged inbox entries are pruned; unresolved entries remain. The
   original news stays in Source/News. Another one-shot invocation is required
   to process/confirm the next prefix.

This design uses production durable outcomes, not the experimental signed
receipt/review workflow. Experimental approvals do not override a production
checkpoint or authorize future sources.

## Explicit blocked-event policy

- **Original channel text/caption, authorized, valid:** store it, then permit
  that durable event in the confirmation prefix.
- **Authorized recognized file media without text/caption:** validate basic
  file metadata, retain its raw envelope and record `skipped_non_text`; it is
  not news. This explicitly documented non-news outcome can be confirmed only
  with the acknowledgement flag. There are no media downloads. Empty textless
  messages, unknown message fields and unsupported media/service variants are
  blocked rather than silently treated as non-news skips.
- **Service event:** skip as news but retain it as
  `blocked_service_skipped_as_news`. Membership notifications, including zero-ID
  Bale service variants, are not automatically acknowledged in production.
- **Edit:** retain as `blocked_edit`. This phase does not implement revision
  synchronization or silently ignore a correction; existing text remains intact.
- **Unauthorized/non-channel/unknown/malformed event:** retain a corresponding
  blocker and raw evidence; never create news from it or advance past it.
- **Conflicting update/message identity, invalid IDs, ordering reversal, gaps
  inside a batch or confirmed-cursor regression:** block advancement. Ordinary
  duplicates are idempotent, with duplicate-update counts reported separately.

Valid news after a blocked event may still be stored, but its presence cannot
make the checkpoint leap over the blocker. A safe earlier prefix can be
confirmed while the blocked tail remains queued and journaled. There is no
production skip/clear/negative-offset/review-bypass flag. Resolving blockers
requires an explicit future policy/migration, not direct deletion of state or
running the experimental queue tools against an active collector.

## Failure recovery and operational limits

| Interruption | Durable state and next step |
|---|---|
| Before combined transaction commits | No news/checkpoint results commit and no acknowledgement is sent; fetch again |
| After storage, before acknowledgement | News and safe candidate survive; default restart still sends no offset |
| After intent, before/during request | `ACK_PENDING` or `ACK_UNKNOWN` plus intent survives; do not infer that confirmation failed |
| API applied, response lost | Already confirmed prefix's news is durable; an explicitly enabled later run can safely re-confirm only a committed safe prefix |
| Acknowledgement response journal fails | Keep prior inbox/intent, report unknown; returned next update was not acknowledged and can be read again within provider retention |
| Unknown/unauthorized event or changed scope | Hold checkpoint; preserve evidence; operator policy/migration needed |

Restart first inspects the current earliest batch without offset. It merges new
data and blocks regressing/unknown earlier IDs before computing any candidate.
An explicit acknowledgement flag is required again; no background replay of
an intent occurs. Repeating a safe committed prefix is permitted here because
all effects below that offset are durable; the experimental workflow's
unpersisted-message assumptions do not apply. Duplicate inserts remain safe.

Only one cooperating production collector can hold a bot's OS advisory lock.
Locks are released on crash and never removed while another process may hold
the inode. Use one shared `NEWS_BOT_LOCK_DIR` for all local deployments of the
same bot, including different databases. Defaults assume commands are run from
this project directory. Locks cannot coordinate different hosts, external bot
services or experimental probes/queue tools that do not use this lock. The
exclusive-owner assertion is therefore mandatory; stop those other consumers.

Timeouts use a cooperative remaining-budget socket timeout, not a hard process
kill against a trickling response. No automatic rate-limit retry is attempted.
Pending inboxes are capped at 1,000 records / 16 MB canonical JSON. Reaching
capacity rolls back the incoming transaction and prevents acknowledgement.
Provider expiry can remove unseen events before collection; no application
can guarantee recovery beyond provider retention. Retained blocked records may
outlive the provider queue and are not silently dropped. Token rotation for the
same bot retains its identity; changing authorized scope requires review.

## Windows PowerShell commands

Run from the existing project. Database settings come from `.env` or the process
environment; bot settings default to the separate `.env.bot-probes`. Optional
`--bot-env-file` selects a different private bot file. Reuse the existing
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_CHANNEL_IDS`, `BALE_BOT_TOKEN` and
`BALE_BOT_CHAT_IDS`; do not put tokens in arguments. `NEWS_BOT_LOCK_DIR` is read
from the bot configuration/environment. Keep credentials outside version control.

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
# Safe one-shot storage: no offset/acknowledgement requests.
.\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram-bot --limit 30 --exclusive-test-bot
.\.venv\Scripts\python.exe -m news_similarity.cli collect-bale --limit 30 --exclusive-test-bot
.\.venv\Scripts\python.exe -m news_similarity.cli collection-status
```

Missing credentials fail before creating a database. Status is read-only and
returns an empty list for a missing/legacy archive. It does not contact providers
or prove current connectivity. Status outputs show pseudonymous collector refs,
counts, offsets and blocker codes; no tokens, message bodies or chat/user IDs.

**Only after the owner explicitly approves irreversible queue confirmation**:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli collect-telegram-bot --limit 30 --exclusive-test-bot --acknowledge-stored
.\.venv\Scripts\python.exe -m news_similarity.cli collect-bale --limit 30 --exclusive-test-bot --acknowledge-stored
```

These are executable opt-in instructions, not actions performed during this
implementation. They collect and confirm only a safe committed prefix, not the
whole backlog. Services/edits/unauthorized events can leave the run blocked.
Exit codes: 0 stored/confirmed, 2 blocked/error, 3 uncertain acknowledgement.

For an owner-coordinated live smoke, first use a separate SQLite path by setting
`$env:DATABASE_URL = 'sqlite:///./.tmp/bot-smoke.db'`, run the store-only commands
on the authorized dedicated test bots, and publish a harmless original Persian
post while polling. Check exact text, source, IDs, UTC dates and duplicate
counts privately. Save the previous DATABASE_URL value and restore it afterward
(remove the override only if there was no previous value). Starting Streamlit
against that same staging path displays those stored sources/news. Do not use
production pending events for destructive testing or enable acknowledgement
merely to produce a success status. No such new live smoke was run here.

## Database/UI integration and security

Tests exercise real transactions in temporary SQLite files: both providers
coexist as two platforms/sources with four synthetic articles and separate
checkpoints; identical bodies under different message IDs remain separate;
restart duplicates do not create more rows. Rollback tests leave no partial
source/news/checkpoint writes. New bot data is consumed by the unchanged
archive explorer and cross-source ranking interface. AppTest renders durable
source status without network or model downloads. Injected-client histories
are labeled test data, never live proof. Synthetic demo mode remains separate.

Complete raw inbox envelopes may include unauthorized/private bot events, so
protect SQLite backups and filesystem access. They are retained for recovery,
not shown as news or printed in logs. The database is not encrypted. Source
names/text displayed in the archive are authorized stored news, not diagnostic
logs. Do not publish checkpoint JSON, credentials or private payloads. No token
is persisted, and HTTP/provider/SQL exception payloads are not printed.

## Verification and readiness

New tests cover both provider envelopes, original Persian text/captions, duplicate
updates/news, identical text with distinct IDs, service and unauthorized events,
malformed input, committed-prefix correctness, partial batches, transaction
rollback, response loss, persistence failure after acknowledgement, restart,
scope changes, cursor regression, webhooks, local locks, missing credentials,
private URLs, CLI status and read-only database/UI integration.

Actual results on 2026-10-29, Python 3.12.14 in the existing virtual environment:

| Check | Result |
|---|---|
| Complete pytest suite, including cached MiniLM integration and Streamlit tests | **669 passed in 40.72 seconds** |
| New production integration cases | **46 passed**, alongside the prior 623 cases |
| Ruff lint | All checks passed |
| Ruff format check | 107 files already formatted |
| Dependency validation | No broken requirements found |
| Protected-file SHA-256 comparison | 112 files checked; six intended existing files modified; 106 previous files unchanged |
| Production SQLite | Unchanged SHA-256 `66de7540c2d36e84a48127331f3e63443ba9dba65c9896863fb838847e3cad8b` |
| Frozen evaluations and packaged datasets | Unchanged |
| New live production ingestion / queue acknowledgement | **Not executed** |

The eight added source/test/fixture/report files listed above are outside the
pre-change snapshot. CLI help for collection/status was exercised without network
or database writes. Reproduce:

```powershell
$env:PYTHONUTF8 = '1'
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

The prepared environment uses the existing cached MiniLM; there is no new model
or dependency download. Local loopback support is needed by existing async/UI
tests. A prior full run exposed only the old CLI command inventory expectation;
it was updated to include the new commands without removing any existing ones.

**Phase 1.6C readiness:** ready for owner-controlled store-only production smoke
testing and further orchestration. Automatic continuous ingestion, edit/version
updates, production blocker resolution, distributed ownership and a policy for
capacity/retention require further work. Probe verification supplied by the
owner does not replace a new production-path live smoke and explicit approval
of any irreversible acknowledgements. No NLP quality improvement is claimed.
