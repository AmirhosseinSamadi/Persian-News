"""Provider-specific update dispatch with a shared documented message shape."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from news_similarity.records import NewsItem

UPDATE_FIELDS = {
    "telegram": ("channel_post", "edited_channel_post"),
    "bale": ("message", "edited_message"),
}


@dataclass(frozen=True)
class ProbeRecord:
    update_id: int
    event_type: str
    chat_type: str
    news: NewsItem
    body_text: str | None
    caption: str | None
    edited_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document["news"]["published_at"] = self.news.published_at.isoformat()
        document["edited_at"] = self.edited_at.isoformat() if self.edited_at else None
        return document


@dataclass(frozen=True)
class ParsedUpdates:
    records: tuple[ProbeRecord, ...]
    dispositions: tuple[dict[str, Any], ...]
    next_offset_candidate: int | None


def integer(value, *, minimum=None) -> int:
    if type(value) is not int or minimum is not None and value < minimum:
        raise ValueError("Invalid integer field.")
    return value


def _timestamp(value):
    return datetime.fromtimestamp(integer(value, minimum=0), UTC)


def _optional_text(message, key):
    value = message.get(key)
    if value is not None:
        if not isinstance(value, str):
            raise ValueError("Invalid optional text.")
        value.encode("utf-8")  # Reject malformed Unicode scalars, not Persian text.
    return value


def _message_record(platform, update_id, event_type, message):
    if not isinstance(message, dict) or not isinstance(message.get("chat"), dict):
        raise ValueError("Missing message/chat object.")
    chat = message["chat"]
    chat_id = integer(chat.get("id"))
    message_id = integer(message.get("message_id"), minimum=1)
    chat_type = chat.get("type")
    allowed_types = (
        {"channel"} if platform == "telegram" else {"private", "group", "channel"}
    )
    if chat_type not in allowed_types:
        raise ValueError("Unsupported chat type.")
    body, caption = _optional_text(message, "text"), _optional_text(message, "caption")
    content = body if body is not None and body.strip() else caption
    if not content or not content.strip():
        return None
    title = _optional_text(chat, "title")
    published_at = _timestamp(message.get("date"))
    edited_at = (
        _timestamp(message["edit_date"])
        if message.get("edit_date") is not None
        else None
    )
    username = chat.get("username")
    url = None
    if (
        platform == "telegram"
        and isinstance(username, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", username)
    ):
        url = f"https://t.me/{username}/{message_id}"
    # No Bale post-link format is inferred from Telegram conventions.
    news = NewsItem(
        platform, str(chat_id), title, str(message_id), content, published_at, url
    )
    return ProbeRecord(update_id, event_type, chat_type, news, body, caption, edited_at)


def parse_updates(
    platform: str, updates: list, authorized_ids: frozenset[str]
) -> ParsedUpdates:
    if (
        platform not in UPDATE_FIELDS
        or not isinstance(updates, list)
        or len(updates) > 100
    ):
        raise ValueError("Unsupported platform or update batch.")
    if not authorized_ids:
        raise ValueError("Explicit authorized chat IDs are required.")
    fields = UPDATE_FIELDS[platform]
    records, dispositions, seen = [], [], {}
    blocked = False
    highest = None
    for update in updates:
        update_id = update.get("update_id") if isinstance(update, dict) else None
        try:
            integer(update_id, minimum=0)
        except ValueError:
            blocked = True
            dispositions.append({"update_id": None, "status": "invalid_update_id"})
            continue
        highest = max(highest, update_id) if highest is not None else update_id
        digest = hashlib.sha256(
            json.dumps(
                update, sort_keys=True, ensure_ascii=True, allow_nan=False
            ).encode()
        ).hexdigest()
        if update_id in seen:
            same_payload, first_status = seen[update_id]
            status = (
                "duplicate" if same_payload == digest else "inconsistent_duplicate_id"
            )
            if status != "duplicate" or first_status != "accepted":
                blocked = True
            dispositions.append({"update_id": update_id, "status": status})
            continue
        payload_keys = set(update) - {"update_id"}
        selected = [key for key in fields if key in update]
        status = "unsupported_update"
        if len(selected) == 1 and payload_keys == {selected[0]}:
            key, message = selected[0], update[selected[0]]
            try:
                chat = message.get("chat") if isinstance(message, dict) else None
                chat_id = (
                    str(integer(chat.get("id"))) if isinstance(chat, dict) else None
                )
                if chat_id not in authorized_ids:
                    status = "unrelated_chat"
                else:
                    record = _message_record(platform, update_id, key, message)
                    status = "accepted" if record else "no_text_or_caption"
                    if record:
                        records.append(record)
            except (ValueError, TypeError, OverflowError, OSError, UnicodeError):
                status = "malformed_message"
        if status != "accepted":
            blocked = True
        seen[update_id] = digest, status
        dispositions.append({"update_id": update_id, "status": status})
    # Informational only, never sent by the probes. Any unresolved queue item
    # prevents proposing advancement; unrelated payload content is never emitted.
    candidate = highest + 1 if highest is not None and not blocked else None
    return ParsedUpdates(tuple(records), tuple(dispositions), candidate)
