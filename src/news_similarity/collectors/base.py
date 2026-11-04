"""Small shared contract for explicitly triggered collection."""

from typing import Protocol

from news_similarity.records import CollectionBatch


class NewsCollector(Protocol):
    async def collect(self, channel: str, limit: int) -> CollectionBatch:
        """Fetch at most limit messages, reporting partial results and errors."""
        ...
