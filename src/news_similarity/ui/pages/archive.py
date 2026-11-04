"""Stored news and source history; collection is an explicit shared header action."""

import streamlit as st

from news_similarity.ui.components.news_card import news_card
from news_similarity.ui.components.stored_selection import (
    news_label,
    persistent_select,
    remember_widget,
)
from news_similarity.ui.pages import insights, sources
from news_similarity.ui.presentation import fa_number, platform_label
from news_similarity.ui.services.ui_facade import UiError


def render(facade):
    st.html('<div class="eyebrow">خبرهای ثبت‌شده در بایگانی</div>')
    st.title("آرشیو و منابع")
    st.write("متن اصلی خبرها را بخوانید و آخرین وضعیت ثبت‌شدهٔ جمع‌آوری را بررسی کنید.")
    archive, status = st.tabs(["آرشیو خبرها", "وضعیت منابع"])
    with archive:
        try:
            _browse(facade)
        except UiError as error:
            st.error(str(error))
    with status:
        sources.render(facade, compact=True)
    with st.expander("راهنمای جمع‌آوری و جزئیات پژوهشی"):
        st.caption(
            "برای دریافت از دکمهٔ بالای صفحه استفاده کنید. "
            "فرمان‌های PowerShell نیز در دسترس‌اند؛ مرور خبرها فقط خواندنی است."
        )
        st.code(
            "python -m news_similarity.cli collect-telegram-bot "
            "--limit 30 --exclusive-test-bot\n"
            "python -m news_similarity.cli collect-bale "
            "--limit 30 --exclusive-test-bot",
            language="powershell",
        )
        st.caption(
            "این دستورها به‌صورت پیش‌فرض صف پیام‌رسان را تأیید نمی‌کنند؛ "
            "مالکیت انحصاری ربات لازم است."
        )
        if st.checkbox("نمایش نتایج ارزیابی پژوهشی", key="show_benchmarks"):
            insights.render(facade, compact=True)


def _browse(facade):
    sources_list = facade.sources()
    total = facade.count_news()
    st.caption(f"{fa_number(total)} خبر ذخیره‌شده · متن اصلی و زمان انتشار به UTC")
    if not total:
        st.info("بایگانی خالی است؛ هنوز خبری ذخیره نشده است.")
        return
    a, b = st.columns(2)
    with a:
        platforms = sorted({item.platform for item in sources_list})
        platform = persistent_select(
            "پیام‌رسان",
            ["all", *platforms],
            key="archive_platform",
            format_func=lambda p: platform_label(p) if p != "all" else "همهٔ پیام‌رسان‌ها",
        )
        platform = None if platform == "all" else platform
    with b:
        names = {
            item.id: item.name
            for item in sources_list
            if platform is None or item.platform == platform
        }
        source_id = persistent_select(
            "منبع خبر",
            [-1, *names],
            key="archive_source_new",
            format_func=lambda value: names.get(value, "همهٔ منابع"),
        )
    st.session_state.setdefault(
        "archive_search", st.session_state.get("saved_archive_search", "")
    )
    search = st.text_input(
        "جست‌وجو در آرشیو",
        max_chars=200,
        key="archive_search",
        placeholder="عبارت خبر یا نام منبع…",
        on_change=remember_widget,
        args=("archive_search", "saved_archive_search"),
    )
    st.session_state["saved_archive_search"] = search
    # SQLite search covers the archive; only the rendered page is bounded.
    page = st.number_input(
        "صفحهٔ نتایج", min_value=1, value=1, step=1, key="archive_result_page"
    )
    items = facade.stored_options(
        platform=platform,
        source_id=None if source_id == -1 else source_id,
        search=search,
        limit=20,
        offset=(page - 1) * 20,
    )
    if not items:
        st.info(
            "خبری در این صفحه یا با این فیلتر پیدا نشد؛ "
            "جست‌وجو یا شمارهٔ صفحه را تغییر دهید."
        )
        return
    by_id = {item.id: item for item in items}
    selected = persistent_select(
        "خبر آرشیو",
        list(by_id),
        key="archive_news",
        format_func=lambda value: news_label(by_id[value]),
    )
    news_card(by_id[selected])
    news = by_id[selected]
    if news.platform in {"telegram", "bale"} and st.button(
        "انتخاب این خبر برای مقایسه", key="use_archive_news"
    ):
        st.session_state["saved_" + news.platform + "_news"] = news.id
        st.session_state["saved_" + news.platform + "_search"] = ""
        st.session_state.pop(news.platform + "_news", None)
        st.session_state.pop(news.platform + "_search", None)
        st.session_state.pop("stored_comparison", None)
        st.switch_page("pages/comparison.py")
    st.caption(
        "برای مقایسهٔ بین تلگرام و بله به «مقایسه اخبار» بروید؛ "
        "انتخاب‌های قبلی حفظ می‌شوند."
    )


if __name__ == "__main__":
    from news_similarity.ui.runtime import get_facade

    render(get_facade())
