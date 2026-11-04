"""Native searchable archive selectors with permanent session-state backups."""

from html import escape

import streamlit as st

from news_similarity.ui.components.news_card import news_body
from news_similarity.ui.presentation import fa_number, platform_label, timestamp
from news_similarity.ui.services.ui_facade import safe_url


def remember_widget(widget, saved):
    st.session_state[saved] = st.session_state.get(widget)
    if widget.startswith(("telegram_", "bale_")):
        st.session_state.pop("stored_comparison", None)
    if widget in {"archive_platform", "archive_source_new", "archive_search"}:
        st.session_state["archive_result_page"] = 1


def persistent_select(
    label, options, *, key, format_func=str, placeholder="انتخاب کنید"
):
    saved = "saved_" + key
    default = options[0] if options else None
    current = st.session_state.get(key, st.session_state.get(saved, default))
    if current not in options:
        current = default
    st.session_state[key] = current
    chosen = st.selectbox(
        label,
        options,
        index=None,
        key=key,
        format_func=format_func,
        placeholder=placeholder,
        disabled=not options,
        on_change=remember_widget,
        args=(key, saved),
    )
    st.session_state[saved] = chosen
    return chosen


def news_label(news):
    return (
        news.text.replace("\n", " ")[:80]
        + " · "
        + (news.source_name or "منبع بدون نام")
    )


def selection_panel(facade, platform):
    label = platform_label(platform)
    with st.container(border=True, key=platform + "_panel"):
        st.html(
            '<div class="platform-heading">خبر '
            + escape(label)
            + '<span class="platform-badge">بایگانی '
            + escape(label)
            + "</span></div>"
        )
        search_key = platform + "_search"
        st.session_state.setdefault(
            search_key, st.session_state.get("saved_" + search_key, "")
        )
        search = st.text_input(
            "جست‌وجو در خبرهای " + label,
            key=search_key,
            max_chars=200,
            placeholder="عبارت خبر یا نام منبع…",
            on_change=remember_widget,
            args=(search_key, "saved_" + search_key),
        )
        st.session_state["saved_" + search_key] = search
        records = facade.stored_options(platform=platform, search=search)
        saved_id = st.session_state.get("saved_" + platform + "_news")
        if (
            saved_id is not None
            and not search
            and saved_id not in {n.id for n in records}
        ):
            saved_news = facade.get_news(saved_id)
            if saved_news is not None and saved_news.platform == platform:
                records.insert(0, saved_news)
        by_id = {news.id: news for news in records}
        selected = persistent_select(
            "انتخاب خبر " + label,
            list(by_id),
            key=platform + "_news",
            format_func=lambda value: news_label(by_id[value]),
            placeholder="خبری برای انتخاب وجود ندارد",
        )
        if not records:
            text = (
                "خبری با این جست‌وجو پیدا نشد."
                if search
                else "هنوز خبری از این پیام‌رسان ذخیره نشده است."
            )
            st.html(
                '<div class="panel-empty"><strong>'
                + escape(text)
                + "</strong><span>بایگانی و وضعیت منابع را بررسی کنید.</span></div>"
            )
            return None
        news = by_id[selected]
        with st.container(height=180, border=False):
            news_body(news.text)
        st.html(
            '<div class="news-meta">'
            + escape(news.source_name or "منبع بدون نام")
            + " · انتشار: "
            + escape(timestamp(news.published_at))
            + "</div>"
        )
        if safe_url(news.url):
            st.link_button("مشاهدهٔ خبر در منبع", news.url)
        st.caption(
            f"{fa_number(len(records))} خبر در فهرست · برای خبرهای قدیمی‌تر جست‌وجو کنید."
        )
        return news
