"""Telegram channel_post collector; Telethon remains a separate history path."""

from news_similarity.collectors.bot_api import BotUpdateCollector


class TelegramBotCollector(BotUpdateCollector):
    platform = "telegram"
