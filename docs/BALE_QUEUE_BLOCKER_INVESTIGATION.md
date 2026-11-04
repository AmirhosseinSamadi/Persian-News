# Bale pending-update blocker investigation

Date: **2026-10-29**. Investigation used the existing locally saved six-update
inspection receipt. No bot token or payload value was printed. No live API
request, acknowledgement, deletion, webhook change or production write was made.
The original receipt is preserved; offline diagnostics do not establish the
queue's current state or authenticate an old receipt for acknowledgement.

## Findings from the saved receipt

| Update | Safe structural finding | Root cause / retained blocker |
|---|---|---|
| 1 | Private text message with positive message ID | Chat outside the recorded authorized scope |
| 2 | Group message; `new_chat_members` is an array; `message_id` is zero; required envelope fields present | Queue validator requires message ID >= 1; service notification gets generic malformed blocker. Authorization was checked later and consequently masked; both blockers are now reported |
| 3–4 | Group text messages with positive message IDs | Chats outside the recorded authorized scope |
| 5 | Channel message; `new_chat_members` is an array; `message_id` is zero; required envelope fields present | Same positive-ID rejection; the observed channel service scope is not explicitly documented |
| 6 | Channel text message with positive message ID | No structural or authorization blocker in the saved receipt |

No required `chat`, `date` or `message_id` field is missing from updates 2 or 5.
They are not malformed JSON and are not ordinary text posts missing a body.
Their service structure was hidden by the single generic exception handler.

The [official Bale Message table](https://docs.bale.ai/), accessed **2026-10-29**,
documents `new_chat_members` as an optional array of User objects for members
joining a **group**, including the bot itself. It describes `message_id` as an
integer unique in the conversation, without the application's explicit positive
minimum or a special definition for zero-valued service IDs. It does not
explicitly describe this membership field's channel-delivery semantics.

Thus update 2 has a documented membership-service field in the documented group
scope, with an observed zero message ID unsupported by our validator. Update 5
has the same service field in an observed channel scope. These are plausible
provider service notifications; their identity/acknowledgement policy must not be
inferred from the field name alone. Neither is converted into a fabricated news
item or silently reclassified as safe to acknowledge.

## Minimal changes

- Added `src/news_similarity/integrations/bale_diagnostics.py`: deterministic
  structural diagnostics using fixed field paths, type labels, known event/chat
  enums and explicit service/media variants. Reports missing fields, wrong
  types, unsupported zero IDs, invalid Unicode and unsupported service scope.
  It counts unknown keys without printing their names or values.
- Updated `src/news_similarity/integrations/bale_queue.py`: attaches diagnostics
  to queue summaries and adds an offline `diagnose` action. Printed inspection
  and acknowledgement-result rows omit chat IDs. User/member IDs, names,
  usernames, bodies, captions, file metadata, timestamps and signatures are not
  emitted by structural diagnostics. Only update IDs remain for correlation.
- Moved the existing chat-authorization check before the message-ID check, so
  an invalid/unsupported ID no longer hides an independent unauthorized-chat
  blocker. This tightens reporting; it never grants authorization.
- Added `tests/test_bale_diagnostics.py` with synthetic service variants and
  adversarial content. Updated the inspection-output expectation in
  `tests/test_bale_queue.py` to require redacted chat IDs and diagnostics.
- Updated README and added this report. Existing queue-management history and
  Telegram investigation reports are retained.

The shared `bot_parsing.py` remains unchanged. Its regular `NewsItem` decoder
also requires a positive message ID and cannot represent these service envelopes
as news; it must not be relaxed globally. Telegram code, normal verification
criteria, shared transport, production SQLite, NLP models and UI are unchanged.

## Safe review and acknowledgement boundary

The pending batch can now be reviewed through **sanitized structural evidence**.
It is **not cleared for acknowledgement**: updates 1, 3 and 4 remain unauthorized;
update 2 retains authorization and zero-ID blockers; update 5 retains its zero-ID
blocker plus a diagnostic about undocumented channel scope. A fresh inspection
of the same batch would still report `acknowledgeable_through: null`.

The HMAC, bot/scope binding, receipt age, selected-prefix checks, reinspection,
durable journals, explicit confirmation and one-shot/no-retry protections are
unchanged. Diagnostics do not clear any blocker or add an acknowledgement path.
The original complete private receipt is still required by that separate action.

`diagnose` deliberately requires **no credentials and makes no network calls**.
It reads a saved Bale receipt, reports `receipt_signature_verified: false`, and
labels the authorization scope as coming from the unverified saved receipt.
That permits reviewing expired receipts safely without misrepresenting them as
fresh, authenticated acknowledgement authority. It neither writes a new receipt
nor modifies the input file. Supplying acknowledgement flags to this action is
rejected. Current queue state requires a new read-only inspection.

Raw inspection receipts still contain original private payloads by design;
keep them in a private ignored directory and do not publish them. The redaction
applies to diagnostic/summary presentation, not to altering forensic evidence.

## Smallest compatible future parser improvement

Keep the implemented service-envelope classification separate from news
extraction. If zero-ID membership events are to be supported further, add a
**Bale-only typed service record**, identified by its update ID, for recognized
`new_chat_members` arrays with validated envelope/member structure. It should
not create a `NewsItem`, copy service IDs into news identity, invent text, or
change Telegram's positive-ID rules. Confirm zero-ID identity semantics and
channel scope with Bale before relaxing queue acceptance. Any future explicit
service acknowledgement must still require authorized scope, complete receipt
review and all existing prefix/confirmation protections. No such relaxation is
part of this change.

## Exact read-only commands

From the project directory, inspect the existing saved receipt offline:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_queue diagnose --receipt .tmp/bale-inspection-20261029-131401863.json
```

That command was executed during this investigation: it produced the six
redacted structural summaries above with zero network calls and no writes.

To verify the **current pending queue** using the privately configured Bale token
and existing authorized scope, run a fresh inspection with a unique receipt:

```powershell
$receipt = Join-Path '.tmp' ('bale-review-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '.json')
.\.venv\Scripts\python.exe -m news_similarity.integrations.bale_queue inspect --receipt $receipt --exclusive-test-bot
```

This sends no offset, never acknowledges anything and saves a new local private
receipt. It still checks authentication and refuses an active webhook. Do not
expand the allowlist just to remove a blocker. No acknowledgement command is
needed for this investigation.

## Verification

Tests cover group/channel zero-ID membership notifications, malformed member
arrays, missing envelope fields, wrong primitive types, unknown envelopes,
textless media, deterministic/non-mutating diagnostics, disclosure attempts in
unknown keys and nested content, offline CLI operation without credentials,
rejected acknowledgement flags and continued blocking of service updates.

Actual verification in the existing Python 3.12.14 environment:

| Check | Result |
|---|---|
| Complete suite including cached MiniLM integration | **592 passed in 36.52 seconds** |
| Added diagnostic cases | **25 passed** within the full suite |
| Ruff lint | All checks passed |
| Ruff format check | 98 files already formatted |
| Dependency validation | No broken requirements found |
| Protected-file comparison | 108 files checked; only Bale queue source, its output-expectation test and README changed; 105 previous files unchanged |
| Original saved receipt | Unchanged |
| Production SQLite | Unchanged SHA-256 `66de7540c2d36e84a48127331f3e63443ba9dba65c9896863fb838847e3cad8b` |

The diagnostic helper, new tests and this report are additions outside the
snapshot. Source entry points are `bale_diagnostics.py:61` (shape diagnostics),
`bale_queue.py:132` (identifier-free presentation), and `bale_queue.py:139`
(offline receipt inspection). No Telegram/shared parser source was changed.

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
