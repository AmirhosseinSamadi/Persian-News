import hashlib

import streamlit as st

from news_similarity.ui.components.score_display import score_display
from news_similarity.ui.components.stored_selection import selection_panel
from news_similarity.ui.services.ui_facade import MAX_TEXT_LENGTH, SourceInput, UiError


def _fingerprint(first, second):
    if first is None or second is None:
        return None
    return (
        first.id,
        second.id,
        hashlib.sha256(first.text.encode()).hexdigest(),
        hashlib.sha256(second.text.encode()).hexdigest(),
    )


def render(facade):
    st.html('<div class="eyebrow">مقایسهٔ بین دو پیام‌رسان</div>')
    st.title("دو خبر، یک رویداد؟")
    st.write(
        "یک خبر از تلگرام و یک خبر از بله انتخاب کنید؛ "
        "شباهت متن و شواهد را کنار هم ببینید."
    )
    try:
        columns = st.columns(2, gap="large")
        with columns[0]:
            first = selection_panel(facade, "telegram")
        with columns[1]:
            second = selection_panel(facade, "bale")
    except UiError as error:
        st.error(str(error))
        return
    fingerprint = _fingerprint(first, second)
    previous = st.session_state.get("stored_comparison")
    if previous and previous["fingerprint"] != fingerprint:
        st.session_state.pop("stored_comparison", None)
    ready = first is not None and second is not None and first.id != second.id
    with st.container(key="compare_action"):
        button, note = st.columns([1, 2], gap="large")
        submitted = button.button(
            "مقایسه اخبار",
            key="compare_stored",
            type="primary",
            width="stretch",
            disabled=not ready,
        )
        note.caption(
            "تحلیل فقط با این دکمه اجرا می‌شود؛ "
            "دریافت خبر از دکمهٔ جداگانهٔ بالای صفحه است."
        )
    if submitted and ready:
        st.session_state.pop("stored_comparison", None)
        try:
            with st.spinner("در حال مقایسهٔ متن‌ها و بررسی شواهد…"):
                view = facade.compare_stored(first.id, second.id)
            st.session_state["stored_comparison"] = {
                "fingerprint": fingerprint,
                "view": view.to_dict(),
            }
        except UiError as error:
            st.error(str(error))
    state = st.session_state.get("stored_comparison")
    if state:
        result = state["view"]["result"]
        score_display(result, key="analysis_result", report=state["view"])
    else:
        st.html(
            '<div class="result-placeholder"><strong>'
            "نتیجهٔ مقایسه اینجا نمایش داده می‌شود</strong>"
            "پس از انتخاب دو خبر، «مقایسه اخبار» را بزنید.</div>"
        )
    with st.expander("مقایسهٔ متن دلخواه · اختیاری"):
        _manual(facade)


def _manual(facade):
    st.caption("برای بررسی متنی که هنوز در بایگانی نیست؛ این بخش چیزی ذخیره نمی‌کند.")
    with st.form("comparison_form", border=False):
        a, b = st.columns(2, gap="large")
        with a:
            st.subheader("خبر الف")
            text_a = st.text_area(
                "متن خبر الف",
                height=265,
                max_chars=MAX_TEXT_LENGTH,
                placeholder="متن اصلی خبر اول را اینجا وارد کنید…",
                key="text_a",
                label_visibility="collapsed",
            )
        with b:
            st.subheader("خبر ب")
            text_b = st.text_area(
                "متن خبر ب",
                height=265,
                max_chars=MAX_TEXT_LENGTH,
                placeholder="متن خبر دوم، بازنویسی یا گزارش منبع دیگر…",
                key="text_b",
                label_visibility="collapsed",
            )
        with st.expander("اطلاعات منبع‌ها · اختیاری"):
            source_a, source_b = st.columns(2)
            name_a = source_a.text_input(
                "نام منبع خبر الف", key="name_a", max_chars=200
            )
            url_a = source_a.text_input("پیوند منبع خبر الف", key="url_a")
            name_b = source_b.text_input("نام منبع خبر ب", key="name_b", max_chars=200)
            url_b = source_b.text_input("پیوند منبع خبر ب", key="url_b")
            st.caption("این اطلاعات را شما وارد می‌کنید و در تصمیم مدل دخالت ندارند.")
        action, note = st.columns([1, 2.7], gap="large")
        submitted = action.form_submit_button(
            "تحلیل دو خبر", type="primary", width="stretch", key="compare_manual"
        )
        note.caption(
            "تحلیل فقط با این دکمه اجرا می‌شود. پردازش مدل روی "
            "CPU و با فایل‌های محلی است."
        )
    if submitted:
        st.session_state.pop("comparison_view", None)
        try:
            with st.spinner("در حال بارگذاری مدل محلی و مقایسهٔ شواهد…"):
                view = facade.compare(
                    text_a,
                    text_b,
                    SourceInput(name_a, url_a),
                    SourceInput(name_b, url_b),
                )
            st.session_state["comparison_view"] = view.to_dict()
        except UiError as error:
            st.error(str(error))
    view = st.session_state.get("comparison_view")
    if view:
        st.divider()
        st.caption("نتیجهٔ آخرین مقایسهٔ ثبت‌شده")
        score_display(view["result"], key="manual_result", report=view)
    else:
        st.divider()
        st.caption(
            "از متن اصلی استفاده کنید؛ اعداد، تاریخ‌ها و نشانه‌های نفی را حذف نکنید."
        )
    st.caption(
        "این ابزار صحت خبر را تأیید نمی‌کند. ارزیابی فعلی "
        "مصنوعی است؛ نتیجهٔ «نامطمئن» باید همان‌طور تفسیر شود."
    )


if __name__ == "__main__":
    from news_similarity.ui.runtime import get_facade

    render(get_facade())
