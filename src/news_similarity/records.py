"""Shared records, independent of the database and messaging SDKs."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class NewsItem:
    platform: str
    channel_id: str
    channel_name: str | None
    message_id: str
    text: str
    published_at: datetime
    url: str | None = None

    def __post_init__(self) -> None:
        for name in ("platform", "channel_id", "message_id", "text"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string.")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware.")
        object.__setattr__(self, "published_at", self.published_at.astimezone(UTC))


@dataclass
class CollectionBatch:
    platform: str
    channel_id: str | None = None
    channel_name: str | None = None
    channel_url: str | None = None
    total_fetched: int = 0
    skipped: int = 0
    items: list[NewsItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class CollectionSummary:
    channel_name: str | None
    total_fetched: int
    valid_news_items: int
    newly_inserted: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
