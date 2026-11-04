from dataclasses import replace
from unittest.mock import AsyncMock

from sqlalchemy.exc import OperationalError

from news_similarity.records import CollectionBatch
from news_similarity.services.collection import CollectionService


def collector_for(item, errors=None):
    batch = CollectionBatch(
        platform="telegram",
        channel_id=item.channel_id,
        channel_name=item.channel_name,
        total_fetched=3,
        skipped=1,
        items=[item, item],
        errors=errors or [],
    )
    collector = AsyncMock()
    collector.collect.return_value = batch
    return collector


async def test_statistics_and_repeated_collection(repository, item):
    service = CollectionService(repository, collector_for(item))
    first = await service.collect("persian_news", 3)
    assert first.channel_name == item.channel_name
    assert first.total_fetched == 3
    assert first.valid_news_items == 2
    assert first.newly_inserted == 1
    assert first.duplicates == 1
    assert first.skipped == 1
    assert not first.errors
    second = await service.collect("persian_news", 3)
    assert second.newly_inserted == 0
    assert second.duplicates == 2
    assert repository.count_news() == 1


async def test_partial_fetch_failure_still_saves_valid_records(repository, item):
    service = CollectionService(repository, collector_for(item, ["Connection lost."]))
    summary = await service.collect("persian_news", 30)
    assert summary.newly_inserted == 1
    assert summary.errors == ["Connection lost."]


async def test_database_failure_is_reported_without_payloads(
    repository, item, monkeypatch
):
    def fail(*args):
        raise OperationalError("SECRET SQL payload", {}, Exception("secret"))

    monkeypatch.setattr(repository, "save_news", fail)
    summary = await CollectionService(repository, collector_for(item)).collect(
        "persian_news", 3
    )
    assert summary.newly_inserted == summary.duplicates == 0
    assert "rolled back" in summary.errors[0]
    assert "SECRET" not in str(summary.errors)


async def test_invalid_source_batch_rolls_back(repository, item):
    collector = collector_for(item)
    collector.collect.return_value.items.append(replace(item, channel_id="wrong"))
    summary = await CollectionService(repository, collector).collect("persian_news", 3)
    assert summary.errors
    assert summary.newly_inserted == 0
    assert repository.count_news() == 0
    assert repository.list_sources() == []


async def test_failed_channel_does_not_create_source(repository):
    collector = AsyncMock()
    collector.collect.return_value = CollectionBatch(
        platform="telegram", errors=["Channel inaccessible."]
    )
    summary = await CollectionService(repository, collector).collect("missing_news", 3)
    assert summary.errors
    assert repository.list_sources() == []
