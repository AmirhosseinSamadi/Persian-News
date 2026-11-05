"""Additive BoW UI adapter; existing Hybrid facade methods are unchanged."""

from news_similarity.ui.services.ui_facade import InputError, SourceInput


def compare_bow(facade, first, second, source_a=None, source_b=None):
    from news_similarity.bow import BagOfWordsSimilarity

    facade.validate_text(first)
    facade.validate_text(second)
    source_a, source_b = source_a or SourceInput(), source_b or SourceInput()
    source_a.validate()
    source_b.validate()
    return {
        "result": BagOfWordsSimilarity().analyze(first, second).to_dict(),
        "source_a": {"name": source_a.name, "url": source_a.url},
        "source_b": {"name": source_b.name, "url": source_b.url},
    }


def compare_stored_bow(facade, telegram_id, bale_id):
    if telegram_id == bale_id:
        raise InputError("دو خبر متفاوت انتخاب کنید؛ یک خبر با خودش مقایسه نمی‌شود.")
    first, second = facade.get_news(telegram_id), facade.get_news(bale_id)
    if first is None or second is None:
        raise InputError("خبر انتخاب‌شده در بایگانی نیست؛ فهرست را تازه‌سازی کنید.")
    if first.platform != "telegram" or second.platform != "bale":
        raise InputError("یک خبر از تلگرام و یک خبر از بله انتخاب کنید.")
    return compare_bow(
        facade,
        first.text,
        second.text,
        SourceInput(first.source_name, first.source_url or ""),
        SourceInput(second.source_name, second.source_url or ""),
    )
