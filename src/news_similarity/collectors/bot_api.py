"""Bounded provider-aware Bot API reads; acknowledgements are explicit calls."""

import hashlib
import io
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from news_similarity.integrations.bale_diagnostics import SERVICE_FIELDS
from news_similarity.integrations.bot_parsing import integer, parse_updates
from news_similarity.integrations.bot_probe import (
    HttpBotClient,
    ProbeConfig,
    ProbeError,
)


class BotConfigurationError(ProbeError):
    """Fixed diagnostic code, with no credential or file contents attached."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"Bot configuration unavailable ({code}).")


@dataclass(frozen=True)
class BotCollectionConfig:
    platform: str
    token: str = field(repr=False)
    authorized_ids: frozenset[str]
    limit: int = 30
    duration: int = 30
    poll_seconds: int = 15
    lock_dir: Path = Path(".tmp/bot-locks")

    def __post_init__(self):
        ProbeConfig(
            self.platform,
            self.token,
            self.authorized_ids,
            self.duration,
            self.poll_seconds,
            self.limit,
        )
        if not self.token or not self.authorized_ids:
            raise ProbeError(
                "Bot token and numeric authorized channel IDs are required."
            )

    @classmethod
    def load(cls, platform, env_file=".env.bot-probes", **options):
        prefix = platform.upper()
        token_key = prefix + "_BOT_TOKEN"
        ids_key = prefix + (
            "_BOT_CHANNEL_IDS" if platform == "telegram" else "_BOT_CHAT_IDS"
        )
        try:
            try:
                text = Path(env_file).read_text(encoding="utf-8-sig")
            except FileNotFoundError:
                # Retain environment-only configuration when both required
                # fields are supplied explicitly by the process.
                if not (os.environ.get(token_key) and os.environ.get(ids_key)):
                    raise BotConfigurationError("file_load") from None
                text = ""
            except (OSError, UnicodeError):
                raise BotConfigurationError("file_load") from None
            if any(binding.error for binding in parse_stream(io.StringIO(text))):
                raise BotConfigurationError("file_load")
            values = {
                **dotenv_values(stream=io.StringIO(text), interpolate=False),
                **os.environ,
            }
            if values.get("NEWS_UI_DEMO_MODE") == "1":
                raise ProbeError(
                    "Production collection is disabled in synthetic demo mode."
                )
            token = (values.get(token_key) or "").strip()
            if not token:
                raise BotConfigurationError("missing_token")
            raw_ids = (values.get(ids_key) or "").strip()
            if not raw_ids:
                raise BotConfigurationError("missing_channels")
            try:
                ids = frozenset(
                    str(int(v.strip())) for v in raw_ids.split(",") if v.strip()
                )
                if not ids:
                    raise ValueError("No channel IDs.")
                ProbeConfig(platform, authorized_ids=ids)
            except (ValueError, ProbeError):
                raise BotConfigurationError("invalid_channels") from None
            try:
                ProbeConfig(platform, token)
            except ProbeError:
                raise BotConfigurationError("invalid_token") from None
            return cls(
                platform,
                token,
                ids,
                lock_dir=Path(values.get("NEWS_BOT_LOCK_DIR") or ".tmp/bot-locks"),
                **options,
            )
        except (ValueError, TypeError, OSError):
            raise BotConfigurationError("configuration") from None


@contextmanager
def bot_lock(platform, bot_id, directory):
    """OS advisory lock, released on process death; never delete its inode."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{platform}:{bot_id}".encode()).hexdigest()
    with (directory / (key + ".lock")).open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ProbeError(
                "Another local collector owns this bot; no polling attempted."
            ) from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class ProductionBotClient(HttpBotClient):
    def poll(self, limit, timeout, request_timeout, *, offset=None):
        integer(limit, minimum=1)
        integer(timeout, minimum=0)
        if limit > 100 or timeout > 20:
            raise ProbeError("Polling bounds exceeded.")
        parameters = {"limit": limit, "timeout": timeout}
        if offset is not None:
            parameters["offset"] = integer(offset, minimum=0)
        return self._request("getUpdates", parameters, request_timeout)


class BotUpdateCollector:
    platform = ""

    def __init__(self, config, client=None):
        if config.platform != self.platform:
            raise ProbeError("Collector platform does not match configuration.")
        self.config = config
        self.real_transport = client is None
        self.client = client if client is not None else ProductionBotClient(config)

    def classify(self, update):
        """Strict blocking policy: no service, edit or unknown event is news."""
        if not isinstance(update, dict):
            return "blocked_malformed", None
        keys = set(update) - {"update_id"}
        event = "channel_post" if self.platform == "telegram" else "message"
        edit = (
            "edited_channel_post" if self.platform == "telegram" else "edited_message"
        )
        if keys == {edit}:
            return "blocked_edit", None
        if keys != {event} or not isinstance(update.get(event), dict):
            return "blocked_unsupported", None
        message = update[event]
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return "blocked_malformed", None
        try:
            chat_id = str(integer(chat.get("id")))
        except ValueError:
            return "blocked_malformed", None
        if chat_id not in self.config.authorized_ids or chat.get("type") != "channel":
            return "blocked_unauthorized", None
        service_fields = set(SERVICE_FIELDS) | {
            "migrate_to_chat_id",
            "migrate_from_chat_id",
            "invoice",
        }
        if any(key in message for key in service_fields):
            return "blocked_service_skipped_as_news", None
        media_fields = {
            "photo",
            "document",
            "audio",
            "video",
            "animation",
            "voice",
            "sticker",
        }
        metadata = {
            "message_id",
            "date",
            "chat",
            "from",
            "sender_chat",
            "text",
            "caption",
            "entities",
            "caption_entities",
            "edit_date",
            "media_group_id",
            "reply_to_message",
            "reply_markup",
            "forward_from",
            "forward_from_chat",
            "forward_from_message_id",
            "forward_date",
            "author_signature",
        }
        if self.platform == "telegram":
            metadata |= {
                "forward_origin",
                "has_protected_content",
                "is_automatic_forward",
                "is_topic_message",
                "message_thread_id",
                "via_bot",
                "link_preview_options",
                "has_media_spoiler",
                "show_caption_above_media",
                "effect_id",
                "external_reply",
                "quote",
                "reply_to_story",
                "is_from_offline",
            }
        if set(message) - metadata - media_fields:
            return "blocked_unsupported_message_field", None
        try:
            integer(message.get("message_id"), minimum=1)
            integer(message.get("date"), minimum=0)
            datetime.fromtimestamp(message["date"], UTC)
            for key in media_fields & message.keys():
                media = message[key] if key == "photo" else [message[key]]
                if not isinstance(media, list) or not media:
                    raise ValueError
                for part in media:
                    if not isinstance(part, dict) or not isinstance(
                        part.get("file_id"), str
                    ):
                        raise ValueError
                    if not part["file_id"].strip():
                        raise ValueError
                    part["file_id"].encode("utf-8")
            parsed = parse_updates(self.platform, [update], self.config.authorized_ids)
        except (ValueError, TypeError, OverflowError, OSError, UnicodeError):
            return "blocked_malformed", None
        if parsed.records:
            return "news", parsed.records[0].news
        if (
            parsed.dispositions
            and parsed.dispositions[0]["status"] == "no_text_or_caption"
        ):
            return (
                "skipped_non_text"
                if media_fields & message.keys()
                else "blocked_unknown_textless_message"
            ), None
        return "blocked_malformed", None
