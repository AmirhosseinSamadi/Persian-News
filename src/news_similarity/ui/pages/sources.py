import streamlit as st

from news_similarity.ui.presentation import fa_number, platform_label, timestamp
from news_similarity.ui.services.ui_facade import UiError


def render(facade, *, compact=False):
    (st.subheader if compact else st.title)("منبع‌ها و وضعیت جمع‌آوری")
    st.write("آنچه در بایگانی ثبت شده، از وضعیت واقعی اتصال جداست.")
    try:
        history = facade.collection_status()
    except UiError as error:
        st.error(str(error))
        return
    for platform, column in zip(
        ("telegram", "bale"), st.columns(2, gap="large"), strict=True
    ):
        with column.container(border=True):
            st.subheader(platform_label(platform))
            st.write("جمع‌آوری محدود با Bot API پیاده‌سازی شده است.")
            entries = [entry for entry in history if entry["platform"] == platform]
            if not entries:
                st.caption("هنوز اجرای جمع‌آوری در این بایگانی ثبت نشده است.")
            for entry in entries:
                labels = {
                    "STORED": "ذخیره‌شده؛ بدون تأیید صف",
                    "BLOCKED": "متوقف؛ نیازمند بررسی",
                    "ACK_PENDING": "نتیجهٔ تأیید صف نیازمند بررسی است",
                    "ACK_UNKNOWN": "نتیجهٔ تأیید صف نامعلوم است",
                    "ACKNOWLEDGED": "پیشوند ذخیره‌شده تأیید شد",
                }
                st.write(labels.get(entry["status"], "نیازمند بررسی"))
                st.caption("آخرین ثبت: " + entry["updated_at"])
                st.caption(
                    f"رویدادهای منتظر: {fa_number(entry['pending_updates'])} · "
                    f"مسدود: {fa_number(entry['blocked_updates'])}"
                )
                if entry["evidence_origin"] != "live_http":
                    st.caption("دادهٔ آزمایشی؛ تأیید اتصال زنده نیست.")
    st.caption(
        "تنظیمات فقط خواندنی‌اند؛ این صفحه ورود به حساب، شروع "
        "جمع‌آوری یا بررسی شبکه انجام نمی‌دهد."
    )
    st.subheader("منبع‌های ثبت‌شده در پایگاه داده")
    st.button("تازه‌سازی فهرست")
    try:
        sources = facade.sources()
    except UiError as error:
        st.error(str(error))
        return
    if not sources:
        st.info("هنوز منبعی در این بایگانی ثبت نشده است.")
        return
    st.caption(
        f"{fa_number(len(sources))} منبع · زمان‌ها به UTC هستند. "
        "وجود داده، اتصال فعلی یا تأیید زندهٔ یکپارچه‌سازی را ثابت نمی‌کند."
    )
    st.dataframe(
        [
            {
                "منبع": item.name,
                "پلتفرم": platform_label(item.platform),
                "خبر ذخیره‌شده": item.news_count,
                "آخرین زمان انتشار": timestamp(item.latest_publication),
                "وضعیت داده": "خبر در بایگانی موجود است"
                if item.news_count
                else "هنوز خبری ذخیره نشده",
                "وضعیت اتصال فعلی": "این صفحه بررسی شبکه انجام نمی‌دهد",
                "پیوند منبع": item.url,
            }
            for item in sources
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "پیوند منبع": st.column_config.LinkColumn(display_text="مشاهدهٔ منبع")
        },
    )
    for item in sources:
        with st.expander(item.name + " · " + platform_label(item.platform)):
            st.text("شناسهٔ ثبت‌شده: " + item.external_id)
            st.caption(
                "آخرین زمان انتشارِ ذخیره‌شده: " + timestamp(item.latest_publication)
            )
            if item.url:
                st.link_button("صفحهٔ منبع", item.url)
            else:
                st.caption("پیوند منبع ثبت نشده است.")


if __name__ == "__main__":
    from news_similarity.ui.runtime import get_facade

    render(get_facade())
