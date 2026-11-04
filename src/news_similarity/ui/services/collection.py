"""Explicit bounded UI collection. There is deliberately no acknowledgement option."""

from dataclasses import replace
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from news_similarity.collectors.bale import BaleBotCollector
from news_similarity.collectors.bot_api import (
    BotCollectionConfig,
    BotConfigurationError,
)
from news_similarity.collectors.telegram_bot import TelegramBotCollector
from news_similarity.config import validate_database_url
from news_similarity.database.repository import NewsRepository
from news_similarity.integrations.bot_probe import ProbeError
from news_similarity.services.bot_collection import BotCollectionService

REASONS = {
    "exclusive_required": "ابتدا اختصاصی بودن ربات‌ها و توقف مصرف‌کننده‌های دیگر "
    "را تأیید کنید.",
    "configuration": "تنظیمات ربات یا کانال مجاز آماده نیست؛ "
    "فایل محیط صریح ربات را بررسی کنید.",
    "file_load": "فایل تنظیمات ربات پیدا نشد، خواندنی نیست یا قالب معتبری ندارد.",
    "missing_token": "توکن ربات این پیام‌رسان در تنظیمات موجود نیست.",
    "missing_channels": "شناسهٔ کانال‌های مجاز این پیام‌رسان در تنظیمات موجود نیست.",
    "invalid_token": "قالب توکن ربات این پیام‌رسان معتبر نیست.",
    "invalid_channels": "شناسهٔ کانال‌های مجاز باید فهرست عددی معتبر باشند.",
    "unavailable": "دریافت کامل نشد؛ اتصال، دسترسی کانال، وب‌هوک "
    "و قفل جمع‌آوری را بررسی کنید.",
    "blocked": "بعضی رویدادها مسدودند و برای بررسی نگه داشته شدند؛ صف تأیید نشده است.",
    "demo": "دریافت زنده در محیط دادهٔ مصنوعی غیرفعال است.",
}


def collect_news(config, platform, *, exclusive_bot=False):
    result = {"platform": platform, "status": "BLOCKED", "acknowledged": False}
    if platform not in {"telegram", "bale"}:
        return result | {"reason": "configuration"}
    if config.demo_mode:
        return result | {"reason": "demo"}
    if exclusive_bot is not True:
        return result | {"reason": "exclusive_required"}
    repository = None
    try:
        path = config.bot_env_path(platform)
        bot = BotCollectionConfig.load(
            platform, path, limit=30, duration=30, poll_seconds=5
        )
        if not bot.lock_dir.is_absolute():
            bot = replace(bot, lock_dir=config.root / bot.lock_dir)
        validate_database_url(config.database_url)
        url = make_url(config.database_url)
        if not url.database or url.database == ":memory:":
            return result | {"reason": "configuration"}
        database = Path(url.database)
        if not database.is_absolute():
            url = url.set(database=str(config.root / database))
        repository = NewsRepository(url.render_as_string(hide_password=False))
        collector = (
            TelegramBotCollector if platform == "telegram" else BaleBotCollector
        )(bot)
        report = BotCollectionService(repository, collector).collect(
            exclusive_test_bot=True, acknowledge_stored=False
        )
        # Never put raw provider text, credentials, IDs or message bodies into UI
        # state. Only fixed labels and count fields cross this adapter boundary.
        result["status"] = (
            report.get("status")
            if report.get("status") in {"STORED", "BLOCKED", "ERROR"}
            else "ERROR"
        )
        for key in (
            "inserted",
            "duplicates",
            "duplicate_updates",
            "skipped",
            "received_updates",
            "pending_updates",
            "blocked_updates",
        ):
            value = report.get(key)
            if type(value) is int and value >= 0:
                result[key] = value
        if report.get("reason") or result["status"] == "ERROR":
            result["reason"] = "unavailable"
        elif result.get("blocked_updates"):
            result["reason"] = "blocked"
        return result
    except BotConfigurationError as error:
        return result | {"reason": error.code}
    except (ProbeError, ValueError, TypeError, OSError, SQLAlchemyError):
        return result | {
            "reason": "configuration" if repository is None else "unavailable"
        }
    finally:
        if repository is not None:
            repository.close()
