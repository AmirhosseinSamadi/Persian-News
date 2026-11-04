from html import escape

import streamlit as st

from news_similarity.ui.presentation import platform_label, timestamp
from news_similarity.ui.services.ui_facade import safe_url


def news_body(text: str):
    st.html('<div class="news-copy" dir="rtl">' + escape(text) + "</div>")


def news_card(news, *, heading: str | None = None):
    with st.container(border=True):
        if heading:
            st.markdown(f"**{heading}**")
        st.caption(f"{platform_label(news.platform)} · {news.source_name}")
        st.caption("انتشار: " + timestamp(news.published_at))
        with st.container(height=240, border=False):
            news_body(news.text)
        columns = st.columns(2)
        url = safe_url(news.url)
        if url:
            columns[0].link_button("خبر در منبع اصلی", url)
        else:
            columns[0].caption("پیوند خبر در دسترس نیست.")
        if safe_url(news.source_url):
            columns[1].link_button("صفحهٔ منبع", news.source_url)


def manual_source(name, url):
    if name:
        st.text(name)
    link = safe_url(url.strip())
    if link:
        st.link_button("پیوند واردشدهٔ منبع", link)
