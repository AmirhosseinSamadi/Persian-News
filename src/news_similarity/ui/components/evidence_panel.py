from html import escape

import streamlit as st

from news_similarity.ui.presentation import CONFIDENCE, FEATURES, fa_number

UNITS = {
    "IRR": "ریال",
    "meter": "متر",
    "kilogram": "کیلوگرم",
    "person": "نفر",
    "percent": "درصد",
    "watt": "وات",
    "minute": "دقیقه",
    "celsius": "سلسیوس",
    "km_per_hour": "کیلومتر بر ساعت",
    "tonne_per_hectare": "تن در هکتار",
}


def value_label(values):
    if not values:
        return "ثبت نشده"
    labels = []
    for value in values:
        text = str(value.get("value") if value.get("value") is not None else "نامشخص")
        text = {"affirmed": "مثبت", "negated": "منفی"}.get(text, text)
        if value.get("unit"):
            text += " " + UNITS.get(value["unit"], value["unit"])
        if value.get("calendar") == "unspecified":
            text += " (تقویم نامشخص)"
        labels.append(text)
    return "، ".join(labels)


def highlighted_evidence(item):
    clause, span = item["clause"], item["span"]
    start, end = span["start"] - clause["start"], span["end"] - clause["start"]
    text = clause["text"]
    if 0 <= start < end <= len(text) and text[start:end] == span["text"]:
        body = (
            escape(text[:start])
            + "<mark>"
            + escape(text[start:end])
            + "</mark>"
            + escape(text[end:])
        )
    else:
        body = escape(span["text"])
    return '<div class="evidence-copy" dir="rtl">' + body + "</div>"


def _finding(finding):
    kind = FEATURES.get(finding["feature_type"], finding["feature_type"])
    confidence = CONFIDENCE[finding["confidence"]]
    with st.expander(f"{kind} · {confidence}"):
        if finding["confidence"] == "explicit_match":
            st.caption(
                "مقدار استخراج‌شده همخوان است؛ این به‌تنهایی "
                "یکسان بودن رویداد را تأیید نمی‌کند."
            )
        elif finding["confidence"] == "confirmed_explicit_conflict":
            st.caption(
                "ادعاهای صریح در زمینهٔ هم‌تراز ناسازگارند؛ "
                "ممکن است مربوط به یک رویداد یا اصلاح خبر "
                "باشند."
            )
        elif finding["confidence"] == "possible_conflict":
            st.caption(
                "این مقادیر تفاوت دارند، اما برای اثبات رویداد متفاوت کافی نیستند."
            )
        else:
            st.caption(
                "اطلاعات برای هم‌ترازی این ویژگی کافی نیست. "
                "استخراج نشدن، به‌معنای نبودن واقعیت در خبر "
                "نیست."
            )
        columns = st.columns(2)
        for column, side, title in (
            (columns[0], "a", "خبر الف"),
            (columns[1], "b", "خبر ب"),
        ):
            with column:
                st.caption(title + " · مقدار نرمال‌شده")
                st.text(value_label(finding[f"values_{side}"]))
                evidence = finding[f"evidence_{side}"]
                if not evidence:
                    st.caption("شاهد قابل نمایش وجود ندارد.")
                for item in evidence:
                    st.html(highlighted_evidence(item))


def evidence_summary(evidence):
    """Compact backend findings only; complete structures stay in technical details."""
    for column, title, key in zip(
        st.columns(2, gap="large"),
        ("شواهد مشترک", "تفاوت‌ها و تعارض‌های احتمالی"),
        ("matching_features", "conflicting_features"),
        strict=True,
    ):
        with column:
            st.markdown("**" + title + "**")
            findings = evidence.get(key) or []
            if not findings:
                st.caption("شاهدی در خروجی تحلیل ثبت نشده است.")
            for finding in findings[:4]:
                kind = FEATURES.get(finding.get("feature_type"), "ویژگی")
                values = (
                    value_label(finding.get("values_a")),
                    value_label(finding.get("values_b")),
                )
                confidence = CONFIDENCE.get(finding.get("confidence"), "نامعلوم")
                st.html(
                    '<div class="finding-summary"><strong>'
                    + escape(kind)
                    + "</strong><span>"
                    + escape(values[0])
                    + " ↔ "
                    + escape(values[1])
                    + "</span><small>"
                    + escape(confidence)
                    + "</small></div>"
                )
            if len(findings) > 4:
                st.caption(
                    f"{fa_number(len(findings) - 4)} مورد دیگر در جزئیات فنی تحلیل."
                )


def evidence_panel(evidence):
    st.subheader("شواهد موجود در تحلیل")
    for column, title, key in zip(
        st.columns(2, gap="large"),
        ("شواهد مشترک", "تفاوت‌های قابل بررسی"),
        ("matching_features", "conflicting_features"),
        strict=True,
    ):
        with column, st.container(border=True):
            findings = evidence.get(key, [])
            st.markdown("**" + title + " · " + fa_number(len(findings)) + "**")
            if not findings:
                st.caption(
                    "شاهدی در این بخش ثبت نشده است؛ از آن نتیجهٔ تازه‌ای نمی‌توان گرفت."
                )
            for finding in findings:
                _finding(finding)
    with st.expander("اطلاعات ناقص یا نامعلوم"):
        findings = evidence.get("missing_or_unknown_features", [])
        if not findings:
            st.caption("موردی در این بخش ثبت نشده است.")
        for finding in findings:
            _finding(finding)
