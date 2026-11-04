"""Store-before-confirm one-shot bot collection with restartable durable inbox."""

import time
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from news_similarity.collectors.bot_api import BotCollectionConfig, bot_lock
from news_similarity.config import Settings
from news_similarity.database.bot_storage import BotStorage
from news_similarity.database.repository import NewsRepository
from news_similarity.integrations.bot_parsing import integer
from news_similarity.integrations.bot_probe import ProbeError
from news_similarity.integrations.probe_cli import sanitized_json


class BotCollectionService:
    def __init__(self, repository, collector):
        self.repository, self.collector = repository, collector
        self.storage = BotStorage(repository)

    def collect(self, *, exclusive_test_bot=False, acknowledge_stored=False):
        result = {
            "platform": self.collector.platform,
            "status": "BLOCKED",
            "acknowledged": False,
            "inserted": 0,
            "duplicates": 0,
            "evidence_origin": "live_http"
            if self.collector.real_transport
            else "mocked",
        }
        if exclusive_test_bot is not True:
            result["reason"] = (
                "Assert exclusive bot ownership with --exclusive-test-bot."
            )
            return result
        config = self.collector.config
        client = self.collector.client
        deadline = time.monotonic() + config.duration

        def timeout(maximum=8):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("Collection deadline reached.")
            return min(remaining, maximum)

        def call(method, parameters=None):
            return client.call(method, parameters or {}, timeout())

        try:
            me = call("getMe")
            if not isinstance(me, dict) or me.get("is_bot") is not True:
                raise ProbeError("Authentication did not identify a bot.")
            bot_id = integer(me.get("id"), minimum=1)
            with bot_lock(config.platform, bot_id, config.lock_dir):
                webhook = call("getWebhookInfo")
                if not isinstance(webhook, dict) or not isinstance(
                    webhook.get("url"), str
                ):
                    raise ProbeError("Invalid webhook response.")
                if webhook["url"]:
                    raise ProbeError(
                        "Active webhook; collection stopped without changing it."
                    )
                for chat_id in sorted(config.authorized_ids):
                    chat = call("getChat", {"chat_id": int(chat_id)})
                    if (
                        not isinstance(chat, dict)
                        or str(integer(chat.get("id"))) != chat_id
                        or chat.get("type") != "channel"
                    ):
                        raise ProbeError(
                            "Authorized channel identity/type was not established."
                        )
                    if config.platform == "telegram":
                        member = call(
                            "getChatMember",
                            {"chat_id": int(chat_id), "user_id": bot_id},
                        )
                        if (
                            not isinstance(member, dict)
                            or member.get("status")
                            not in {"member", "administrator", "creator"}
                            or not isinstance(member.get("user"), dict)
                            or integer(member["user"].get("id")) != bot_id
                        ):
                            raise ProbeError(
                                "Telegram bot channel membership was not established."
                            )
                self.storage.initialize()
                wait = max(
                    0, min(config.poll_seconds, int(deadline - time.monotonic()) - 1)
                )
                updates = client.poll(config.limit, wait, timeout(25))
                if not isinstance(updates, list) or len(updates) > config.limit:
                    raise ProbeError(
                        "Provider batch exceeds the requested limit or is malformed."
                    )
                result.update(self.storage.ingest(self.collector, bot_id, updates))
                result["received_updates"] = len(updates)
                candidate = result["next_offset"]
                if acknowledge_stored is True and candidate is not None:
                    # Commit intent and all lower results before the API call.
                    self.storage.mark(
                        config.platform, bot_id, "ACK_PENDING", intent=candidate
                    )
                    try:
                        pending = client.poll(1, 0, timeout(), offset=candidate)
                        valid = (
                            isinstance(pending, list)
                            and len(pending) <= 1
                            and all(
                                isinstance(u, dict)
                                and type(u.get("update_id")) is int
                                and u["update_id"] >= candidate
                                for u in pending
                            )
                        )
                        if not valid:
                            if isinstance(pending, list) and len(pending) <= 100:
                                self.storage.ingest(
                                    self.collector, bot_id, pending, process=False
                                )
                            raise ProbeError(
                                "Acknowledgement response violates "
                                "the requested boundary."
                            )
                        # Journal new updates; never acknowledge them in this run.
                        after = self.storage.ingest(
                            self.collector,
                            bot_id,
                            pending,
                            process=False,
                            acknowledged_offset=candidate,
                        )
                        result.update(
                            status="BLOCKED"
                            if after["blocked_updates"]
                            else "ACKNOWLEDGED",
                            acknowledged=True,
                            acknowledged_offset=candidate,
                            pending_updates=after["pending_updates"],
                            blocked_updates=after["blocked_updates"],
                            next_offset=after["next_offset"],
                        )
                    except (
                        ProbeError,
                        SQLAlchemyError,
                        ValueError,
                        TypeError,
                        OSError,
                        OverflowError,
                    ):
                        # It may have applied; durable results make replay safe.
                        try:
                            self.storage.mark(config.platform, bot_id, "ACK_UNKNOWN")
                        except (SQLAlchemyError, OSError):
                            pass  # ACK_PENDING intent was already durable.
                        result.update(
                            status="ACK_UNKNOWN",
                            acknowledged=None,
                            reason="Acknowledgement may have applied; "
                            "durable intent retained.",
                        )
                return result
        except ProbeError as error:
            result["reason"] = str(error)
        except (SQLAlchemyError, ValueError, TypeError, OSError, OverflowError):
            result.update(
                status="ERROR",
                reason="Collection/storage failed; no new acknowledgement sent.",
            )
        return result


def collection_status(database_url):
    database = make_url(database_url).database
    if not database or database == ":memory:" or not Path(database).is_file():
        return []
    repository = NewsRepository(database_url, read_only=True)
    try:
        return BotStorage(repository).status()
    finally:
        repository.close()


def run_cli(args):
    repository = None
    token = None
    try:
        if args.command == "collection-status":
            settings = Settings.load(args.env_file)
            report = {
                "collectors": collection_status(settings.database_url),
                "note": "Durable history; no current connection check "
                "or probe verification.",
            }
        else:
            if args.acknowledge_stored:
                import sys

                print(
                    "IRREVERSIBLE: confirm only the durably processed bot prefix; "
                    "pending API replay for that prefix becomes unavailable.",
                    file=sys.stderr,
                    flush=True,
                )
            from news_similarity.collectors.bale import BaleBotCollector
            from news_similarity.collectors.telegram_bot import TelegramBotCollector

            platform = "telegram" if args.command == "collect-telegram-bot" else "bale"
            config = BotCollectionConfig.load(
                platform,
                args.bot_env_file,
                limit=args.limit,
                duration=args.duration,
                poll_seconds=args.poll_seconds,
            )
            token = config.token
            if not args.exclusive_test_bot:
                raise ProbeError(
                    "--exclusive-test-bot is required before production polling."
                )
            settings = Settings.load(args.env_file)
            repository = NewsRepository(settings.database_url)
            collector = (
                TelegramBotCollector if platform == "telegram" else BaleBotCollector
            )(config)
            report = BotCollectionService(repository, collector).collect(
                exclusive_test_bot=True,
                acknowledge_stored=args.acknowledge_stored,
            )
    except (ProbeError, ValueError, TypeError, OSError, SQLAlchemyError):
        report = {
            "status": "BLOCKED",
            "reason": "Configuration, channel scope or storage unavailable.",
            "acknowledged": False,
        }
    finally:
        if repository is not None:
            repository.close()
    print(sanitized_json(report, token))
    if report.get("status") == "ACK_UNKNOWN":
        return 3
    return 2 if report.get("status") in {"BLOCKED", "ERROR"} else 0
