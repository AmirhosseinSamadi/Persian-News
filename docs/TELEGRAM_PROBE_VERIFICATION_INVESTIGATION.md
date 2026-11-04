# Telegram probe live verification investigation

Investigation date: 2026-10-29. Scope: the isolated probe only. No Telegram
requests, queue acknowledgements, webhook changes or production writes were
made during this investigation. The supplied live result is user-reported
evidence; new regression responses are explicitly synthetic.

## Root cause and expected behavior

The probe authenticates and parses messages separately from verifying a **new
post during this run**. The supplied `authentication_verified=true` and
`evidence_origin=live_http` establish that the real-client path authenticated.
Five accepted `channel_post` records establish successful parsing of authorized
channel messages. They do not establish when those messages were published.

The implementation makes **one** `getUpdates` call. There is no polling loop.
`--duration` is a request budget, not a watch window. `--poll-seconds` is the
timeout for that one request; queued messages can cause an immediate response.
After processing that response the process ends, even if almost all its budget
remains. A message sent after that response is never inspected by this run.

Telegram documents that omitted offsets return the earliest unconfirmed updates
and higher offsets confirm earlier IDs. The probe intentionally omits offsets,
so repeated executions can return the same earliest batch. Its informational
`next_offset_candidate` has no effect on Telegram. A batch at the requested
limit might hide later updates; a non-full batch does not guarantee the queue
will remain empty afterward. Source: [official getUpdates reference](https://core.telegram.org/bots/api#getupdates),
accessed 2026-10-29.

The unchanged verification predicate requires:

1. Successful preflight and the real HTTP client path, not an injected client.
2. An accepted record from an explicitly authorized receiving channel.
3. An original post event, not an `edited_*` event.
4. `floor(probe_started_at.timestamp()) <= published_at.timestamp()`.
5. `published_at.timestamp() <= observed_at.timestamp() + 5`.

Start time is captured **before preflight**, not when polling begins. Dates are
aware UTC timestamps; local Persian/Tehran clock display does not change the
comparison. Second rounding preserves Telegram's integer date precision. The
same-second allowance can include a post less than one second before the precise
start; it is existing behavior, not a new relaxation. A local clock ahead of
Telegram can misclassify posts as old; a clock far behind can reject them as
future-dated. The five-second future allowance is unchanged.

Telegram's `date` is publication time, while `update_id` identifies/order updates;
IDs are not timestamps and can restart randomly after prolonged inactivity.
`edit_date` does not replace the original publication date. Sources:
[Message](https://core.telegram.org/bots/api#message),
[Update](https://core.telegram.org/bots/api#update), accessed 2026-10-29.

For the supplied real-client original channel posts, the time predicate is the
remaining reason they can fail verification. Repeated queued older posts explain
the observation, but the supplied summary omits their dates and probe start:
it cannot alone distinguish old dates from excessive future skew. New diagnostics
show that distinction explicitly. `20604487` indicates a candidate following
the largest inspected ID when all entries were accepted; it says nothing about
publication time or whether later updates exist.

**Classification:** rejecting old queued posts is expected and preserves the
strict experiment definition. The one-batch/no-ack strategy has a known liveness
limitation. The defect addressed here is insufficient diagnostics and ambiguous
timeout help. No freshness rule, transport gate or queue policy was weakened.
Repeated no-offset polling would not solve a full first batch and would add
requests, so no retry loop was introduced.

## Small correction

Modified:

- `src/news_similarity/integrations/bot_probe.py`: `_verification_evidence`
  reports the start, observation time, exact effective time bounds, eligible IDs
  and each accepted record's rejection reasons. `live_probe` reports raw returned
  update count separately from accepted records, request limit, whether the batch
  reached that limit, one-request strategy and unknown remaining-queue state.
  The failure message now explains why increasing duration alone cannot help.
- `src/news_similarity/integrations/probe_cli.py`: help distinguishes the total
  request budget, one polling timeout and earliest-batch size.
- `tests/test_bot_probe_verification.py`: deterministic synthetic regressions
  simulate the full HTTP-client code path with a mocked opener; no requests
  leave the tests. Such tests exercise `VERIFIED` branches without establishing
  actual live connectivity.
- `README.md`: links this investigation. This document records findings and
  controlled verification instructions; the historical Phase 1.6A report is
  preserved.

New live JSON fields:

| Field | Meaning |
|---|---|
| `polling.updates_returned` | Raw batch count, including unsupported/unrelated entries |
| `polling.batch_at_limit` | Returned count reached the requested limit; not proof more updates exist |
| `polling.more_pending_updates` | Always `unknown`; the probe does not inspect later queue pages |
| `verification.probe_started_at` / `observed_at` | UTC times used by the decision |
| `verification.publication_not_before` / `publication_not_after` | Effective inclusive time window |
| `verification.records[].rejection_reasons` | `published_before_probe`, `published_after_clock_tolerance`, `edited_update` and/or `not_channel` |
| `verification.eligible_update_ids` | Content/time candidates only; injected clients still cannot be verified |

These fields describe accepted records only; rejected raw messages stay in
`dispositions`, without printing unrelated bodies. Existing output fields are
preserved. No automatic persistence, cursor, subscription mutation or queue
management command was added. Network and credential errors retain sanitized
diagnostics.

## Exact safe verification procedure with the current probe

1. Use an owner-authorized **dedicated test bot**, with no other poller/webhook
   consumer. Preserve its locally configured token and numeric channel allowlist
   in `.env.bot-probes`; do not put tokens in arguments or publish private JSON.
   Check that the machine clock is synchronized. The probe stops if a webhook
   exists rather than deleting it.
2. Use a quiet channel and a bot whose pending queue is already empty. A fresh
   setup can itself generate non-post updates, so "new bot" is not proof of an
   empty queue. An empty returned batch confirms only that inspection moment.
   Stop other sources of updates. For an existing backlog, read the opt-in
   proposal below; the current probe cannot drain it. Natural provider expiry
   on an unused bot is another option, but loses queued delivery at expiry.
3. From the project directory, start the following command. Have the owner ready
   to publish one harmless, original Persian text post **after the process
   starts and while its one polling request is outstanding**. Do not post first
   and then start another run: its new start window would reject that post.

   ```powershell
   Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
   .\.venv\Scripts\python.exe -m news_similarity.integrations.telegram_bot_probe --live --exclusive-test-bot --duration 60 --poll-seconds 20 --limit 100
   ```

4. Inspect the result immediately. Confirm original text, authorized chat ID,
   message ID, publication time and the new timing diagnostics against the
   controlled channel. Successful real preflight plus an eligible new post
   produces `VERIFIED`. The bot queue remains unacknowledged even on success.
   Retain sanitized evidence privately; do not store it in the production DB.
5. If the request returns older/setup updates immediately, this run did not wait
   for the owner. Do not repeatedly send posts or treat another start as replay
   verification. `--limit 100` only helps when the fresh post has already arrived
   before this response and fits inside the first 100 raw updates. Otherwise stop
   and address queue ownership through an explicitly reviewed procedure.

An empty queue and coordinated timing are preconditions, not guarantees of
network delivery or an exact wait duration. Increasing `--duration` does not add
polls. A later edit cannot substitute for an original post. No such new live
experiment was performed during this investigation.

## Queue management proposal — opt-in only, not implemented or executed

**Consequence before any implementation:** calling `getUpdates` with a higher
offset confirms **all bot updates with lower IDs**, across every chat and update
type, including unrelated events. Their pending API replay becomes unavailable
to another consumer. It does not delete the original channel messages. A saved
local copy is not a way to restore Telegram's queue. A stale candidate copied
from a previous run is not sufficient authorization or evidence for this action.

For a bot owned exclusively by this experiment, a future reviewed opt-in tool
could implement the following operator-driven procedure:

1. Confirm exclusive bot ownership and explicit approval of bot-wide queue
   acknowledgement. Stop all other consumers; inspect, but never change,
   existing webhook configuration. Settle handling of unrelated updates first.
2. Fetch at most 100 updates with no offset/filter and `timeout=0`. Save the full
   original response to a private, durable staging journal outside production,
   including unsupported/unrelated payloads. Fail closed on malformed IDs,
   conflicting duplicates, incomplete writes or a missing journal.
3. Review that exact staged batch and its highest update ID. Propose only the
   staged prefix boundary, `max(reviewed_update_ids) + 1`. Require a separate
   explicit operator confirmation of that boundary and its consequences.
4. Only then make one `getUpdates` request with that exact offset. For example,
   **only if a newly staged, reviewed complete prefix actually ends at
   `20604486`**, the confirmed request would use `offset=20604487`, `limit=100`,
   `timeout=0`, and no `allowed_updates`. Journal the returned next batch before
   proposing any further acknowledgement; errors must not trigger blind retries
   or cursor leaps. Do not use this example ID from the old summary directly.
5. Repeat review/confirmation per staged prefix until no pending updates remain.
   Keep the bot/channel quiet between this preparation and starting the fresh
   verification command. The fresh test post must still arrive after the new
   probe starts and is not automatically acknowledged by it.

This procedure must account for crash recovery and provider timeouts before it
is implemented. Negative offsets, backlog-drop flags, webhook deletion and
implicit acknowledgements remain excluded. The existing transport still rejects
any offset or `allowed_updates` parameter. No approval is inferred from a
numeric candidate; no acknowledgement path was added in this change.

## Regression coverage and verification

The added scenarios cover:

- Five queued original posts with max ID `20604486`, repeated unchanged across
  runs, producing the supplied non-verified shape and candidate `20604487`.
- Fresh content hidden by a five-update limit, exposed by a larger batch.
- A fresh 101st update that remains inaccessible at the maximum batch size.
- Original publication before start, the inclusive start second, existing future
  tolerance and excessive future clock skew.
- A very large update ID with an old date, and a fresh small ID.
- A recent edit of an old post, injected-client freshness without live status,
  and an empty one-request run.
- No offsets, acknowledgements, webhook changes, retries or queue mutations.

Actual results in the prepared Python 3.12.14 environment:

| Check | Result |
|---|---|
| Full pytest suite, including the opt-in cached MiniLM test | **530 passed in 58.62 seconds** |
| New deterministic cases | **11 passed** within the full suite |
| Ruff lint | All checks passed |
| Ruff format check | 92 files already formatted |
| Dependency check | No broken requirements found |
| Pre-change SHA-256 snapshot | 102 files checked; only the two probe source files and README changed; 99 previous files unchanged |
| Production SQLite | Unchanged SHA-256 `66de7540c2d36e84a48127331f3e63443ba9dba65c9896863fb838847e3cad8b` |

The new regression file and this new report are additions outside the snapshot.
Existing test files and the historical feasibility report remain unchanged.
Relevant code locations: `bot_probe.py:183` (verification evidence),
`bot_probe.py:223` (live preflight/start), `bot_probe.py:299` (the single poll),
`bot_probe.py:307` (batch diagnostics), `probe_cli.py:57` (timeout help), and
`test_bot_probe_verification.py:78` (five-post reproduction).

Reproduce in the prepared Windows environment:

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

The opt-in semantic test uses the existing cached model. Local loopback sockets
are required by existing async/Streamlit tests. An initial focused invocation
without the project-local TEMP override had six temporary-directory setup errors;
the new regression cases themselves passed. This is an environment setup issue,
not message classification failure; the full invocation uses the override above.

## Remaining limitations

This remains a single-batch inspection probe with no durable cursor or full
queue traversal. There is no hard guarantee of inspecting a post sent after the
first response, nor of finding a fresh update behind a full batch. Local clock
skew affects freshness. Content parsing, authentication and during-run freshness
are distinct evidence; `DOCUMENTED_ONLY` can coexist with actual authentication
and older real channel posts. The supplied summary cannot establish individual
publication times. No database, models, thresholds, UI, old datasets or previous
evaluation artifacts were modified.
