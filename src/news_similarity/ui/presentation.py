"""Persian labels and formatting only; no duplicated matching algorithms."""

from datetime import UTC, datetime

MODEL_LABELS = {
    "word": "TF-IDF واژه‌ای",
    "character": "TF-IDF نویسه‌ای",
    "semantic": "MiniLM چندزبانه",
    "hybrid_without_events": "ترکیبی بدون شواهد",
    "hybrid": "ترکیبی با شواهد",
}
DECISIONS = {
    "likely_same_event": "احتمالاً یک رویداد",
    "uncertain": "نامطمئن؛ نیازمند بررسی",
    "likely_different_event": "احتمالاً رویدادهای متفاوت",
}
FEATURES = {
    "number": "عدد و مقدار",
    "date": "تاریخ",
    "time": "ساعت",
    "location": "مکان",
    "entity": "نام مشخص",
    "assertion": "قطبیت ادعا",
    "negation": "نشانهٔ نفی",
}
CONFIDENCE = {
    "explicit_match": "شواهد همخوان",
    "confirmed_explicit_conflict": "ناسازگاری صریح ادعا",
    "possible_conflict": "تفاوت احتمالی",
    "insufficient_information": "اطلاعات ناکافی",
}
SCENARIOS = {
    "same_event_paraphrase": "یک رویداد، بیان متفاوت",
    "near_identical": "تقریباً یکسان",
    "same_topic_different_events": "موضوع مشترک، رویداد متفاوت",
    "same_location_different_dates": "مکان مشترک، تاریخ متفاوت",
    "different_numbers": "عددهای متفاوت",
    "negation_difference": "تفاوت نفی",
    "unrelated": "نامرتبط",
    "short_long": "خبر کوتاه و بلند",
}


def fa_number(value) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def platform_label(value: str) -> str:
    return {
        "telegram": "تلگرام",
        "bale": "بله",
        "synthetic": "دادهٔ مصنوعی",
        "unknown": "نامشخص",
    }.get(value, value)


def timestamp(value: datetime | None) -> str:
    return (
        value.astimezone(UTC).strftime("%Y/%m/%d · %H:%M UTC")
        if value
        else "زمان ثبت نشده"
    )


def decision_explanation(result) -> str:
    if result["decision"] == "likely_same_event":
        return (
            "شباهت متنی بالا و چند نوع شواهد زمینه‌ای همخوان، "
            "پشتیبان این برآوردند. این نتیجه تأیید صحت خبر نیست."
        )
    if result["decision"] == "likely_different_event":
        return (
            "شباهت متنی پایین و چند تفاوت زمینه‌ای از این برآورد "
            "اولیه پشتیبانی می‌کنند. هویت رویدادها هنوز تأیید نشده "
            "است."
        )
    if result.get("applied_penalty", 0) > 0:
        return (
            "ادعاهای صریح ناسازگارند؛ ممکن است دربارهٔ یک رویداد یا"
            " اصلاح خبر باشند. امتیاز رتبه‌بندی کاهش یافته، اما "
            "رویداد متفاوت نتیجه‌گیری نشده است."
        )
    if result["event_evidence"]["conflicting_features"]:
        return (
            "تفاوت‌هایی در شواهد دیده شده است. تفاوت عدد، تاریخ یا "
            "مکان به‌تنهایی رویداد متفاوت را ثابت نمی‌کند؛ بررسی "
            "انسانی لازم است."
        )
    return (
        "شواهد قابل اتکا یا هم‌ترازی کافی برای تصمیم رویدادی وجود "
        "ندارد. حتی شباهت زیاد متن نیز برای یکسان دانستن رویدادها "
        "کافی نیست."
    )
