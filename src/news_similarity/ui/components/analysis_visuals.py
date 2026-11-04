"""Presentation-only SVG and evidence spans; no matching rules or thresholds."""

import math
import re
from html import escape
from numbers import Real

import streamlit as st

from news_similarity.event_features import normalized_view
from news_similarity.ui.presentation import CONFIDENCE, FEATURES, fa_number


def valid_score(value):
    return (
        isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    )


def score_gauge(value, decision):
    available = valid_score(value) and 0 <= value <= 1
    number = fa_number(f"{value:.4f}") if available else "—"
    offset = 326.73 * (1 - value) if available else 326.73
    tone = {
        "likely_same_event": "same",
        "likely_different_event": "different",
    }.get(decision, "uncertain")
    return (
        f'<div class="score-gauge {tone}" role="img" '
        f'aria-label="امتیاز خام شباهت: {escape(number)}">'
        '<svg viewBox="0 0 128 128" aria-hidden="true">'
        '<circle class="gauge-track" cx="64" cy="64" r="52"/>'
        f'<circle class="gauge-value" cx="64" cy="64" r="52" '
        f'style="stroke-dashoffset:{offset:.5f}"/></svg>'
        f'<div class="gauge-number">{escape(number)}'
        "<small>امتیاز ترکیبی</small></div></div>"
    )


def model_bars(result):
    rows = []
    for title, key, lower in (
        ("TF-IDF واژه‌ای", "word_similarity", 0),
        ("TF-IDF نویسه‌ای", "character_similarity", 0),
        ("MiniLM معنایی", "semantic_similarity", -1),
        ("امتیاز ترکیبی", "combined_ranking_score", 0),
    ):
        value = result.get(key)
        available = valid_score(value) and lower <= value <= 1
        label = fa_number(f"{value:.4f}") if available else "موجود نیست"
        zero = -lower / (1 - lower) * 100
        position = (value - lower) / (1 - lower) * 100 if available else zero
        left, width = min(zero, position), abs(position - zero)
        rows.append(
            f'<div class="model-row"><div class="model-bar-label">{title}'
            f'<b dir="ltr">{escape(label)}</b></div>'
            '<div class="model-track" role="img" '
            f'aria-label="{title}: {escape(label)}">'
            f'<span class="model-zero" style="left:{zero}%"></span>'
            f'<span class="model-fill" style="left:{left}%;width:{width}%">'
            '</span></div><div class="bar-scale">'
            f"<span>{fa_number(lower)}</span><span>۱</span></div></div>"
        )
    return '<div class="model-bars">' + "".join(rows) + "</div>"


def evidence_spans(text, evidence, side, *, kinds=None, include_unknown=False):
    """Only verified original offsets may become visual evidence."""
    spans = []
    groups = [("matching_features", "shared"), ("conflicting_features", "possible")]
    if include_unknown:
        groups.append(("missing_or_unknown_features", "unknown"))
    for group, category in groups:
        for finding in evidence.get(group, []):
            kind = finding.get("feature_type")
            if kinds is not None and kind not in kinds:
                continue
            confidence = finding.get("confidence", "")
            tone = (
                "conflict" if confidence == "confirmed_explicit_conflict" else category
            )
            label = (
                FEATURES.get(kind, kind or "شاهد")
                + " · "
                + CONFIDENCE.get(confidence, "نامعلوم")
            )
            for item in finding.get("evidence_" + side, []):
                span = item.get("span", {})
                start, end = span.get("start"), span.get("end")
                if (
                    type(start) is int
                    and type(end) is int
                    and 0 <= start < end <= len(text)
                    and text[start:end] == span.get("text")
                ):
                    spans.append((start, end, tone, label))
    return spans


def lexical_spans(first, second):
    """Literal normalized word overlap, descriptive only; not attribution."""

    def tokens(text):
        normalized, offsets = normalized_view(text)
        return [
            (m.group(), offsets[m.start()][0], offsets[m.end() - 1][1])
            for m in re.finditer(r"[^\W_]+", normalized)
            if len(m.group()) >= 3 or m.group().isdigit()
        ]

    left, right = tokens(first), tokens(second)
    shared = {t[0] for t in left} & {t[0] for t in right}
    return tuple(
        [
            (start, end, "lexical", "اشتراک واژگانی؛ توضیح تصمیم مدل نیست")
            for word, start, end in words
            if word in shared
        ]
        for words in (left, right)
    )


def highlighted_text(text, spans):
    """Escape all user text; split overlapping spans without changing characters."""
    points = sorted({0, len(text), *(p for s in spans for p in s[:2])})
    priority = {"conflict": 5, "possible": 4, "unknown": 3, "shared": 2, "lexical": 1}
    pieces = []
    for start, end in zip(points, points[1:], strict=False):
        active = [s for s in spans if s[0] <= start and s[1] >= end]
        body = escape(text[start:end])
        if active:
            chosen = max(active, key=lambda s: priority[s[2]])
            body = (
                f'<mark class="ev-{chosen[2]}" '
                f'title="{escape(chosen[3], quote=True)}">{body}</mark>'
            )
        pieces.append(body)
    return '<div class="evidence-text" dir="rtl">' + "".join(pieces) + "</div>"


def evidence_explorer(result, first=None, second=None, *, key="stored"):
    evidence = result.get("event_evidence") or {}
    first = (
        first if first is not None else evidence.get("news_a", {}).get("original_text")
    )
    second = (
        second
        if second is not None
        else evidence.get("news_b", {}).get("original_text")
    )
    if not isinstance(first, str) or not isinstance(second, str):
        st.info("متن‌های اصلی برای نمایش تعاملی در این خروجی موجود نیستند.")
        return
    st.subheader("کاوش در متن و شواهد")
    has_spans = bool(
        evidence_spans(first, evidence, "a") or evidence_spans(second, evidence, "b")
    )
    mode = st.radio(
        "روش نمایش متن",
        ["شواهد استخراج‌شده", "هم‌پوشانی واژگانی", "متن اصلی"],
        index=0 if has_spans else 1,
        horizontal=True,
        key=key + "_evidence_mode",
    )
    spans = ([], [])
    if mode == "شواهد استخراج‌شده":
        kinds = st.multiselect(
            "نوع شواهد",
            list(FEATURES),
            default=list(FEATURES),
            format_func=FEATURES.get,
            key=key + "_evidence_types",
        )
        unknown = st.checkbox("نمایش اطلاعات ناکافی", key=key + "_show_unknown")
        spans = (
            evidence_spans(first, evidence, "a", kinds=kinds, include_unknown=unknown),
            evidence_spans(second, evidence, "b", kinds=kinds, include_unknown=unknown),
        )
        st.html(
            '<div class="evidence-legend"><span class="ev-shared">همخوان</span>'
            '<span class="ev-possible">تفاوت احتمالی</span>'
            '<span class="ev-conflict">تعارض صریح ادعا</span>'
            '<span class="ev-unknown">اطلاعات ناکافی</span></div>'
        )
        st.caption(
            "رنگ‌ها فقط شواهد استخراج‌شده‌اند؛ "
            "تفاوت به‌تنهایی رویداد متفاوت را ثابت نمی‌کند."
        )
        if not any(spans):
            st.info("شاهد دارای محدودهٔ معتبر برای این انتخاب موجود نیست.")
    elif mode == "هم‌پوشانی واژگانی":
        spans = lexical_spans(first, second)
        st.caption(
            "نمایش توصیفی واژه‌های مشترک با یکسان‌سازی نویسه و رقم؛ "
            "واژه‌های کوتاه غیرعددی کنار گذاشته می‌شوند. "
            "این توضیح تصمیم یا توجه مدل نیست."
        )
        if not any(spans):
            st.info("هم‌پوشانی واژگانی قابل نمایش پیدا نشد.")
    for column, title, text, marks in zip(
        st.columns(2, gap="large"),
        ("خبر اول · متن اصلی", "خبر دوم · متن اصلی"),
        (first, second),
        spans,
        strict=True,
    ):
        with column, st.container(border=True):
            st.markdown("**" + title + "**")
            with st.container(height=300, border=False):
                st.html(highlighted_text(text, marks))
