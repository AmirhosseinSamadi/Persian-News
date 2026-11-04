"""Bounded Bot API inspection without webhook changes or update acknowledgements."""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from news_similarity.integrations.bot_parsing import integer, parse_updates

BASE_URLS = {"telegram": "https://api.telegram.org", "bale": "https://tapi.bale.ai"}
METHODS = frozenset(
    {"getMe", "getWebhookInfo", "getChat", "getChatMember", "getUpdates"}
)
MAX_BYTES = 8_000_000


class ProbeError(RuntimeError):
    """Safe fixed diagnostic only; never include provider exception payloads."""


@dataclass(frozen=True)
class ProbeConfig:
    platform: str
    token: str | None = field(default=None, repr=False)
    authorized_ids: frozenset[str] = frozenset()
    duration: int = 30
    poll_seconds: int = 15
    limit: int = 20

    def __post_init__(self):
        if self.platform not in BASE_URLS:
            raise ProbeError("Unsupported platform.")
        if self.token is not None and (
            not isinstance(self.token, str)
            or not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{16,256}", self.token)
        ):
            raise ProbeError("Invalid bot token format in environment configuration.")
        if (
            not isinstance(self.authorized_ids, frozenset)
            or len(self.authorized_ids) > 5
            or any(
                not isinstance(value, str) or not re.fullmatch(r"-?[0-9]{1,20}", value)
                for value in self.authorized_ids
            )
        ):
            raise ProbeError(
                "Configure at most five explicit numeric authorized chat IDs."
            )
        for value, lower, upper in (
            (self.duration, 5, 60),
            (self.poll_seconds, 0, 20),
            (self.limit, 1, 100),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise ProbeError(
                    "Probe duration, polling timeout or batch "
                    "limit is outside safe bounds."
                )


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError(
            "API redirect refused; token-bearing requests stay "
            "on the official endpoint."
        )


class HttpBotClient:
    origin = "live_http"

    def __init__(self, config: ProbeConfig):
        if not config.token:
            raise ProbeError("A bot token is required for HTTP calls.")
        self._config = config
        self._opener = build_opener(_NoRedirect())
        self.requests = 0

    def call(self, method: str, parameters: dict, timeout: float):
        if method not in METHODS:
            raise ProbeError("Method is outside the read-only probe allowlist.")
        if method == "getUpdates" and set(parameters) - {"limit", "timeout"}:
            raise ProbeError(
                "Probe polling cannot send offsets or change allowed_updates."
            )
        return self._request(method, parameters, timeout)

    def _request(self, method: str, parameters: dict, timeout: float):
        """Shared sanitized transport; public probe calls retain their allowlist."""
        self.requests += 1
        address = f"{BASE_URLS[self._config.platform]}/bot{self._config.token}/{method}"
        request = Request(
            address,
            data=json.dumps(parameters).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ProbeError("API response exceeds the probe size limit.")
            document = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            # The URL and provider description may contain the secret token.
            retry_after = None
            try:
                body = json.loads(error.read(MAX_BYTES).decode("utf-8"))
                value = body.get("parameters", {}).get("retry_after")
                if type(value) is int and 0 <= value <= 86400:
                    retry_after = value
            except (ValueError, UnicodeError, AttributeError, TypeError):
                pass
            suffix = (
                f" Retry after {retry_after} seconds; no retry was attempted."
                if retry_after is not None
                else " No retry was attempted."
            )
            raise ProbeError(f"API HTTP failure ({error.code})." + suffix) from None
        except (URLError, OSError, TimeoutError, ValueError, UnicodeError):
            raise ProbeError(
                "API connection or response decoding failed; no retry was attempted."
            ) from None
        if (
            not isinstance(document, dict)
            or document.get("ok") is not True
            or "result" not in document
        ):
            raise ProbeError(
                "API rejected the request or returned an invalid envelope."
            )
        return document["result"]


def initial_report(config: ProbeConfig, mode: str) -> dict[str, Any]:
    return {
        "platform": config.platform,
        "mode": mode,
        "status": "DOCUMENTED_ONLY",
        "live_verified": False,
        "authentication_verified": False,
        "records": [],
        "dispositions": [],
        "network_requests": 0,
        "api_calls": 0,
        "requested_offset": None,
        "next_offset_candidate": None,
        "acknowledged_by_probe": False,
        "production_database_written": False,
        "subscription_policy": (
            "allowed_updates omitted; existing subscription unchanged"
        ),
        "limitations": [
            "An isolated experiment, not a production collector.",
            (
                "No offset, webhook mutation, backlog deletion or "
                "automatic retry is implemented."
            ),
            "Use a dedicated controlled bot with no other update consumer.",
        ],
    }


def preview_updates(
    config: ProbeConfig, updates: list, *, mode="offline"
) -> dict[str, Any]:
    report = initial_report(config, mode)
    parsed = parse_updates(config.platform, updates, config.authorized_ids)
    report.update(
        records=[record.to_dict() for record in parsed.records],
        dispositions=list(parsed.dispositions),
        next_offset_candidate=parsed.next_offset_candidate,
    )
    if config.platform == "bale":
        report["limitations"].append(
            "Bale message/edited_message parsing does not prove"
            " channel delivery or Telegram-specific update "
            "support."
        )
    return report


def _verification_evidence(records, started, observed_at):
    """Explain the existing freshness predicate without changing its bounds."""
    lower = int(started.timestamp())
    upper = observed_at.timestamp() + 5
    checks, eligible, counts = [], [], {}
    for record in records:
        published = datetime.fromisoformat(record["news"]["published_at"]).timestamp()
        reasons = []
        if record["chat_type"] != "channel":
            reasons.append("not_channel")
        if record["event_type"].startswith("edited_"):
            reasons.append("edited_update")
        if published < lower:
            reasons.append("published_before_probe")
        if published > upper:
            reasons.append("published_after_clock_tolerance")
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
        if not reasons:
            eligible.append(record["update_id"])
        checks.append(
            {
                "update_id": record["update_id"],
                "event_type": record["event_type"],
                "published_at": record["news"]["published_at"],
                "eligible_by_content": not reasons,
                "rejection_reasons": reasons,
            }
        )
    return {
        "probe_started_at": started.isoformat(),
        "observed_at": observed_at.isoformat(),
        "publication_not_before": datetime.fromtimestamp(lower, UTC).isoformat(),
        "publication_not_after": datetime.fromtimestamp(upper, UTC).isoformat(),
        "eligible_update_ids": eligible,
        "rejection_counts": counts,
        "records": checks,
    }


def live_probe(
    config: ProbeConfig,
    *,
    exclusive_test_bot: bool = False,
    client=None,
    clock=time.monotonic,
) -> dict[str, Any]:
    report = initial_report(config, "live")
    if not config.token or not config.authorized_ids or not exclusive_test_bot:
        report.update(
            status="BLOCKED",
            reason=(
                "Bot token, explicit authorized chat IDs and "
                "--exclusive-test-bot are required."
            ),
        )
        return report
    real_transport = client is None
    client = client if client is not None else HttpBotClient(config)
    started = datetime.now(UTC)
    deadline = clock() + config.duration

    def call(method, parameters=None):
        remaining = deadline - clock()
        if remaining <= 0:
            raise ProbeError("Bounded probe deadline reached.")
        return client.call(
            method,
            parameters or {},
            min(remaining, 25 if method == "getUpdates" else 8),
        )

    try:
        me = call("getMe")
        if not isinstance(me, dict) or me.get("is_bot") is not True:
            raise ProbeError("Authentication response does not identify a bot.")
        bot_id = integer(me.get("id"), minimum=1)
        report["authentication_verified"] = real_transport
        report["evidence_origin"] = "live_http" if real_transport else "injected_mock"
        webhook = call("getWebhookInfo")
        if not isinstance(webhook, dict) or not isinstance(webhook.get("url"), str):
            raise ProbeError("Webhook inspection returned invalid metadata.")
        if webhook["url"]:
            raise ProbeError(
                "An existing webhook is active. Polling was not"
                " attempted and webhook configuration was not "
                "changed."
            )
        for chat_id in sorted(config.authorized_ids):
            chat = call("getChat", {"chat_id": int(chat_id)})
            if not isinstance(chat, dict) or str(integer(chat.get("id"))) != chat_id:
                raise ProbeError(
                    "Authorized chat identity did not match the requested ID."
                )
            if config.platform == "telegram":
                if chat.get("type") != "channel":
                    raise ProbeError(
                        "Telegram probe requires an explicitly authorized channel."
                    )
                member = call(
                    "getChatMember", {"chat_id": int(chat_id), "user_id": bot_id}
                )
                if not isinstance(member, dict) or member.get("status") not in {
                    "member",
                    "administrator",
                    "creator",
                }:
                    raise ProbeError(
                        "Bot membership in an authorized channel was not established."
                    )
                user = member.get("user")
                if not isinstance(user, dict) or integer(user.get("id")) != bot_id:
                    raise ProbeError("Membership metadata did not identify this bot.")
            elif chat.get("type") not in {"private", "group", "channel"}:
                raise ProbeError("Bale chat metadata has an undocumented type.")
        poll_timeout = max(0, min(config.poll_seconds, int(deadline - clock()) - 1))
        updates = call("getUpdates", {"limit": config.limit, "timeout": poll_timeout})
        parsed_report = preview_updates(config, updates, mode="live")
        observed_at = datetime.now(UTC)
        report.update(
            records=parsed_report["records"],
            dispositions=parsed_report["dispositions"],
            next_offset_candidate=parsed_report["next_offset_candidate"],
        )
        report["polling"] = {
            "strategy": "single_batch_no_acknowledgement",
            "request_count": 1,
            "limit": config.limit,
            "updates_returned": len(updates),
            "batch_at_limit": len(updates) >= config.limit,
            "more_pending_updates": "unknown",
        }
        evidence = _verification_evidence(report["records"], started, observed_at)
        report["verification"] = evidence
        if config.platform == "bale":
            report["limitations"].append(
                "Channel delivery/admin requirements remain "
                "experimental until an actual controlled "
                "channel post is observed."
            )
        if evidence["eligible_update_ids"] and real_transport:
            report.update(status="VERIFIED", live_verified=True)
        else:
            report["reason"] = (
                "No new authorized channel post was verified in the single "
                "returned batch. See verification for per-record exclusions. "
                "The probe ends after one getUpdates request; queued updates "
                "can return immediately, and later posts are not inspected. "
                "No offset was sent or acknowledged. Injected mocks cannot "
                "establish live verification."
            )
    except ProbeError as error:
        # ProbeError messages are authored here; HTTP URLs, response descriptions
        # and underlying exception strings never enter them. CLI output also
        # redacts configured credentials if a message body happens to contain one.
        report.update(status="BLOCKED", reason=str(error))
    except (ValueError, TypeError, OverflowError, OSError):
        report.update(
            status="BLOCKED",
            reason=(
                "Probe preflight, authorization, transport or "
                "payload validation failed; no updates were "
                "acknowledged."
            ),
        )
    report["api_calls"] = getattr(client, "requests", 0)
    report["network_requests"] = report["api_calls"] if real_transport else 0
    return report
