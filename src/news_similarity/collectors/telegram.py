"""Authorized Telegram history collection using Telethon's asynchronous API."""

import asyncio
import logging
import re
import sqlite3
import sys
from collections.abc import Awaitable, Callable
from contextlib import redirect_stdout
from getpass import getpass
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

from telethon import TelegramClient, errors, types

from news_similarity.config import Settings
from news_similarity.records import CollectionBatch, NewsItem

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CollectionError(RuntimeError):
    """A safe-to-display Telegram error without API payloads or credentials."""


def channel_reference(value: str) -> str | int:
    """Accept a username, public channel URL or cached Telegram channel peer ID."""
    value = value.strip()
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        if (
            parsed.netloc not in {"t.me", "telegram.me"}
            or parsed.query
            or parsed.fragment
        ):
            raise CollectionError(
                "Use a Telegram channel username or public channel URL."
            )
        value = parsed.path.strip("/")
    if re.fullmatch(r"-100[0-9]+", value):
        return int(value)
    value = value.removeprefix("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", value):
        raise CollectionError(
            "Invalid channel. Use @username, https://t.me/username, "
            "or an authorized cached -100... channel ID."
        )
    return value


def message_to_news(message: object, channel: types.Channel) -> NewsItem | None:
    """Keep text and captions exactly; skip service, empty and invalid messages."""
    if not isinstance(message, types.Message):
        return None
    text = message.message
    if not isinstance(text, str) or not text.strip():
        return None
    if message.id <= 0 or message.date is None:
        raise ValueError("Message lacks a valid ID or publication timestamp.")
    username = channel.username
    return NewsItem(
        platform="telegram",
        channel_id=str(channel.id),
        channel_name=channel.title,
        message_id=str(message.id),
        text=text,
        published_at=message.date,
        url=f"https://t.me/{username}/{message.id}" if username else None,
    )


def safe_error(error: Exception) -> str:
    """Avoid rendering exception text that may contain phone numbers or requests."""
    if isinstance(error, CollectionError):
        return str(error)
    if isinstance(error, errors.FloodWaitError):
        return f"Telegram requires a wait of {error.seconds} seconds. Retry later."
    if isinstance(error, (errors.UnauthorizedError, errors.AuthKeyError)):
        return (
            "Telegram authentication failed. Check credentials and the saved session."
        )
    if isinstance(error, (errors.ForbiddenError, errors.BadRequestError, ValueError)):
        return (
            "Telegram rejected the request. Check the channel and account permissions."
        )
    if isinstance(error, (OSError, sqlite3.Error)):
        return (
            "Telegram connection or session storage failed. "
            "Check connectivity and paths."
        )
    if isinstance(error, (EOFError, RuntimeError)):
        return (
            "Telegram authentication needs an interactive terminal or a valid session."
        )
    return f"Telegram operation failed ({type(error).__name__})."


class TelegramCollector:
    def __init__(
        self,
        settings: Settings,
        *,
        client: TelegramClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_flood_wait: int = 60,
        max_flood_retries: int = 2,
    ) -> None:
        api_id, api_hash = settings.require_telegram()
        if max_flood_wait < 0 or max_flood_retries < 0:
            raise ValueError("Flood wait bounds cannot be negative.")
        if client is None:
            Path(settings.telegram_session_name).parent.mkdir(
                parents=True, exist_ok=True
            )
            client = TelegramClient(
                settings.telegram_session_name,
                api_id,
                api_hash,
                flood_sleep_threshold=0,
                request_retries=2,
                connection_retries=2,
                raise_last_call_error=True,
                receive_updates=False,
            )
        self.client = client
        self.sleep = sleep
        self.max_flood_wait = max_flood_wait
        self.max_flood_retries = max_flood_retries

    async def _wait(self, error: errors.FloodWaitError, retries: int) -> None:
        if error.seconds > self.max_flood_wait or retries >= self.max_flood_retries:
            raise CollectionError(
                f"Telegram requires a wait of {error.seconds} seconds; "
                "automatic retry limit reached. Retry later."
            ) from None
        logger.warning("Telegram rate limit: waiting %d seconds.", error.seconds)
        await self.sleep(error.seconds)

    async def _with_flood_wait(self, operation: Callable[[], Awaitable[T]]) -> T:
        retries = 0
        while True:
            try:
                return await operation()
            except errors.FloodWaitError as error:
                await self._wait(error, retries)
                retries += 1

    async def collect(self, channel: str, limit: int = 30) -> CollectionBatch:
        if limit <= 0:
            raise ValueError("limit must be positive.")
        batch = CollectionBatch(platform="telegram", channel_name=channel)
        try:
            reference = channel_reference(channel)
        except CollectionError as error:
            batch.errors.append(str(error))
            return batch

        try:
            # No codes, phone numbers, API hashes or 2FA passwords enter our logs.
            # Telethon prints a first-login greeting; reserve stdout for JSON.
            with redirect_stdout(sys.stderr):
                await self.client.start(
                    phone=lambda: getpass(
                        "Telegram phone number (with country code): "
                    ),
                    code_callback=lambda: getpass("Telegram login code: "),
                    password=lambda: getpass(
                        "Telegram two-step verification password: "
                    ),
                )
            entity = await self._with_flood_wait(
                lambda: self.client.get_entity(reference)
            )
            if not isinstance(entity, types.Channel):
                raise CollectionError(
                    "The target must be a Telegram channel or supergroup."
                )
            batch.channel_id = str(entity.id)
            batch.channel_name = entity.title
            batch.channel_url = (
                f"https://t.me/{entity.username}" if entity.username else None
            )

            offset_id = 0
            retries = 0
            while batch.total_fetched < limit:
                try:
                    async for message in self.client.iter_messages(
                        entity,
                        limit=limit - batch.total_fetched,
                        offset_id=offset_id,
                        wait_time=1,
                    ):
                        batch.total_fetched += 1
                        offset_id = message.id
                        try:
                            item = message_to_news(message, entity)
                        except (ValueError, TypeError):
                            batch.skipped += 1
                            batch.errors.append(
                                f"Message {message.id}: invalid ID or timestamp."
                            )
                            continue
                        if item is None:
                            batch.skipped += 1
                        else:
                            batch.items.append(item)
                    break
                except errors.FloodWaitError as error:
                    await self._wait(error, retries)
                    retries += 1
        except (
            errors.RPCError,
            OSError,
            sqlite3.Error,
            ValueError,
            RuntimeError,
            EOFError,
        ) as error:
            batch.errors.append(safe_error(error))
            logger.error("%s", batch.errors[-1])
        finally:
            try:
                await self.client.disconnect()
            except (errors.RPCError, OSError, sqlite3.Error, RuntimeError) as error:
                batch.errors.append(f"Disconnect: {safe_error(error)}")
        return batch
