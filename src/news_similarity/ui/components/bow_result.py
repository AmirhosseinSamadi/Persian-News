"""BoW-only result using existing result styles; never impersonates Hybrid output."""

import json
from html import escape

import streamlit as st

from news_similarity.ui.presentation import fa_number


def bow_result(view, *, key):
    result = view["result"]
    score = result["cosine_similarity"]
    with st.container(border=True, key=key):
        st.subheader("نتیجهٔ مقایسه")
        method, number = st.columns([2, 1], gap="large", vertical_alignment="center")
        with method:
            st.markdown("**Bag of Words + Cosine Similarity**")
            st.write("شباهت بر اساس تعداد تکرار واژه‌ها؛ بدون وزن‌دهی TF-IDF.")
            st.caption("این خط پایه آستانه یا تصمیم یکسانی رویداد ندارد.")
        with number:
            st.html(
                '<div class="primary-score"><span>امتیاز کسینوس BoW</span>'
                '<strong dir="ltr">'
                + escape(fa_number(f"{score:.4f}"))
                + "</strong></div>"
            )
        st.html(
            '<div class="similarity-track" role="meter" '
            'aria-label="کسینوس BoW" aria-valuemin="0" aria-valuemax="1" '
            f'aria-valuenow="{score}"><span style="width:{score * 100:.5f}%">'
            "</span></div>"
        )
        st.caption("مقیاس امتیاز: صفر تا یک؛ درصد اطمینان نیست.")
        with st.expander("جزئیات فنی تحلیل"):
            st.caption("CountVectorizer · شمارش واژه‌های تک‌واحدی در اتحاد واژگان دو متن")
            st.caption("پیش‌پردازش واژگانی موجود؛ بدون ریشه‌یابی یا حذف کلمات توقف.")
            st.dataframe(
                {
                    "واژه": result["vocabulary"],
                    "تعداد در خبر اول": result["counts_a"],
                    "تعداد در خبر دوم": result["counts_b"],
                },
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "دریافت گزارش JSON",
                json.dumps(view, ensure_ascii=False, indent=2, allow_nan=False),
                file_name="bow-cosine-comparison.json",
                mime="application/json",
                key=key + "_report",
            )
