from datetime import UTC, datetime

import pytest

from news_similarity.config import Settings
from news_similarity.database.repository import NewsRepository
from news_similarity.records import NewsItem


@pytest.fixture
def settings():
    # Deliberately fake, used only with injected mocks. Never connects to Telegram.
    return Settings(telegram_api_id=12345, telegram_api_hash="a" * 32)


@pytest.fixture
def repository(tmp_path):
    repo = NewsRepository(f"sqlite:///{(tmp_path / 'news.db').as_posix()}")
    repo.initialize()
    yield repo
    repo.close()


@pytest.fixture
def item():
    return NewsItem(
        platform="telegram",
        channel_id="1001",
        channel_name="اخبار فارسی",
        message_id="42",
        text="  خبر تازه: پژوهش‌های داده‌کاوی\nبا حفظ متن اصلی!  ",
        published_at=datetime(2026, 1, 2, 12, 30, tzinfo=UTC),
        url="https://t.me/persian_news/42",
    )
