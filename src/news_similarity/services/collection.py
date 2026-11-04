"""Coordinate collection and persistence, preserving partial failure details."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from news_similarity.collectors.base import NewsCollector
from news_similarity.database.repository import NewsRepository
from news_similarity.records import CollectionSummary

logger = logging.getLogger(__name__)


class CollectionService:
    def __init__(self, repository: NewsRepository, collector: NewsCollector) -> None:
        self.repository = repository
        self.collector = collector

    async def collect(self, channel: str, limit: int = 30) -> CollectionSummary:
        batch = await self.collector.collect(channel, limit)
        summary = CollectionSummary(
            channel_name=batch.channel_name,
            total_fetched=batch.total_fetched,
            valid_news_items=len(batch.items),
            skipped=batch.skipped,
            errors=list(batch.errors),
        )
        if batch.channel_id is not None:
            try:
                result = self.repository.save_news(
                    batch.platform,
                    batch.channel_id,
                    batch.channel_name,
                    batch.channel_url,
                    batch.items,
                )
                summary.newly_inserted = result.inserted
                summary.duplicates = result.duplicates
            except (SQLAlchemyError, ValueError):
                # SQLAlchemy exception text can include full article payloads.
                summary.errors.append(
                    "Database save failed; the entire batch was rolled back."
                )
        logger.info(
            "Collection finished: fetched=%d valid=%d inserted=%d duplicates=%d "
            "skipped=%d errors=%d",
            summary.total_fetched,
            summary.valid_news_items,
            summary.newly_inserted,
            summary.duplicates,
            summary.skipped,
            len(summary.errors),
        )
        return summary
