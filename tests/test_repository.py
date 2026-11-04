from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import IntegrityError

from news_similarity.database.models import News, Source
from news_similarity.database.repository import NewsRepository


def test_initialization_creates_parent_and_is_idempotent(tmp_path):
    repo = NewsRepository(f"sqlite:///{(tmp_path / 'nested' / 'news.db').as_posix()}")
    try:
        repo.initialize()
        repo.initialize()
        assert set(inspect(repo.engine).get_table_names()) == {"sources", "news"}
        assert repo.count_news() == 0
    finally:
        repo.close()


def test_source_uniqueness_and_metadata(repository):
    first = repository.get_or_create_source("telegram", "1001", "Old title")
    second = repository.get_or_create_source("telegram", "1001", "New title")
    other = repository.get_or_create_source("bale", "1001")
    assert first.id == second.id != other.id
    assert second.name == "New title"
    assert first.created_at.tzinfo == UTC
    assert len(repository.list_sources()) == 2


def test_source_unique_constraint_is_enforced_by_database(repository):
    repository.get_or_create_source("telegram", "1001")
    with pytest.raises(IntegrityError), repository.engine.begin() as connection:
        connection.execute(
            insert(Source).values(platform="telegram", external_id="1001")
        )


def save(repository, item, items=None):
    return repository.save_news(
        item.platform,
        item.channel_id,
        item.channel_name,
        None,
        [item] if items is None else items,
    )


def test_news_insert_retrieve_and_duplicate_handling(repository, item):
    first = save(repository, item, [item, item])
    second = save(repository, item)
    assert (first.inserted, first.duplicates) == (1, 1)
    assert (second.inserted, second.duplicates) == (0, 1)
    stored = repository.recent_news()[0]
    assert stored.text == item.text
    assert stored.url == item.url
    assert stored.external_id == item.message_id
    assert stored.published_at == item.published_at
    assert stored.published_at.tzinfo == UTC
    assert stored.collected_at.tzinfo == UTC
    assert repository.count_news() == 1


def test_news_unique_constraint_is_enforced_by_database(repository, item):
    save(repository, item)
    source = repository.list_sources()[0]
    with pytest.raises(IntegrityError), repository.engine.begin() as connection:
        connection.execute(
            insert(News).values(
                source_id=source.id,
                external_id=item.message_id,
                text="duplicate",
                published_at=item.published_at,
            )
        )


def test_ordering_limit_filtering_and_cross_channel_message_ids(repository, item):
    older = replace(
        item, message_id="41", published_at=item.published_at - timedelta(days=1)
    )
    other = replace(item, channel_id="2002", text="خبر کانال دیگر")
    save(repository, item, [older, item])
    save(repository, other)
    source = repository.get_or_create_source("telegram", "1001")
    assert repository.count_news() == 3
    assert repository.count_news(source.id) == 2
    assert [row.external_id for row in repository.recent_news(10, source.id)] == [
        "42",
        "41",
    ]
    assert len(repository.recent_news(1)) == 1
    assert repository.recent_news(source_id=9999) == []


def test_utc_conversion_and_naive_rejection(repository, item):
    local = datetime(2026, 1, 2, 16, 0, tzinfo=timezone(timedelta(hours=3, minutes=30)))
    converted = replace(item, published_at=local)
    save(repository, converted)
    assert repository.recent_news()[0].published_at == item.published_at
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(item, published_at=local.replace(tzinfo=None))


def test_transaction_rolls_back_source_and_all_news(repository, item):
    wrong_source = replace(item, channel_id="wrong")
    with pytest.raises(ValueError, match="does not belong"):
        save(repository, item, [item, wrong_source])
    assert repository.count_news() == 0
    assert repository.list_sources() == []
    # The repository remains usable after failure.
    assert save(repository, item).inserted == 1


def test_foreign_key_is_enforced(repository, item):
    with pytest.raises(IntegrityError), repository.engine.begin() as connection:
        connection.execute(
            insert(News).values(
                source_id=9999,
                external_id="1",
                text=item.text,
                published_at=item.published_at,
            )
        )


def test_data_survives_reopening(repository, item):
    save(repository, item)
    with repository.engine.connect() as connection:
        assert connection.scalar(select(News.text)) == item.text
    reopened = NewsRepository(str(repository.engine.url))
    try:
        assert reopened.count_news() == 1
    finally:
        reopened.close()


def test_invalid_record_text_and_limit(repository, item):
    with pytest.raises(ValueError, match="text"):
        replace(item, text=" \n ")
    with pytest.raises(ValueError, match="positive"):
        repository.recent_news(0)
