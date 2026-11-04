# Phase 1.6A — Messaging integration feasibility

Investigation and verification date: **2026-10-29**. Every external reference
below was accessed on that date. This report distinguishes documented capability
from local observations. No real channel message was received in this phase.

## Final platform status

| Platform | Final status | Reason |
|---|---|---|
| Telegram | **BLOCKED** | No bot token or authorized channel IDs; existing account API credentials are also unavailable. |
| Bale | **BLOCKED** | No bot token or authorized chat IDs; automatic channel delivery and reception permissions also remain unverified. |

`VERIFIED` requires an actual new authorized channel post through the real HTTP
transport. Fixtures, injected clients, authentication alone, private messages,
edits and previously queued posts cannot establish this. `DOCUMENTED_ONLY` in
an offline probe describes documentation/parsing work, not platform connectivity.
No capability is classified `UNSUPPORTED` merely because documentation is silent.

## Evidence table

Source links in this table were accessed **2026-10-29**.

| Platform | Access method | Official support | Live verified | Historical access | Status |
|---|---|---|---|---|---|
| Telegram | Bot API channel updates | [API reference](https://core.telegram.org/bots/api), [membership FAQ](https://core.telegram.org/bots/faq) | No | Pending updates, not general history enumeration | BLOCKED: credentials/authorized IDs absent |
| Telegram | Existing authorized Telethon/account API | [Account credentials](https://core.telegram.org/api/obtaining_api_id), [history method](https://core.telegram.org/method/messages.getHistory) | No | Accessible peer history under account permissions | BLOCKED: app registration/access unavailable |
| Telegram | Owner-authorized Desktop export | [Official export announcement](https://telegram.org/blog/export-and-more) | No export imported | Static JSON/HTML history export | DOCUMENTED_ONLY |
| Bale | Bot API message polling | [Official developer landing](https://bale.ai/dev) links to [API documentation](https://docs.bale.ai/) | No | Bounded pending-update queue | BLOCKED: credentials/authorized IDs absent |
| Bale | Automatic channel-post delivery | Message/chat representation is documented in [API documentation](https://docs.bale.ai/); receipt contract is unclear | No | No general history method identified in checked reference | BLOCKED: access absent and delivery requirements unresolved |
| Bale | Official account API or public channel feed | No authoritative supported collection contract identified in the checked official developer sources | No | Unknown | DOCUMENTED_ONLY investigation; no implementation or support claim |

## Documented facts and their implications

### Telegram

The [FAQ](https://core.telegram.org/bots/faq) states bots receive messages in
channels where they are members. Group privacy/admin rules should not be
mistaken for channel reception rules. A channel owner must authorize adding the
bot; the channel UI may use administrator management. No sending permission is
needed by this read-only experiment. A token/public channel URL alone is not
permission to subscribe to arbitrary channel posts. Accessed 2026-10-29.

The [Bot API](https://core.telegram.org/bots/api) documents `channel_post` and
`edited_channel_post`, including edits to posts known to the bot. `getUpdates`
and webhooks are mutually exclusive; updates expire after 24 hours. Polling
accepts batches of 1–100 and a timeout. A higher `offset` confirms earlier
updates; negative offsets can discard backlog. Omitted `allowed_updates` retains
the preceding subscription, and filters do not retroactively remove queued
updates. `getWebhookInfo` inspects configuration. No general channel-history
enumeration method was identified in this Bot API reference. These constraints
make this route appropriate for future authorized posts, not unrestricted
historical collection. Accessed 2026-10-29.

The [FAQ's rate limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)
concern outgoing messages (roughly one per second per chat, 20 per minute in
groups, and 30 per second for broadcasts). They are not receive-poll quotas.
The probe sends no messages and stops on API failures, reporting a validated
`retry_after` when supplied rather than retrying. Accessed 2026-10-29.

### Bale

Authority was established through [Bale's developer landing](https://bale.ai/dev),
which links to [docs.bale.ai](https://docs.bale.ai/). Third-party libraries and
claims of Telegram compatibility were not treated as evidence of undocumented
channel behavior. Accessed 2026-10-29.

The [official reference](https://docs.bale.ai/) specifies HTTPS
`https://tapi.bale.ai/bot<TOKEN>/METHOD_NAME`, token authentication, `getMe`,
`getUpdates`, and webhook methods. Its Update table lists `message`,
`edited_message`, `callback_query` and `pre_checkout_query`, **not** Telegram's
`channel_post` fields. Message metadata includes message/chat IDs, Unix dates,
optional text/caption and edit dates; Chat can represent a channel. The queue
is limited to 2,000 messages and 24 hours. Polling documents offset, limit and
timeout; no `allowed_updates` argument was found. No general history API was
identified. `getChatMember` requires admin privileges, which does not establish
an admin requirement for receiving posts. `retry_after` describes throttling
delays. Accessed 2026-10-29.

**Unverified:** a channel-shaped Message does not prove a bot automatically
receives new channel posts. Exact channel reception/admin requirements remain
unresolved. The Bale parser supports only documented `message` and
`edited_message` shapes. A future actual `message` with `chat.type=channel`
could provide experimental evidence; private/direct/forwarded messages retain
their actual receiving chat identity. No original channel identity is inferred.

## Repository inspection and implementation

The existing `NewsCollector` interface returns an asynchronous `CollectionBatch`;
the Telethon collector already implements authorized account-history collection.
`CollectionService` persists batches through the SQLite repository. `NewsItem`
is the reusable validated immutable record. Repository deduplication uses source
and external message identity; it currently ignores repeated inserts rather
than synchronizing edited bodies. That is unsuitable for silently attaching an
edit stream without a separate persistence policy.

The existing configuration, main CLI, Streamlit source-status page, collector,
database models, scoring services and all old tests are preserved. The UI still
reports production collection as unverified. The new modules do not instantiate
the collection service, database or models, and are not production collectors.
There are no dependency additions, model downloads or background workers.

Created files:

- `src/news_similarity/integrations/__init__.py`
- `src/news_similarity/integrations/bot_parsing.py`: provider dispatch, validated
  metadata, UTC timestamps, original Persian text and within-batch deduplication.
- `src/news_similarity/integrations/bot_probe.py`: bounded preflight and one
  polling request, strict read-only method allowlist, sanitized errors.
- `src/news_similarity/integrations/probe_cli.py`: separate environment settings,
  dry-run/offline/live modes and sanitized JSON output.
- `src/news_similarity/integrations/telegram_bot_probe.py`
- `src/news_similarity/integrations/bale_bot_probe.py`
- `tests/test_bot_probes.py`
- `tests/fixtures/telegram_bot_updates.json`
- `tests/fixtures/bale_bot_updates.json`
- `docs/BOT_PROBE_ENV.example`
- This feasibility report. `README.md` adds usage and current status.

Both fixtures are explicitly **synthetic**. Fixture content, IDs and timestamps
are fictional parser inputs, not verified news from either platform.

## Probe behavior and shared records

Default execution checks configuration without network access. Live mode also
requires an explicit `--exclusive-test-bot` assertion, numeric authorized IDs
(maximum five), and a valid environment token. Preflight authenticates, checks
for an existing webhook, resolves each authorized chat and, for Telegram,
checks this bot's membership. Bale does not borrow Telegram membership rules.
An active webhook stops the probe; no webhook is changed or deleted.

Each run makes at most **one** `getUpdates` request, with only `limit` and
`timeout`. It never sends an offset or subscription filter. The default budget
is 30 seconds (configurable 5–60); polling defaults to 15 seconds (0–20), batch
size 20 (1–100), responses are capped at 8 MB, and individual socket operations
receive remaining-budget timeouts. This is cooperative timeout budgeting,
not a process-level hard wall-clock kill against a trickling server response.
Redirects are refused and there are no automatic retries.

Within a batch, identical update IDs/payloads are deduplicated. A reused ID with
different content is flagged; separate edit updates retain their own update ID
and original message identity. Unsupported, unrelated, invalid or textless
updates hold `next_offset_candidate=null`. Otherwise that candidate is the
largest ID plus one, for inspection only: it is **never applied or persisted**.
Unrelated message bodies are not emitted. There is no durable cursor, cross-run
exactly-once guarantee or backlog bypass. Re-running can return the same queue;
a busy backlog can prevent observation of a fresh post. Pending data can still
expire at the provider. This is why an unused, dedicated bot is required.

Each `records[]` item includes `update_id`, `event_type`, `chat_type`,
`body_text`, `caption`, `edited_at` and a nested `news` dictionary containing
the existing `NewsItem` fields: `platform`, `channel_id`, `channel_name`,
`message_id`, `text`, `published_at`, `url`. Numeric IDs become strings;
timestamps become aware UTC ISO strings. Publication time remains the original
message date, while edit time stays separate. Text is copied without Persian
normalization; caption is used when the body is absent/blank. Missing titles and
optional fields are accepted. Missing mandatory metadata fails safely.

Telegram public links are constructed only from an actual valid channel
username and message ID; other Telegram links and all Bale links remain null.
Malformed messages are reported without printing raw payloads. Tokens are never
arguments or diagnostic fields; HTTP errors exclude URLs/descriptions. CLI JSON
also redacts the configured token and token-shaped strings even if they appear
inside a message. Consequently the underlying record preserves original text,
but its displayed copy can redact credential-like text. The probe intentionally
does not save live payloads automatically.

## Actual local observations

No bot token or authorized IDs were configured. No account API ID/hash was
available. Only presence was inspected; secret values were not printed.

| Executed check | Telegram | Bale |
|---|---|---|
| Default dry-run | BLOCKED, exit 2, zero requests | BLOCKED, exit 2, zero requests |
| `--live --exclusive-test-bot` without settings | BLOCKED, exit 2, zero requests | BLOCKED, exit 2, zero requests |
| Offline synthetic fixture | DOCUMENTED_ONLY, exit 0, 3 records | DOCUMENTED_ONLY, exit 0, 3 records |
| Informational offline next offset | 13; not sent | 3; not sent |
| Real authentication/new channel post | Not attempted: access unavailable | Not attempted: access unavailable |

Offline Telegram results include an edit and a caption plus one duplicate
update. Bale covers direct message, edit and caption shapes. Hypothetical Bale
channel-shaped messages are tested only as synthetic parser cases. None of
these observations establishes live channel reception or cross-platform news
collection. Production SQLite contents were not populated.

## Legitimate credentials and controlled verification

Telegram: create a dedicated bot through the official
[@BotFather workflow](https://core.telegram.org/bots/features#botfather), using
`/newbot`. A Bot API token is separate from account `api_id`/`api_hash`
registration, so this experiment does not need to retry the currently blocked
account registration. Have the owner add the bot to a controlled channel with
the minimum permissions the official client requires. These instructions are
based on [BotFather documentation](https://core.telegram.org/bots/features#botfather)
and the [channel membership FAQ](https://core.telegram.org/bots/faq), accessed
2026-10-29.

Bale: follow the official developer page's creation link to
[@botfather](https://ble.ir/botfather). Store its token locally. Use a controlled
conversation first to establish documented message polling; obtain authoritative
channel setup guidance or test owner-authorized channel addition separately.
Do not infer permissions from Telegram. Sources:
[Bale developer page](https://bale.ai/dev), [API reference](https://docs.bale.ai/),
accessed 2026-10-29.

For both, obtain the numeric chat ID from a trusted owner-controlled API response
or supported client metadata. Usernames are not accepted by this probe. If IDs
are unavailable, stop and resolve them locally through official tools; do not
enumerate someone else's queue. Keep the bot exclusive: no other poller or
webhook service. Never pass tokens on the command line or publish private JSON.
The probe intentionally cannot discover unknown IDs by dumping all messages.

Windows PowerShell, from the existing project:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
# Once only; do not overwrite an existing configured file:
Copy-Item docs/BOT_PROBE_ENV.example .env.bot-probes
# Edit .env.bot-probes privately, using the four documented variables.
.\.venv\Scripts\python.exe -m news_similarity.integrations.telegram_bot_probe
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_bot_probe

# Reproduce the synthetic checks without credentials or network access:
.\.venv\Scripts\python.exe -m news_similarity.integrations.telegram_bot_probe --offline tests/fixtures/telegram_bot_updates.json --chat-id=-100123
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_bot_probe --offline tests/fixtures/bale_bot_updates.json --chat-id=345

# Only after configuring an authorized, exclusive controlled bot:
.\.venv\Scripts\python.exe -m news_similarity.integrations.telegram_bot_probe --live --exclusive-test-bot --duration 30 --poll-seconds 20
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_bot_probe --live --exclusive-test-bot --duration 30 --poll-seconds 20
```

Environment variables override `.env.bot-probes`; `--env-file` can select another
local file. Production `.env` is not loaded by default. The template defines
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_CHANNEL_IDS`, `BALE_BOT_TOKEN` and
`BALE_BOT_CHAT_IDS`; ID lists are comma-separated. Real settings stay outside
version control. A missing configuration intentionally returns exit 2.

During a live run, have the owner publish one new harmless Persian test post
while the poll is waiting. Verify exact Unicode text/caption, actual chat/message
IDs and original UTC date against the controlled channel. A qualifying new
channel post, real transport and successful preflight are required for
`VERIFIED`. Clock agreement matters; publication must fall inside the probe's
second-resolution start window (five seconds of future skew tolerated). An
unconsumed backlog may return first; do not discard it to obtain a success.
An operator must check Telegram's prior subscription includes channel updates;
the probe will not reset an existing subscription. Test edits separately and
compare duplicate IDs on repeated runs without acknowledging them. Retain only
sanitized, consented evidence with date and observed permissions; there is no
such live evidence from the current phase.

## Alternative access assessment and recommendation

All source links here were accessed **2026-10-29**. Complexity and assignment
fit are engineering assessments, not provider guarantees.

| Method | Data and authorization | New/history | Complexity and operational limit | Assignment fit |
|---|---|---|---|---|
| Telegram permission-based Bot API | Owner adds bot to selected channels; legitimate bot token | Future updates, bounded queue | Low PoC complexity; owner cooperation, exclusive consumer, no full-history enumeration | Recommended first live path while app registration is blocked; only cooperating sources |
| Existing Telegram Telethon/account API | Legitimate app credentials, own authorized account/session and accessible peers | History; future streaming possible but not added here | Existing collector reusable; registration/login and platform restrictions remain blockers | Best existing option for permitted historical source collection once access is restored |
| Telegram Desktop export | Account owner exports accessible conversations | Static JSON/HTML, no automatic future reception | Low manual effort; importer and provenance review would be separate work | Useful authorized dataset fallback; does not demonstrate automatic reception |
| Bale Bot API polling | Legitimate token and owner-authorized conversation; channel rights unresolved | Documented messages/edits; bounded queue | Low message PoC complexity; channel delivery needs direct proof/provider clarification | Recommended experimental route; cross-platform channel requirement remains unmet |
| Bale direct/owner-forwarded messages | Consenting owner supplies material to bot; preserve receiving chat and provenance | New supplied messages, not automatic source history | Low manual setup; original source identity may be unavailable | Narrow demonstration fallback only; not proof of automatic channel collection |
| Publisher-provided feeds or archives | Explicitly published/licensed access and owner permission where needed | Depends on publisher | No supported channel-feed endpoint identified in checked Bale/Telegram bot docs; assess an actual offered feed separately | Conditional fallback, not implemented or verified |
| Bale account API/export | No supported collection contract identified in checked official sources | Unknown | Requires authoritative documentation before implementation | Not a current recommendation; private/reverse-engineered endpoints excluded |

Supporting sources: [Telegram membership](https://core.telegram.org/bots/faq),
[Bot API](https://core.telegram.org/bots/api),
[account credential requirements](https://core.telegram.org/api/obtaining_api_id),
[account history API](https://core.telegram.org/method/messages.getHistory),
[Desktop JSON/HTML export](https://telegram.org/blog/export-and-more),
[Bale official developer source](https://bale.ai/dev),
[Bale method reference](https://docs.bale.ai/).
No shared application credentials, stolen sessions, private endpoints,
unauthorized scraping or access-control workarounds were used.

## Verification

Actual results on 2026-10-29, using Python 3.12.14 in the existing virtual
environment:

| Check | Result |
|---|---|
| Complete pytest suite, including opt-in cached MiniLM test | **519 passed in 66.70 seconds**, no failures/skips |
| New probe tests within that suite | **47 passed**; the previous 472 tests also pass |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 91 files already formatted (final check) |
| `python -m pip check` | No broken requirements found |
| Protected-file SHA-256 comparison | All **87** previous source/test/dataset/report/evaluation/database files unchanged |
| Production `data/news.db` | Unchanged SHA-256: `66de7540c2d36e84a48127331f3e63443ba9dba65c9896863fb838847e3cad8b` |

New tests cover both
documented payload shapes, Persian Unicode, IDs, dates, edits, captions, optional
fields, malformed data, duplicates, conflicting IDs, unrelated queues, deadline
budgets, redirects, membership identity, webhook preservation, token redaction,
HTTP failures, missing configuration and no database writes. No credentials or
external API access are needed. Injected clients cannot claim live verification.

```powershell
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
# Optional existing real-model test, using only the previously cached model:
$env:RUN_SEMANTIC_INTEGRATION = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

The optional semantic test requires the existing cache; omit the opt-in variable
if unavailable, and report that test as skipped. Streamlit/async tests require
local loopback socket support. No model or dependency installation is necessary
in this prepared environment.

## Concrete Phase 1.6B plan

1. **Access gate:** obtain legitimate dedicated bot tokens and controlled IDs.
   Record a real Telegram channel post. For Bale, resolve exact reception/admin
   requirements through the official provider and capture an actual channel
   payload. Keep Bale experimental until this succeeds. Do not mark UI sources
   connected based on mocks or `getMe` alone.
2. **Queue ownership:** design a single consumer per bot, a durable inbox and
   checkpoints. Persist every relevant envelope before confirming the contiguous
   processed prefix. Quarantine unsupported/unrelated/malformed updates rather
   than silently discarding them. Handle retries, provider throttling, recovery
   and retention explicitly. The current candidate offset is not a production
   checkpoint implementation.
3. **Persistence contract:** adapt verified messages to `NewsCollector` and
   `CollectionService`. Define edit/version/upsert behavior first: the current
   repository's ignore-on-duplicate insertion would lose corrected bodies.
   Review any necessary migration separately; none is introduced here.
4. **Controlled integration:** add opt-in configuration and bounded collection
   commands, retaining Telethon for permitted history. Add replay/restart and
   update-delivery tests. Production enablement requires dated live evidence and
   explicit source authorization. No automatic worker is required.
5. **Application proof:** store a small real authorized sample in a separate
   staging archive, verify counts, timestamps, original Persian text, provenance
   and duplicates, then exercise existing ranking. Show actual evidence-backed
   source status. Cross-platform matching claims require independently reviewed
   real pairs and untouched evaluation groups; existing scores/thresholds and
   synthetic historical reports remain unchanged.

The project is ready for controlled access verification and subsequent adapter
design. It is **not yet ready for verified automatic cross-platform ingestion**.
