"""Run with: python -m streamlit run src/news_similarity/ui/app.py"""

from pathlib import Path

import streamlit as st

from news_similarity.ui.components.collection_panel import collection_panel
from news_similarity.ui.runtime import get_facade
from news_similarity.ui.services.ui_facade import UiError


def main():
    st.set_page_config(
        page_title="هم‌خبر | سامانه تشخیص شباهت اخبار فارسی",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    css = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")
    st.html("<style>" + css + "</style>")
    pages = [
        st.Page(
            "pages/comparison.py",
            title="مقایسه اخبار",
            default=True,
            url_path="compare",
        ),
        st.Page("pages/archive.py", title="آرشیو و منابع", url_path="archive"),
    ]
    # Native top navigation becomes a sidebar on narrow screens. Keep the two
    # native page links visible above the content at every viewport width.
    page = st.navigation(pages, position="hidden")
    with st.container(key="hamkhabar"):
        with st.container(key="top_navigation", horizontal=True):
            for entry in pages:
                st.page_link(entry)
        st.html(
            '<header class="brand" dir="rtl"><div class="brand-name">'
            "هم‌خبر<span>◈</span></div>"
            '<div class="brand-description">سامانه تشخیص شباهت اخبار فارسی</div>'
            '<div class="brand-note">پروژهٔ داده‌کاوی · نسخهٔ پژوهشی</div></header>'
        )
        try:
            facade = get_facade()
        except UiError as error:
            st.error(str(error))
            st.stop()
        if facade.config.demo_mode:
            st.warning("محیط نمایشی: خبرهای این پایگاه مصنوعی‌اند؛ دادهٔ زنده نیستند.")
        collection_panel(facade)
        page.run()
        st.html(
            '<footer class="product-footer">هم‌خبر · تحلیل متن و شواهد رویداد'
            "<span>نتیجهٔ مدل، تأیید صحت خبر نیست.</span></footer>"
        )


if __name__ == "__main__":
    main()
