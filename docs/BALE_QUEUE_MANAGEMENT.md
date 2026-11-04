# Experimental Bale service events and explicit queue review

Date: **2026-10-29**. This is a separate, opt-in development workflow. The normal
Bale and Telegram probes still never send offsets or acknowledge updates. No
real queue acknowledgement or live platform request was performed while
implementing or testing this change.
Every acknowledged update now requires individual approval in a separate signed
review file, including ordinary authorized messages. Commands that omit the
review file fail closed; normal inspection and probe commands are preserved.

## Provider evidence and observation

The [official Bale API reference](https://docs.bale.ai/) was accessed on
2026-10-29. Its `getUpdates` section explicitly documents that omitted offsets
return the earliest unconfirmed updates and requesting an offset greater than
an update ID confirms that update. The requested offset is one greater than
the highest received ID being confirmed. It documents limits of 1–100 and
negative-offset backlog forgetting. This workflow **never uses negative offsets**.
The same reference documents token-authenticated HTTPS requests at
`https://tapi.bale.ai/bot<TOKEN>/METHOD_NAME` and `getWebhookInfo` inspection.
These are Bale's own documented semantics, not assumptions imported from
Telegram. The specific offset paragraph, rather than the more general queue
retention wording, is the basis for explicit acknowledgement.

The user reports an actual authorized `message` with `chat.type=channel`,
update ID `6`, authenticated through real HTTP. That supports
channel delivery for that tested bot/configuration. The message predates the
probe run, so it does not meet the existing during-run freshness requirement.
This observation is user-supplied; it was not independently repeated here.
Acknowledging it does not retroactively make it a fresh post or establish
universal Bale channel permissions.

## Irreversible consequences

**Acknowledging through ID 6 sends offset 7. It confirms every pending update
with an ID below 7 for that Bale bot, across all chats and event types.** Pending
API replay cannot be restored by this tool. Other consumers could lose access
to those queued updates. This does not delete the original channel posts or
write to the production SQLite archive.

The acknowledgement command displays this warning before the action. It requires
both an explicit `--ack-through` highest inspected ID and
`--confirm-irreversible`, plus `--exclusive-test-bot`. No offset is inferred from
the old live result or applied by inspection or normal verification.
A matching `--review-file` and exact boundary are mandatory. Recording review
approvals is local and reversible; it never executes the irreversible request.

## Implementation and changed files

- **Modified** `src/news_similarity/integrations/bale_diagnostics.py`: validates
  membership service structure independently of ordinary messages.
- **Modified** `src/news_similarity/integrations/bale_queue.py`: classifies
  recognized service records, adds local per-update review and checks signed
  reviews before acknowledgement. No approval is inferred automatically.
- **Added** `tests/test_bale_review.py`: 31 synthetic review/service regressions.
- **Modified** `tests/test_bale_queue.py` and `tests/test_bale_diagnostics.py`:
  adapt existing expectations and success scenarios to explicit review, retaining
  their prior failure-path coverage.
- **Modified** `README.md` and this report: current behavior and commands.

The shared transport, normal probe CLI modules, shared news parser, Telegram
collector, UI, SQLite data/schema, news records, NLP models and evaluation
artifacts were not modified by this extension. No dependency was added.

## Safety boundaries

### Inspection

`inspect` authenticates the Bale bot, refuses an active webhook, and makes one
`getUpdates(limit=100, timeout=0)` request **without an offset**. No webhook or
subscription setting is changed. No sending method is exposed.

The command prints each returned update's ID, event type and available chat
type, together with blockers and structural diagnostics. Chat/user IDs, names,
message bodies and credentials are not printed. Unsupported events remain visible; callbacks
show nested message chat metadata when available. Unknown chat types are shown
as unknown rather than inferred. Bodies are not printed.

A new inspection receipt stores the **complete original batch**, bot ID,
authorized chat scope, UTC inspection time and a token-keyed HMAC. The receipt
is created exclusively, flushed and synced; an existing file is never
overwritten. This retains unsupported/unrelated events for review, rather than
discarding their payloads. File creation is a local staging write, not a
production database write. A receipt is required even for an empty inspection.
`acknowledgeable_through` remains a structural candidate, not acknowledgement
authority: `approval_required_for_all_updates=true` and
`acknowledgement_ready=false` make the missing review explicit.

### Bale service classification

The [official Message and User tables](https://docs.bale.ai/) (accessed
2026-10-29) document `new_chat_members` for groups as an array of User objects.
The API describes message IDs as integers without defining zero-ID service
identity. Channel use of this membership field remains an observed, uncertain
variant. The application treats a zero ID as **potentially valid only inside a
recognized service envelope**, identified for queue purposes by its update ID.

Recognition requires an original `message`, nonnegative integer message ID/date,
integer chat ID, group/channel scope, a nonempty member array, typed member
`is_bot`/`first_name` fields, valid optional member fields and no mixed text,
media or competing service payload. Missing/malformed data, booleans as IDs,
negative IDs, edited membership events or ambiguous mixed variants remain hard
blockers. This is deliberately a narrow structural classifier, not full entity
verification.

Group membership events carry `service_review_required`. Recognized channel
variants additionally carry `uncertain_channel_service`. Unauthorized chats
retain `chat_not_authorized`. These blockers can be accepted only for the exact
individual updates in a signed review; they do not disappear from inspection.
Ordinary zero-ID news and unknown service envelopes remain hard-blocked.
Neither service variant creates a `NewsItem` or changes shared news validation.

### Explicit local review

`review` reads an authenticated, unexpired inspection receipt and creates a new,
token-signed review file. It makes **zero API requests**. The user must list
each selected update separately with `--approve-update`, in prefix order, and
give the exact `--ack-through` boundary. There is no approve-all flag. Missing,
duplicate, reordered or out-of-prefix approvals are rejected.

All selected entries need approval, even authorized ordinary messages. Review
can accept an understood unauthorized message or recognized service event for
**acknowledgement only**. It does not expand the authorized source list, mark
anything as news or permit future updates from that chat. Malformed, unknown,
callback/payment, duplicate/reordered/gapped update envelopes cannot be bypassed
by approval in this minimal version.

The review binds the complete inspection digest, bot, policy version, exact
boundary, individual IDs and review time. Both inspection and review expire
after 15 minutes; reviewing an old receipt cannot extend its lifetime. Changing
the token, scope, payload, boundary or approved IDs invalidates the review.

### Explicit acknowledgement

The selected highest ID must appear in a valid, intact receipt no older than
15 minutes. The receipt must match the current Bale token and authorized chat
list. A token rotation or scope change requires a new inspection. Partial
prefixes are allowed: inspecting 0, 1, 2 and confirming through 1 sends offset 2,
leaving update 2 pending. The caller never supplies a raw offset.

Every selected entry must have valid structural metadata and an explicit
matching approval. The only reviewable policy exceptions are unauthorized chats,
recognized membership services and their uncertain channel scope. All other
blockers remain non-overridable. A missing review file fails before API calls.

Before acknowledgement, the command authenticates again, checks webhook status
and bot identity, then re-fetches the earliest batch without an offset. The
complete prefix through the selected ID must exactly match the saved prefix.
Missing, changed or newly inserted earlier events block the action. Newer updates
above the selected ID are not acknowledged; they are retained in the local
revalidation journal and any returned next batch.

Only after these checks does the tool create and sync
`<receipt>.ack-attempt.json`. This durable marker contains the exact boundary and
the full revalidated batch, approved IDs and review digest. It then makes **one** Bale request:
`getUpdates(offset=highest_id+1, limit=100, timeout=0)`.
The response is saved separately as `<receipt>.ack-result.json`, including all
returned updates. Those returned updates remain **unacknowledged**: receiving
them is not permission to advance again. Acknowledgement is never looped.

The attempt marker prevents reusing that receipt path, including after a
timeout/crash. An uncertain request/result-save/response-validation outcome is
reported `UNKNOWN`, exit code 3. It might already have applied: never repeat the
command with that receipt. Inspect anew and reconcile the saved attempt/result
with the current queue. An API-success receipt records the provider envelope;
it is not a freshness verification result.

## Exact Windows PowerShell workflow

Use the existing `.env.bot-probes` with your legitimate `BALE_BOT_TOKEN` stored
privately. Do not put the token in a command argument. Environment variables
override that file; `--env-file` can select another local file. Only Bale settings
are used. Keep the existing authorized chat list unchanged while reviewing old
unauthorized messages; per-update approval is not source authorization.

First stop any other consumers of this **dedicated experimental bot**. Keep the
channel quiet while reviewing and acknowledging old updates. The workflow
cannot establish exclusive ownership remotely; the flag is your explicit
assertion. An active webhook causes a refusal rather than removal.

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
New-Item -ItemType Directory -Path .tmp -Force | Out-Null
# Keep BALE_BOT_TOKEN and BALE_BOT_CHAT_IDS privately configured in .env.bot-probes.
```

**Step 1 — read-only inspection:** inspect the pending queue and save a unique receipt:

```powershell
$receipt = Join-Path '.tmp' ('bale-inspection-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '.json')
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_queue inspect --receipt $receipt --exclusive-test-bot
```

Review the printed IDs, event/chat types, blockers and
the diagnostics. Review the complete receipt privately when deciding
what is being confirmed; it contains raw payloads and may be sensitive. If a
hard structural blocker appears before your chosen boundary, stop. Known
unauthorized/service entries require explicit acknowledgement-only review;
do not add someone else's chat to the allowlist to make the check pass.

**Step 2 — local explicit approval:** only if the fresh inspected prefix is
exactly updates 1–6 and you have deliberately reviewed each one, record six
individual approvals. Otherwise use the actual inspected prefix and boundary;
do not approve unseen IDs. This command makes no API calls:

```powershell
$review = $receipt + '.review.json'
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_queue review --receipt $receipt --review-file $review --ack-through 6 --approve-update 1 --approve-update 2 --approve-update 3 --approve-update 4 --approve-update 5 --approve-update 6 --exclusive-test-bot
```

The review does not mark updates 1–5 as news, authorize their chats, or change
the queue. Ordinary update 6 also needs its own approval. Duplicate approvals
are rejected; no old receipt or review file is overwritten.

**Step 3 — irreversible confirmation:** acknowledging through 6 confirms every
pending ID below 7 across the bot. After accepting that consequence, execute
the separate command yourself. The implementation session did not execute it:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_queue acknowledge --receipt $receipt --review-file $review --ack-through 6 --confirm-irreversible --exclusive-test-bot
```

The `6` is the highest reviewed update ID, **not** an offset. If your actual
inspection has a different boundary, deliberately select that inspected value.
Do not reuse a stale ID or derive it from the old observation. Missing confirmation,
an absent/out-of-range boundary, incomplete/mismatched review, stale/changed receipt or a changed prefix
returns `BLOCKED`, exit code 2, without an acknowledgement request.

**Step 4 — confirm queue state** with a read-only inspection and a **new** receipt:

```powershell
$emptyReceipt = Join-Path '.tmp' ('bale-empty-check-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '.json')
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_queue inspect --receipt $emptyReceipt --exclusive-test-bot
```

`queue_empty: true` means the returned batch was empty at that inspection moment.
If false, review the new batch and repeat a separate explicit acknowledgement
only if appropriate. A full 100-update batch can hide further pending updates;
this tool never skips to its tail or drains the queue automatically. A new
acknowledgement always requires its own inspection and per-update review.

**Step 5 — live channel-post test:** once the quiet bot queue is empty, start the **unchanged normal probe**, then
publish one new original Persian channel post after startup while its polling
request is outstanding:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_bot_probe --live --exclusive-test-bot --duration 60 --poll-seconds 20 --limit 100
```

Check original text, chat/message IDs and publication time against the controlled
channel. `VERIFIED` still requires successful real preflight and a new original
authorized channel post within the existing freshness window. Queue management
cannot grant that status. The normal probe does not acknowledge the new post;
repeat runs may return it again as an older queued message.

## Limitations and recovery

- This is an experimental, operator-driven prefix workflow, not a durable
  production consumer or background worker. Only documented Bale offset
  semantics are used; acknowledgement has not been exercised against the real
  provider in this implementation session.
- Queue checks cannot be atomic with the remote offset request. There is no
  documented compare-and-set/conditional acknowledgement. Safety requires the
  dedicated single-consumer bot and provider ordering semantics; the tool cannot
  protect against another consumer racing or a provider violating its contract.
- Missing/expired/malformed or unknown events still block progress. Explicit
  review accepts only understood messages and recognized service envelopes;
  it cannot override other structural blockers. Preserve the journal and resolve provider/schema questions
  separately. New unreviewed updates above the boundary remain pending.
- Use a private local staging folder, outside version control, with adequate
  space. `.tmp` is ignored here. Files are created with restrictive POSIX mode;
  Windows access is governed by the parent folder's ACL, which this tool does
  not configure. Receipts hold original private payloads, possibly sensitive
  content; do not publish them. HMACs detect receipt changes/token mismatch,
  but are not encryption or protection against an owner who already has the token.
- Do not copy/rename an attempted receipt to bypass its attempt marker, remove
  markers to retry, or run competing acknowledgements. The one-shot protection
  is local to the receipt path, not a server-side idempotency guarantee.
- After `UNKNOWN` or a crash, keep all files. A read-only fresh inspection can
  reveal remaining pending IDs, but may not prove whether an absent update was
  acknowledged, expired or handled by another consumer. No blind retry occurs.
- An empty queue is a momentary observation. New setup/chat events can cause
  the single normal polling request to return early before a new post arrives.
  Machine clock skew can still affect freshness. All prior verification
  requirements remain intact.

## Verification

New tests use synthetic clients and mocked HTTP only. They cover exact offset
derivation, zero and partial prefixes, incorrect boundaries, confirmation,
unexpected/unauthorized/malformed events, changed prefixes, token/scope/bot
binding, receipt tampering/expiry, active webhooks, journal failure, uncertain
outcomes, no retries, returned-unacknowledged events, empty inspections and
Telegram/normal-probe isolation.
The review extension adds valid/invalid zero-ID services, unauthorized-chat
review without allowlist changes, exact per-ID approvals, duplicate/missing
approvals, review tampering/binding, expired inspections, fresh-arrival retention,
changed prefixes and separate local-review/irreversible-confirmation tests.

Actual verification on 2026-10-29 with the existing Python 3.12.14 environment:

| Check | Result |
|---|---|
| Full pytest suite, including the cached MiniLM integration test | **623 passed in 38.41 seconds** |
| New review-extension cases within that suite | **31 passed**, alongside the previous 592 cases |
| Ruff lint | All checks passed |
| Ruff format check | 100 files already formatted |
| Dependency validation | No broken requirements found |
| Protected-file snapshot | 111 files checked; six intended files changed and 105 previous files unchanged |
| Production SQLite hash | Unchanged: `66de7540c2d36e84a48127331f3e63443ba9dba65c9896863fb838847e3cad8b` |

The new review regression file is an addition outside the snapshot. Original
inspection receipts, Telegram/shared parser code and production SQLite are
unchanged. CLI help and the documented list of six unique approvals were checked
without API access. No real inspection, review approval, acknowledgement or new
live freshness verification was performed.

Code entry points: `bale_diagnostics.py:61` (service classification),
`bale_queue.py:269` (acknowledgement) and `bale_queue.py:381` (local review).
Reproduction commands:

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

The optional semantic test uses the existing cached model. Existing async and
Streamlit tests require local loopback socket support. No model download or new
dependency was added for this workflow.
