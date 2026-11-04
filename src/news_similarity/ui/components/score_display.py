"""One coherent comparison result; secondary output stays in one expander."""

import json
import math
from html import escape
from numbers import Real

import streamlit as st

from news_similarity.ui.components.evidence_panel import evidence_summary
from news_similarity.ui.presentation import DECISIONS, fa_number


def _available(value):
    return (
        isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    )


def interpretation(result):
    decision = result.get("decision")
    if decision == "likely_same_event":
        return (
            "مدل این دو خبر را احتمالاً مربوط به یک رویداد می‌داند؛ "
            "این نتیجه تأیید صحت خبر نیست."
        )
    if decision == "likely_different_event":
        return "مدل احتمال می‌دهد این دو خبر به رویدادهای متفاوت مربوط باشند."
    if decision == "uncertain":
        conflicts = (result.get("event_evidence") or {}).get("conflicting_features")
        if conflicts:
            return (
                "تفاوت‌هایی در شواهد ثبت شده، اما مدل دربارهٔ یکسانی رویدادها "
                "تصمیم نگرفته است."
            )
        return "اطلاعات موجود برای تصمیم روشن دربارهٔ یکسانی رویدادها کافی نیست."
    return "تصمیم معتبر رویدادی در خروجی تحلیل موجود نیست."


def score_display(result, *, key=None, report=None):
    result = result or {}
    evidence = result.get("event_evidence") or {}
    with st.container(border=True, key=key):
        st.subheader("نتیجهٔ مقایسه")
        decision, number = st.columns([2, 1], gap="large", vertical_alignment="center")
        with decision:
            kind = result.get("decision")
            label = DECISIONS.get(kind, "تصمیم در دسترس نیست")
            if kind == "uncertain":
                with st.container(key=(key or "manual") + "_uncertain"):
                    st.warning(label)
            else:
                st.markdown("**" + label + "**")
            st.write(interpretation(result))
        value = result.get("combined_ranking_score")
        available = _available(value) and 0 <= value <= 1
        with number:
            shown = fa_number(f"{value:.4f}") if available else "—"
            st.html(
                '<div class="primary-score"><span>امتیاز شباهت ترکیبی</span>'
                '<strong dir="ltr">' + escape(shown) + "</strong></div>"
            )
        if available:
            st.html(
                '<div class="similarity-track" role="meter" '
                'aria-label="شباهت ترکیبی" aria-valuemin="0" aria-valuemax="1" '
                f'aria-valuenow="{value}"><span style="width:{value * 100:.5f}%">'
                "</span></div>"
            )
        else:
            st.caption("امتیاز ترکیبی معتبر در خروجی این تحلیل موجود نیست.")
        st.caption("مقیاس امتیاز: صفر تا یک؛ درصد اطمینان نیست.")
        evidence_summary(evidence)
        with st.expander("جزئیات فنی تحلیل"):
            rows = [
                {
                    "مدل": name,
                    "امتیاز خام": result.get(field)
                    if _available(result.get(field))
                    else None,
                }
                for name, field in (
                    ("TF-IDF واژه‌ای", "word_similarity"),
                    ("TF-IDF نویسه‌ای", "character_similarity"),
                    ("MiniLM معنایی", "semantic_similarity"),
                )
            ]
            st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "امتیاز خام": st.column_config.NumberColumn(format="%.4f")
                },
            )
            if result.get("metadata"):
                st.caption("تنظیمات، آستانه‌ها و مدل‌های ثبت‌شده در خروجی")
                st.json(result["metadata"])
            else:
                st.caption("اطلاعات مدل و آستانه‌ها در این خروجی ثبت نشده است.")
            if evidence:
                st.caption("شواهد ساختاری خروجی تحلیل")
                st.json(evidence)
            else:
                st.info("شواهد ساختاری در خروجی این تحلیل موجود نیست.")
            if report is not None:
                sources = {
                    k: report[k] for k in ("source_a", "source_b") if report.get(k)
                }
                if sources:
                    st.json(sources)
                st.download_button(
                    "دریافت گزارش JSON",
                    json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                    file_name="hamkhabar-comparison.json",
                    mime="application/json",
                    key=(key or "manual") + "_report",
                )
