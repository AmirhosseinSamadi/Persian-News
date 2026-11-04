"""A button-gated, non-acknowledging collection action shared by both views."""

from datetime import UTC, datetime

import streamlit as st

from news_similarity.ui.presentation import fa_number, platform_label
from news_similarity.ui.services.collection import REASONS


def collection_panel(facade):
    with st.container(border=True, key="collection_panel"):
        heading, action = st.columns([2, 1], vertical_alignment="center")
        heading.markdown("**اخبار تازه از منابع شما**")
        heading.caption(
            "دریافت محدود از کانال‌های مجاز؛ بدون تأیید یا پاک‌کردن صف پیام‌ها."
        )
        with st.expander("انتخاب پیام‌رسان و اجازهٔ دریافت"):
            selected = st.multiselect(
                "دریافت از",
                ["telegram", "bale"],
                default=["telegram", "bale"],
                format_func=platform_label,
                key="collection_platforms",
            )
            exclusive = st.checkbox(
                "این ربات‌ها اختصاصی‌اند و مصرف‌کنندهٔ دیگری برای آن‌ها فعال نیست.",
                key="collection_exclusive",
            )
            st.caption("تنظیمات و اعتبارنامه‌ها فقط از فایل محیط ربات خوانده می‌شوند.")
        clicked = action.button(
            "دریافت اخبار جدید",
            key="fetch_news",
            type="primary",
            width="stretch",
            disabled=not exclusive or not selected or facade.config.demo_mode,
        )
        if clicked:
            reports = []
            progress = st.progress(0, text="آماده‌سازی دریافت…")
            for index, platform in enumerate(selected):
                with st.status(
                    "دریافت از " + platform_label(platform), expanded=True
                ) as status:
                    st.write("بررسی دسترسی، قفل ربات، خواندن محدود و ذخیرهٔ خبرها…")
                    report = facade.collect_news(platform, exclusive_bot=exclusive)
                    reports.append(report)
                    status.update(
                        label=platform_label(platform)
                        + " · "
                        + (
                            "دریافت پایان یافت"
                            if report["status"] == "STORED"
                            else "نیازمند بررسی"
                        ),
                        state="complete" if report["status"] == "STORED" else "error",
                        expanded=False,
                    )
                progress.progress(
                    (index + 1) / len(selected), text="بررسی منابع انتخاب‌شده"
                )
            progress.empty()
            st.session_state["collection_report"] = {
                "time": datetime.now(UTC).strftime("%Y/%m/%d · %H:%M UTC"),
                "reports": reports,
            }
            # The page below reads SQLite afresh in this same button run. Keep
            # existing selections/results; newly inserted records join the list.
        state = st.session_state.get("collection_report")
        if state:
            st.caption("آخرین درخواست شما: " + state["time"])
            for report in state["reports"]:
                title = platform_label(report["platform"])
                counts = " · ".join(
                    label + ": " + fa_number(report[key])
                    for key, label in (
                        ("received_updates", "رویداد دریافتی"),
                        ("inserted", "خبر جدید"),
                        ("duplicates", "تکراری"),
                        ("blocked_updates", "مسدود"),
                    )
                    if key in report
                )
                if report.get("reason"):
                    st.warning(title + " · " + REASONS[report["reason"]])
                elif report.get("received_updates") == 0:
                    st.info(title + " · در این درخواست رویداد تازه‌ای برنگشت.")
                else:
                    st.success(title + " · دریافت و ذخیره پایان یافت.")
                if counts:
                    st.caption(title + " · " + counts)
            st.caption(
                "صف تأیید نشده است؛ پیام‌های قدیمی ممکن است دوباره برگردند. "
                "اگر صف قدیمی جلوی پیام‌های جدید را بگیرد، "
                "بررسی صف از مسیر جداگانه لازم است."
            )
