"""Archive access and thin adapters over established application services."""

import os
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values
from sqlalchemy import or_, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from news_similarity.config import ConfigurationError, validate_database_url
from news_similarity.database.models import News, Source
from news_similarity.database.repository import NewsRepository

MAX_TEXT_LENGTH = 30_000
MAX_CANDIDATES = 100


class UiError(RuntimeError):
    """A localized, safe message for an expected UI failure."""


class InputError(UiError):
    pass


def safe_url(value: str | None) -> str | None:
    if not value or any(
        character.isspace() or ord(character) < 32 for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        _ = parsed.port
        return value
    except ValueError:
        return None


@dataclass(frozen=True)
class UiConfig:
    root: Path
    database_url: str
    artifacts: Path
    cache_folder: str | None = None
    demo_mode: bool = False
    bot_env_file: str | None = None

    def bot_env_path(self, platform):
        filename = self.bot_env_file or (
            ".env" if platform == "telegram" else ".env.bot-probes"
        )
        path = Path(filename)
        return (path if path.is_absolute() else self.root / path).resolve()

    @classmethod
    def from_environment(
        cls, root: Path | None = None, environ: Mapping[str, str] | None = None
    ):
        # This UI runs from the existing source checkout; launch location must
        # not select a different credential file, archive or lock directory.
        root = (root or Path(__file__).resolve().parents[4]).resolve()
        try:
            file_values = dotenv_values(root / ".env", interpolate=False)
        except (OSError, UnicodeError):
            raise UiError(
                "فایل تنظیمات برنامه خوانده نشد؛ "
                "دسترسی و قالب UTF-8 فایل را بررسی کنید."
            ) from None
        values = {
            **file_values,
            **(os.environ if environ is None else environ),
        }
        artifacts = Path(values.get("NEWS_UI_ARTIFACT_DIR") or root / "artifacts")
        if not artifacts.is_absolute():
            artifacts = root / artifacts
        return cls(
            root,
            values.get("DATABASE_URL") or "sqlite:///./data/news.db",
            artifacts,
            values.get("NEWS_UI_MODEL_CACHE") or None,
            values.get("NEWS_UI_DEMO_MODE") == "1",
            values.get("NEWS_UI_BOT_ENV_FILE") or None,
        )

    def model_files(self) -> tuple[Path, ...]:
        return (
            self.artifacts / "tfidf/word.model.json",
            self.artifacts / "tfidf/character.model.json",
            self.artifacts / "semantic/freeze.json",
            self.artifacts / "hybrid/hybrid.freeze.json",
        )


@dataclass(frozen=True)
class SourceInfo:
    id: int
    platform: str
    name: str
    external_id: str
    url: str | None
    news_count: int
    latest_publication: datetime | None


@dataclass(frozen=True)
class StoredNews:
    id: int
    source_id: int
    platform: str
    source_name: str
    text: str
    published_at: datetime
    collected_at: datetime
    url: str | None
    source_url: str | None


@dataclass(frozen=True)
class SourceInput:
    name: str = ""
    url: str = ""

    def validate(self):
        if self.url.strip() and safe_url(self.url.strip()) is None:
            raise InputError("پیوند منبع باید یک نشانی معتبر http یا https باشد.")
        if len(self.name) > 200:
            raise InputError("نام منبع را کوتاه‌تر از ۲۰۰ نویسه وارد کنید.")


@dataclass(frozen=True)
class ComparisonView:
    result: dict[str, Any]
    source_a: SourceInput
    source_b: SourceInput

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RankedNews:
    news: StoredNews
    result: dict[str, Any]


class UiFacade:
    def __init__(self, config: UiConfig, *, model_provider: Callable | None = None):
        self.config = config
        self._model_provider = model_provider

    def collect_news(self, platform, *, exclusive_bot=False):
        from news_similarity.ui.services.collection import collect_news

        return collect_news(self.config, platform, exclusive_bot=exclusive_bot)

    @contextmanager
    def _repository(self):
        repository = None
        try:
            validate_database_url(self.config.database_url)
            url = make_url(self.config.database_url)
            if url.database == ":memory:":
                yield None
                return
            path = Path(url.database)
            if not path.is_absolute():
                path = self.config.root / path
            if not path.is_file():
                yield None
                return
            repository = NewsRepository(
                url.set(database=path.as_posix()).render_as_string(hide_password=False),
                read_only=True,
            )
            yield repository
        except (SQLAlchemyError, OSError, ConfigurationError, ValueError):
            raise UiError(
                "بایگانی در دسترس نیست. مسیر و ساختار پایگاه "
                "داده را در پیکربندی بررسی کنید."
            ) from None
        finally:
            if repository is not None:
                repository.close()

    @staticmethod
    def _source_name(source):
        return source.name or "منبع بدون نام"

    @classmethod
    def _news(cls, record, source):
        return StoredNews(
            record.id,
            record.source_id,
            source.platform if source else "unknown",
            cls._source_name(source) if source else "منبع نامشخص",
            record.text,
            record.published_at,
            record.collected_at,
            safe_url(record.url),
            safe_url(source.url) if source else None,
        )

    def sources(self) -> list[SourceInfo]:
        with self._repository() as repository:
            if repository is None:
                return []
            return [
                SourceInfo(
                    item.source.id,
                    item.source.platform,
                    self._source_name(item.source),
                    item.source.external_id,
                    safe_url(item.source.url),
                    item.news_count,
                    item.latest_publication,
                )
                for item in repository.source_statistics()
            ]

    def count_news(self, source_id: int | None = None) -> int:
        with self._repository() as repository:
            return repository.count_news(source_id) if repository else 0

    def collection_status(self):
        from news_similarity.database.bot_storage import BotStorage

        with self._repository() as repository:
            return BotStorage(repository).status() if repository else []

    def stored_options(
        self, *, platform=None, source_id=None, search="", limit=100, offset=0
    ):
        """Read-only UI search across stored text/source names; never contact a bot."""
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or type(offset) is not int
            or offset < 0
        ):
            raise InputError("اندازهٔ فهرست خبر معتبر نیست.")
        if not isinstance(search, str) or len(search) > 200:
            raise InputError("عبارت جست‌وجو باید حداکثر ۲۰۰ نویسه باشد.")
        with self._repository() as repository:
            if repository is None:
                return []
            statement = select(News, Source).join(Source, Source.id == News.source_id)
            if platform is not None:
                statement = statement.where(Source.platform == platform)
            if source_id is not None:
                statement = statement.where(Source.id == source_id)
            if search.strip():
                statement = statement.where(
                    or_(
                        News.text.contains(search.strip(), autoescape=True),
                        Source.name.contains(search.strip(), autoescape=True),
                    )
                )
            statement = (
                statement.order_by(News.published_at.desc(), News.id.desc())
                .limit(limit)
                .offset(offset)
            )
            with Session(repository.engine) as session:
                return [
                    self._news(news, source)
                    for news, source in session.execute(statement)
                ]

    def compare_stored(self, telegram_id, bale_id):
        if telegram_id == bale_id:
            raise InputError("دو خبر متفاوت انتخاب کنید؛ یک خبر با خودش مقایسه نمی‌شود.")
        first, second = self.get_news(telegram_id), self.get_news(bale_id)
        if first is None or second is None:
            raise InputError("خبر انتخاب‌شده در بایگانی نیست؛ فهرست را تازه‌سازی کنید.")
        if first.platform != "telegram" or second.platform != "bale":
            raise InputError("یک خبر از تلگرام و یک خبر از بله انتخاب کنید.")
        return self.compare(
            first.text,
            second.text,
            SourceInput(first.source_name, first.source_url or ""),
            SourceInput(second.source_name, second.source_url or ""),
        )

    def browse(
        self, *, source_id: int | None = None, limit=20, offset=0
    ) -> list[StoredNews]:
        with self._repository() as repository:
            if repository is None:
                return []
            sources = {source.id: source for source in repository.list_sources()}
            return [
                self._news(record, sources.get(record.source_id))
                for record in repository.browse_news(
                    limit=limit, offset=offset, source_id=source_id
                )
            ]

    def get_news(self, news_id: int) -> StoredNews | None:
        with self._repository() as repository:
            if repository is None:
                return None
            record = repository.get_news(news_id)
            if record is None:
                return None
            source = next(
                (
                    source
                    for source in repository.list_sources()
                    if source.id == record.source_id
                ),
                None,
            )
            return self._news(record, source)

    def _models(self):
        if self._model_provider is not None:
            return self._model_provider()
        from news_similarity.ui.services.resources import model_resource, resource_stamp

        return model_resource(self.config, resource_stamp(self.config))

    def _inference(self, method, *args, **kwargs):
        from news_similarity.hybrid import HybridModelError
        from news_similarity.semantic import SemanticModelError

        try:
            return getattr(self._models(), method)(*args, **kwargs)
        except UiError:
            raise
        except (HybridModelError, SemanticModelError, OSError, ValueError):
            raise UiError(
                "تحلیل در دسترس نیست. فایل‌های مدل، تنظیمات ثابت و کش MiniLM "
                "را بررسی کنید. هیچ امتیاز جایگزینی تولید نشد."
            ) from None

    @staticmethod
    def validate_text(text: str):
        if not isinstance(text, str) or not text.strip():
            raise InputError("متن هر دو خبر را وارد کنید؛ متن خالی قابل مقایسه نیست.")
        if len(text) > MAX_TEXT_LENGTH:
            raise InputError("برای هر خبر حداکثر ۳۰ هزار نویسه وارد کنید.")
        from news_similarity.semantic import SemanticSimilarity

        try:
            SemanticSimilarity.prepare(text)
        except ValueError:
            raise InputError(
                "متن باید بیش از فاصله یا نشانه‌های قالب‌بندی باشد."
            ) from None

    def compare(
        self,
        text_a: str,
        text_b: str,
        source_a: SourceInput | None = None,
        source_b: SourceInput | None = None,
    ) -> ComparisonView:
        self.validate_text(text_a)
        self.validate_text(text_b)
        source_a, source_b = source_a or SourceInput(), source_b or SourceInput()
        source_a.validate()
        source_b.validate()
        result = self._inference("compare", text_a, text_b)
        return ComparisonView(result.to_dict(), source_a, source_b)

    def rank(
        self,
        news_id: int,
        *,
        target_source_id: int | None = None,
        platform: str | None = None,
        limit: int = 50,
        top_k: int = 10,
    ) -> list[RankedNews]:
        if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
            raise InputError("تعداد نامزدها باید بین ۱ تا ۱۰۰ باشد.")
        if type(top_k) is not int or not 1 <= top_k <= limit:
            raise InputError("تعداد نتایج باید مثبت و کمتر از تعداد نامزدها باشد.")
        with self._repository() as repository:
            if repository is None:
                raise InputError("بایگانی خبری برای جست‌وجو وجود ندارد.")
            query = repository.get_news(news_id)
            if query is None:
                raise InputError(
                    "خبر انتخاب‌شده دیگر در بایگانی نیست. فهرست را تازه‌سازی کنید."
                )
            if query.source_id == target_source_id:
                raise InputError("برای مقایسهٔ بین‌منبعی، منبع دیگری را انتخاب کنید.")
            sources = {source.id: source for source in repository.list_sources()}
            records = repository.browse_news(
                limit=limit,
                source_id=target_source_id,
                platform=platform,
                exclude_source_id=query.source_id,
            )
            candidates = [
                self._news(record, sources.get(record.source_id)) for record in records
            ]
        if not candidates:
            return []
        from news_similarity.semantic import SemanticSimilarity

        try:
            SemanticSimilarity.prepare(query.text)
        except ValueError:
            raise InputError("متن خبر انتخاب‌شده برای تحلیل کافی نیست.") from None
        # Stored long articles are preserved in full; the existing encoder owns
        # its context limit. The manual-input cap does not truncate archive rows.
        ranked = self._inference(
            "rank", query.text, [item.text for item in candidates], top_k=top_k
        )
        return [
            RankedNews(candidates[item.index], item.result.to_dict()) for item in ranked
        ]
