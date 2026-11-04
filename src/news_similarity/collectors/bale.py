"""Bale message/chat.type=channel collector, without Telegram envelope assumptions."""

from news_similarity.collectors.bot_api import BotUpdateCollector


class BaleBotCollector(BotUpdateCollector):
    platform = "bale"
