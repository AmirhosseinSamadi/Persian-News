"""Explicit Bale-only prefix acknowledgement, isolated from normal probes."""

import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from news_similarity.integrations.bale_diagnostics import diagnose_update
from news_similarity.integrations.bot_parsing import integer
from news_similarity.integrations.bot_probe import MAX_BYTES, HttpBotClient, ProbeError

WARNING = (
    "IRREVERSIBLE: acknowledgement removes pending API replay for ALL Bale bot "
    "updates through the selected ID, across chats and event types. It cannot "
    "be undone and may affect other consumers. It does not delete channel posts. "
    "Use only an exclusive dedicated test bot and review the saved receipt first."
)
RECEIPT_MAX_AGE = 900


class AcknowledgementUncertain(ProbeError):
    """A request may have reached Bale; automatic replay is prohibited."""


class BaleQueueClient(HttpBotClient):
    def __init__(self, config):
        if config.platform != "bale":
            raise ProbeError("Queue acknowledgement is restricted to Bale.")
        super().__init__(config)

    def acknowledge(self, highest_id, timeout):
        integer(highest_id, minimum=0)
        return self._request(
            "getUpdates",
            {"offset": highest_id + 1, "limit": 100, "timeout": 0},
            timeout,
        )


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _signature(payload, token):
    return hmac.new(
        token.encode("utf-8"), _canonical(payload), hashlib.sha256
    ).hexdigest()


def _write_new(path, document):
    # O_EXCL prevents overwriting receipts/attempt markers, including symlink targets.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_canonical(document))
        stream.flush()
        os.fsync(stream.fileno())


def _summary(updates, authorized_ids):
    if not isinstance(updates, list) or len(updates) > 100:
        raise ProbeError("Invalid or oversized Bale update batch.")
    rows, previous = [], None
    for update in updates:
        row = {
            "update_id": None,
            "event_type": "unsupported",
            "chat_type": None,
            "chat_id": None,
            "blockers": [],
            "diagnostics": diagnose_update(update),
        }
        try:
            identifier = integer(update.get("update_id"), minimum=0)
            row["update_id"] = identifier
            if previous is not None and identifier != previous + 1:
                row["blockers"].append("non_contiguous_or_reordered_ids")
            previous = identifier
            keys = set(update) - {"update_id"}
            if len(keys) != 1:
                raise ValueError
            event = next(iter(keys))
            if event not in {"message", "edited_message"}:
                row["event_type"] = (
                    event
                    if event in {"callback_query", "pre_checkout_query"}
                    else "unsupported"
                )
                query = update[event]
                if event == "callback_query" and isinstance(query, dict):
                    message = query.get("message")
                    chat = message.get("chat") if isinstance(message, dict) else None
                    if isinstance(chat, dict):
                        row["chat_id"] = str(integer(chat.get("id")))
                        kind = chat.get("type")
                        row["chat_type"] = (
                            kind if kind in ("private", "group", "channel") else None
                        )
                raise ValueError
            row["event_type"] = event
            message = update[event]
            chat = message["chat"]
            row["chat_id"] = str(integer(chat["id"]))
            kind = chat.get("type")
            if kind not in ("private", "group", "channel"):
                raise ValueError
            row["chat_type"] = kind
            if row["chat_id"] not in authorized_ids:
                row["blockers"].append("chat_not_authorized")
            service = row["diagnostics"].get("service_classification")
            if service == "invalid_membership_service":
                raise ValueError
            recognized = service in {"membership_group", "membership_channel_review"}
            integer(message.get("message_id"), minimum=0 if recognized else 1)
            integer(message.get("date"), minimum=0)
            if recognized:
                row["blockers"].append("service_review_required")
            if service == "membership_channel_review":
                row["blockers"].append("uncertain_channel_service")
            for key in ("text", "caption"):
                value = message.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError
                    value.encode("utf-8")
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            row["blockers"].append("unsupported_or_malformed_update")
        rows.append(row)
    return rows


def _public_rows(rows):
    """Keep chat identifiers inside authorization checks and private receipts."""
    return [
        {key: value for key, value in row.items() if key != "chat_id"} for row in rows
    ]


def diagnose_receipt(receipt_path):
    """Offline shape review, never an authenticated receipt or queue action."""
    path = Path(receipt_path)
    if path.stat().st_size > 2 * MAX_BYTES:
        raise ProbeError("Inspection receipt exceeds the size limit.")
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = document.get("payload") if isinstance(document, dict) else None
    if not isinstance(payload, dict) or payload.get("platform") != "bale":
        raise ProbeError("A Bale inspection receipt is required.")
    scope = payload.get("authorized_ids")
    if not isinstance(scope, list) or not all(
        isinstance(value, str) for value in scope
    ):
        raise ProbeError("Invalid recorded authorization scope.")
    rows = _summary(payload.get("updates"), frozenset(scope))
    return {
        "platform": "bale",
        "operation": "diagnose",
        "status": "DIAGNOSED",
        "provenance": "Saved receipt structure only; not current queue state.",
        "receipt_signature_verified": False,
        "authorization_scope_source": "unverified_saved_receipt",
        "updates": _public_rows(rows),
        "network_requests": 0,
        "acknowledged": False,
        "production_database_written": False,
    }


def _session(config, exclusive_test_bot, client):
    if config.platform != "bale" or not config.token or not config.authorized_ids:
        raise ProbeError("Bale token and explicit authorized chat IDs are required.")
    if exclusive_test_bot is not True:
        raise ProbeError("--exclusive-test-bot is required for queue operations.")
    client = client if client is not None else BaleQueueClient(config)
    deadline = time.monotonic() + config.duration

    def timeout():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("Queue operation deadline reached.")
        return min(remaining, 8)

    def call(method, parameters=None):
        return client.call(method, parameters or {}, timeout())

    me = call("getMe")
    if not isinstance(me, dict) or me.get("is_bot") is not True:
        raise ProbeError("Bale authentication did not identify a bot.")
    bot_id = integer(me.get("id"), minimum=1)
    webhook = call("getWebhookInfo")
    if not isinstance(webhook, dict) or not isinstance(webhook.get("url"), str):
        raise ProbeError("Invalid webhook metadata.")
    if webhook["url"]:
        raise ProbeError("Existing webhook is active; queue operation stopped.")
    return client, bot_id, call, timeout


def inspect_queue(config, receipt_path, *, exclusive_test_bot=False, client=None):
    path = Path(receipt_path)
    if path.exists():
        raise ProbeError("Inspection receipt already exists; choose a new file.")
    _, bot_id, call, _ = _session(config, exclusive_test_bot, client)
    updates = call("getUpdates", {"limit": 100, "timeout": 0})
    rows = _summary(updates, config.authorized_ids)
    payload = {
        "version": 1,
        "platform": "bale",
        "bot_id": bot_id,
        "authorized_ids": sorted(config.authorized_ids),
        "inspected_at": datetime.now(UTC).isoformat(),
        "updates": updates,
    }
    _write_new(
        path, {"payload": payload, "signature": _signature(payload, config.token)}
    )
    through = None
    for row in rows:
        if row["blockers"]:
            break
        through = row["update_id"]
    return {
        "platform": "bale",
        "operation": "inspect",
        "status": "INSPECTED",
        "queue_empty": not updates,
        "updates": _public_rows(rows),
        "receipt": str(path),
        "acknowledgeable_through": through,
        "approval_required_for_all_updates": True,
        "acknowledgement_ready": False,
        "batch_at_limit": len(updates) == 100,
        "acknowledged": False,
        "production_database_written": False,
    }


def _load_receipt(path, config):
    if path.stat().st_size > 2 * MAX_BYTES:
        raise ProbeError("Inspection receipt exceeds the size limit.")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise ProbeError("Invalid inspection receipt structure.")
    payload, signature = document["payload"], document["signature"]
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _signature(payload, config.token)
    ):
        raise ProbeError("Receipt integrity/token binding failed; inspect again.")
    if (
        payload.get("version") != 1
        or payload.get("platform") != "bale"
        or payload.get("authorized_ids") != sorted(config.authorized_ids)
    ):
        raise ProbeError("Receipt platform or authorized scope does not match.")
    age = (
        datetime.now(UTC) - datetime.fromisoformat(payload["inspected_at"])
    ).total_seconds()
    if not 0 <= age <= RECEIPT_MAX_AGE:
        raise ProbeError("Receipt is expired or future-dated; inspect again.")
    return payload


def acknowledge_queue(
    config,
    receipt_path,
    highest_id,
    *,
    confirm_irreversible=False,
    exclusive_test_bot=False,
    client=None,
    review_file=None,
):
    if config.platform != "bale" or not config.token:
        raise ProbeError("Only a configured Bale bot can acknowledge this queue.")
    if confirm_irreversible is not True:
        raise ProbeError("Explicit --confirm-irreversible is required. " + WARNING)
    integer(highest_id, minimum=0)
    path = Path(receipt_path)
    attempt_path = path.with_name(path.name + ".ack-attempt.json")
    result_path = path.with_name(path.name + ".ack-result.json")
    if attempt_path.exists() or result_path.exists():
        raise ProbeError("This receipt has an acknowledgement attempt; inspect anew.")
    payload = _load_receipt(path, config)
    prefix = _reviewable_prefix(payload, highest_id, config.authorized_ids)
    if review_file is None:
        raise ProbeError(
            "Unexpected/unapproved prefix: an explicit --review-file is required."
        )
    review = _load_review(Path(review_file), config, payload, highest_id, prefix)
    client, bot_id, call, timeout = _session(config, exclusive_test_bot, client)
    if bot_id != payload["bot_id"]:
        raise ProbeError("Receipt belongs to a different bot.")
    current = call("getUpdates", {"limit": 100, "timeout": 0})
    current_rows = _summary(current, config.authorized_ids)
    if any(row["update_id"] is None for row in current_rows):
        raise ProbeError("Reinspection contains invalid IDs; acknowledgement stopped.")
    current_prefix = [u for u in current if u["update_id"] <= highest_id]
    if _canonical(current_prefix) != _canonical(prefix):
        raise ProbeError("Pending prefix changed since inspection; inspect again.")
    # Durable intent precedes the irreversible request. Never retry this receipt.
    _write_new(
        attempt_path,
        {
            "platform": "bale",
            "bot_id": bot_id,
            "acknowledged_through": highest_id,
            "requested_offset": highest_id + 1,
            "outcome": "unknown_until_result",
            "revalidated_updates": current,
            "created_at": datetime.now(UTC).isoformat(),
            "approved_update_ids": review["approved_update_ids"],
            "review_digest": hashlib.sha256(_canonical(review)).hexdigest(),
            "acknowledgement_only": True,
        },
    )
    try:
        remaining = client.acknowledge(highest_id, timeout())
        _write_new(
            result_path,
            {
                "platform": "bale",
                "outcome": "api_success",
                "acknowledged_through": highest_id,
                "updates": remaining,
            },
        )
        remaining_rows = _summary(remaining, config.authorized_ids)
        if any(
            row["update_id"] is None or row["update_id"] <= highest_id
            for row in remaining_rows
        ):
            raise ProbeError(
                "Acknowledgement response violates the requested boundary."
            )
    except (ProbeError, ValueError, OSError, TypeError, OverflowError) as error:
        raise AcknowledgementUncertain(
            "Acknowledgement outcome UNKNOWN; the request may have applied. "
            "Do not retry this receipt. Inspect the queue with a new receipt."
        ) from error
    return {
        "platform": "bale",
        "operation": "acknowledge",
        "status": "ACKNOWLEDGED",
        "acknowledged_through": highest_id,
        "requested_offset": highest_id + 1,
        "queue_empty": not remaining,
        "returned_unacknowledged_updates": _public_rows(remaining_rows),
        "result_receipt": str(result_path),
        "production_database_written": False,
    }


def _reviewable_prefix(payload, highest_id, authorized_ids):
    integer(highest_id, minimum=0)
    rows = _summary(payload["updates"], authorized_ids)
    if highest_id not in [row["update_id"] for row in rows]:
        raise ProbeError("Acknowledgement boundary was not inspected in this receipt.")
    overridable = {
        "chat_not_authorized",
        "service_review_required",
        "uncertain_channel_service",
    }
    prefix = []
    for update, row in zip(payload["updates"], rows, strict=True):
        if row["update_id"] is None or set(row["blockers"]) - overridable:
            raise ProbeError(
                "Unexpected or malformed update prevents explicit prefix review."
            )
        prefix.append(update)
        if row["update_id"] == highest_id:
            break
    return prefix


def review_queue(
    config,
    receipt_path,
    review_file,
    highest_id,
    approved_ids,
    *,
    exclusive_test_bot=False,
):
    """Record per-update, acknowledgement-only approval locally; no API calls."""
    if config.platform != "bale" or not config.token or exclusive_test_bot is not True:
        raise ProbeError("Configured exclusive Bale test bot is required for review.")
    path = Path(receipt_path)
    payload = _load_receipt(path, config)
    prefix = _reviewable_prefix(payload, highest_id, config.authorized_ids)
    expected = [update["update_id"] for update in prefix]
    if not isinstance(approved_ids, list) or any(
        type(i) is not int or i < 0 for i in approved_ids
    ):
        raise ProbeError(
            "Explicit integer approval is required for each inspected update."
        )
    if len(approved_ids) != len(set(approved_ids)):
        raise ProbeError("Duplicate update approvals are not allowed.")
    if approved_ids != expected:
        raise ProbeError(
            "Approve every update in the exact inspected prefix, in order."
        )
    review = {
        "version": 1,
        "platform": "bale",
        "policy": "explicit-prefix-v1",
        "bot_id": payload["bot_id"],
        "acknowledged_through": highest_id,
        "inspection_digest": hashlib.sha256(_canonical(payload)).hexdigest(),
        "approved_update_ids": approved_ids,
        "acknowledgement_only": True,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    _write_new(
        Path(review_file),
        {"payload": review, "signature": _signature(review, config.token)},
    )
    return {
        "platform": "bale",
        "operation": "review",
        "status": "REVIEWED",
        "approved_update_ids": approved_ids,
        "approved_through": highest_id,
        "acknowledgement_only": True,
        "acknowledged": False,
        "network_requests": 0,
        "production_database_written": False,
    }


def _load_review(path, config, inspection, highest_id, prefix):
    if path.stat().st_size > 2 * MAX_BYTES:
        raise ProbeError("Review exceeds the size limit.")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise ProbeError("Invalid review structure.")
    review, signature = document["payload"], document["signature"]
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _signature(review, config.token)
    ):
        raise ProbeError("Review integrity/token binding failed.")
    expected = [update["update_id"] for update in prefix]
    if (
        review.get("version") != 1
        or review.get("platform") != "bale"
        or review.get("policy") != "explicit-prefix-v1"
        or review.get("bot_id") != inspection["bot_id"]
        or review.get("inspection_digest")
        != hashlib.sha256(_canonical(inspection)).hexdigest()
        or review.get("acknowledged_through") != highest_id
        or review.get("approved_update_ids") != expected
        or review.get("acknowledgement_only") is not True
    ):
        raise ProbeError("Review does not approve this exact inspection and prefix.")
    age = (
        datetime.now(UTC) - datetime.fromisoformat(review["reviewed_at"])
    ).total_seconds()
    if not 0 <= age <= RECEIPT_MAX_AGE:
        raise ProbeError("Review expired or future-dated; inspect and review again.")
    return review


def main(argv=None):
    """Separate opt-in CLI; the existing Bale probe never calls this workflow."""
    import sys

    from dotenv import dotenv_values

    from news_similarity.integrations.bot_probe import ProbeConfig
    from news_similarity.integrations.probe_cli import SafeParser, sanitized_json

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = SafeParser(description="Dedicated experimental Bale bot queue management.")
    parser.add_argument(
        "action", choices=("inspect", "diagnose", "review", "acknowledge")
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--env-file", default=".env.bot-probes")
    parser.add_argument("--exclusive-test-bot", action="store_true")
    parser.add_argument(
        "--ack-through",
        type=int,
        help="Highest inspected update ID to acknowledge, not an offset.",
    )
    parser.add_argument("--confirm-irreversible", action="store_true")
    parser.add_argument("--review-file", type=Path)
    parser.add_argument(
        "--approve-update",
        action="append",
        type=int,
        help="Explicitly approve one inspected update for acknowledgement only.",
    )
    parser.add_argument("--duration", type=int, default=30)
    args = parser.parse_args(argv)
    if args.action == "acknowledge":
        print(WARNING, file=sys.stderr, flush=True)
    token = None
    try:
        if args.action in {"inspect", "diagnose"} and (
            args.ack_through is not None
            or args.confirm_irreversible
            or args.review_file is not None
            or args.approve_update is not None
        ):
            raise ProbeError("Inspection cannot include acknowledgement arguments.")
        if args.action in {"review", "acknowledge"} and args.ack_through is None:
            raise ProbeError(
                "An explicit --ack-through highest inspected ID is required."
            )
        if args.action == "review" and (
            args.review_file is None
            or args.approve_update is None
            or args.confirm_irreversible
        ):
            raise ProbeError(
                "Review requires --review-file and individual --approve-update flags."
            )
        if args.action == "acknowledge" and args.approve_update is not None:
            raise ProbeError("Create a separate review file before acknowledgement.")
        if args.action == "diagnose":
            report = diagnose_receipt(args.receipt)
        else:
            values = {**dotenv_values(args.env_file, interpolate=False), **os.environ}
            token = (values.get("BALE_BOT_TOKEN") or "").strip() or None
            ids = frozenset(
                str(int(value.strip()))
                for value in (values.get("BALE_BOT_CHAT_IDS") or "").split(",")
                if value.strip()
            )
            config = ProbeConfig("bale", token, ids, duration=args.duration)
        if args.action == "inspect":
            report = inspect_queue(
                config, args.receipt, exclusive_test_bot=args.exclusive_test_bot
            )
        elif args.action == "review":
            report = review_queue(
                config,
                args.receipt,
                args.review_file,
                args.ack_through,
                args.approve_update,
                exclusive_test_bot=args.exclusive_test_bot,
            )
        elif args.action == "acknowledge":
            report = acknowledge_queue(
                config,
                args.receipt,
                args.ack_through,
                confirm_irreversible=args.confirm_irreversible,
                exclusive_test_bot=args.exclusive_test_bot,
                review_file=args.review_file,
            )
    except (
        ProbeError,
        ValueError,
        OSError,
        KeyError,
        TypeError,
        OverflowError,
        AttributeError,
        UnicodeError,
    ) as error:
        uncertain = isinstance(error, AcknowledgementUncertain)
        report = {
            "platform": "bale",
            "operation": args.action,
            "status": "UNKNOWN" if uncertain else "BLOCKED",
            "acknowledgement_outcome": "unknown" if uncertain else "not_sent",
            "reason": str(error)
            if isinstance(error, ProbeError)
            else "Invalid queue configuration/receipt or local file operation failed.",
            "production_database_written": False,
        }
    print(sanitized_json(report, token))
    return {"BLOCKED": 2, "UNKNOWN": 3}.get(report["status"], 0)


if __name__ == "__main__":
    raise SystemExit(main())
