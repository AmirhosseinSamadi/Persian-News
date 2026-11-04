"""Short transactions; duplicate conflicts are handled by SQLite atomically."""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from news_similarity.config import validate_database_url
from news_similarity.database.models import Base, News, Source
from news_similarity.records import NewsItem


@dataclass(frozen=True)
class SaveResult:
    inserted: int
    duplicates: int


@dataclass(frozen=True)
class SourceStatistics:
    source: Source
    news_count: int
    latest_publication: datetime | None


class NewsRepository:
    def __init__(self, database_url: str, *, read_only: bool = False) -> None:
        validate_database_url(database_url)
        database = make_url(database_url).database
        if read_only:
            if not database or database == ":memory:" or not Path(database).is_file():
                raise FileNotFoundError(
                    "A stored SQLite database is required for reading."
                )
            uri = Path(database).resolve().as_uri() + "?mode=ro"
            self.engine = create_engine(
                database_url,
                creator=lambda: sqlite3.connect(
                    uri, uri=True, timeout=30, check_same_thread=False
                ),
            )
        else:
            if database and database != ":memory:":
                Path(database).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(database_url, connect_args={"timeout": 30})

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _get_or_create_source(
        session: Session,
        platform: str,
        external_id: str,
        name: str | None,
        url: str | None,
    ) -> Source:
        if not platform.strip() or not external_id.strip():
            raise ValueError("Source platform and external ID must be nonempty.")
        session.execute(
            insert(Source)
            .values(platform=platform, external_id=external_id, name=name, url=url)
            .on_conflict_do_nothing(index_elements=["platform", "external_id"])
        )
        source = session.scalar(
            select(Source).where(
                Source.platform == platform, Source.external_id == external_id
            )
        )
        assert source is not None
        if name is not None:
            source.name = name
        if url is not None:
            source.url = url
        return source

    def get_or_create_source(
        self,
        platform: str,
        external_id: str,
        name: str | None = None,
        url: str | None = None,
    ) -> Source:
        with self._sessions.begin() as session:
            return self._get_or_create_source(session, platform, external_id, name, url)

    def save_news(
        self,
        platform: str,
        channel_id: str,
        channel_name: str | None,
        channel_url: str | None,
        items: Iterable[NewsItem],
    ) -> SaveResult:
        """Commit source metadata and the entire batch, or roll everything back."""
        inserted = duplicates = 0
        with self._sessions.begin() as session:
            source = self._get_or_create_source(
                session, platform, channel_id, channel_name, channel_url
            )
            for item in items:
                if item.platform != platform or item.channel_id != channel_id:
                    raise ValueError(
                        "News item does not belong to the requested source."
                    )
                new_id = session.scalar(
                    insert(News)
                    .values(
                        source_id=source.id,
                        external_id=item.message_id,
                        text=item.text,
                        published_at=item.published_at,
                        url=item.url,
                    )
                    .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
                    .returning(News.id)
                )
                if new_id is None:
                    duplicates += 1
                else:
                    inserted += 1
        return SaveResult(inserted, duplicates)

    def recent_news(self, limit: int = 10, source_id: int | None = None) -> list[News]:
        if limit <= 0:
            raise ValueError("limit must be positive.")
        statement = (
            select(News).order_by(News.published_at.desc(), News.id.desc()).limit(limit)
        )
        if source_id is not None:
            statement = statement.where(News.source_id == source_id)
        with self._sessions() as session:
            return list(session.scalars(statement))

    def count_news(self, source_id: int | None = None) -> int:
        statement = select(func.count()).select_from(News)
        if source_id is not None:
            statement = statement.where(News.source_id == source_id)
        with self._sessions() as session:
            return session.scalar(statement) or 0

    def list_sources(self) -> list[Source]:
        with self._sessions() as session:
            return list(session.scalars(select(Source).order_by(Source.id)))

    def get_news(self, news_id: int) -> News | None:
        if type(news_id) is not int or news_id < 1:
            raise ValueError("News ID must be a positive integer.")
        with self._sessions() as session:
            return session.get(News, news_id)

    def browse_news(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        source_id: int | None = None,
        platform: str | None = None,
        exclude_source_id: int | None = None,
    ) -> list[News]:
        if type(limit) is not int or limit < 1 or type(offset) is not int or offset < 0:
            raise ValueError("Page size must be positive and offset nonnegative.")
        statement = select(News).join(Source, Source.id == News.source_id)
        if source_id is not None:
            statement = statement.where(News.source_id == source_id)
        if platform is not None:
            statement = statement.where(Source.platform == platform)
        if exclude_source_id is not None:
            statement = statement.where(News.source_id != exclude_source_id)
        statement = (
            statement.order_by(News.published_at.desc(), News.id.desc())
            .offset(offset)
            .limit(limit)
        )
        with self._sessions() as session:
            return list(session.scalars(statement))

    def source_statistics(self) -> list[SourceStatistics]:
        statement = (
            select(Source, func.count(News.id), func.max(News.published_at))
            .outerjoin(News, News.source_id == Source.id)
            .group_by(Source.id)
            .order_by(Source.id)
        )
        with self._sessions() as session:
            return [
                SourceStatistics(source, count, latest)
                for source, count, latest in session.execute(statement)
            ]
