import math

import streamlit as st

from news_similarity.ui.components.evidence_panel import evidence_panel
from news_similarity.ui.components.news_card import news_card
from news_similarity.ui.components.score_display import score_display
from news_similarity.ui.presentation import DECISIONS, fa_number, platform_label
from news_similarity.ui.services.ui_facade import UiError


def _clear_results():
    st.session_state.pop("explorer_results", None)


def _reset_archive():
    st.session_state["archive_page"] = 1
    _clear_results()


def render(facade):
    st.title("خبرهای مرتبط را پیدا کنید.")
    st.write(
        "از بایگانی یک خبر انتخاب کنید و گزارش‌های منبع دیگر را"
        " برای بررسی کنار آن ببینید."
    )
    try:
        _archive(facade)
    except UiError as error:
        st.error(str(error))


def _archive(facade):
    sources = facade.sources()
    total = facade.count_news()
    if not total:
        st.info("بایگانی خالی است. هنوز خبری برای مرور یا رتبه‌بندی ذخیره نشده است.")
        st.caption(
            "برای متن‌های دستی از صفحهٔ «مقایسهٔ خبر» استفاده "
            "کنید. وضعیت جمع‌آوری در «منابع خبر» مشخص است."
        )
        return
    names = {source.id: source.name for source in sources}
    controls = st.columns([3, 1, 1])
    source_id = controls[0].selectbox(
        "منبع بایگانی",
        [None, *names],
        format_func=lambda key: names.get(key, "همهٔ منبع‌ها"),
        key="archive_source",
        on_change=_reset_archive,
    )
    count = facade.count_news(source_id)
    page_count = max(1, math.ceil(count / 20))
    if st.session_state.get("archive_page", 1) > page_count:
        st.session_state["archive_page"] = 1
    page = controls[1].number_input(
        "صفحهٔ بایگانی",
        min_value=1,
        max_value=page_count,
        value=1,
        step=1,
        key="archive_page",
        on_change=_clear_results,
    )
    controls[2].button("تازه‌سازی", on_click=_reset_archive, width="stretch")
    news = facade.browse(source_id=source_id, limit=20, offset=(page - 1) * 20)
    if not news:
        st.info("در این صفحه خبری باقی نمانده است. بایگانی را تازه‌سازی کنید.")
        return
    by_id = {item.id: item for item in news}
    st.caption(
        f"صفحهٔ {fa_number(page)} از {fa_number(page_count)} · "
        f"{fa_number(count)} خبر در این انتخاب"
    )
    selected = st.selectbox(
        "خبر مبنا",
        list(by_id),
        format_func=lambda key: (
            by_id[key].text.replace("\n", " ")[:95] + " · " + by_id[key].source_name
        ),
        key="query_news",
        on_change=_clear_results,
    )
    query = by_id[selected]
    news_card(query, heading="خبر مبنا")
    alternatives = [source for source in sources if source.id != query.source_id]
    if not alternatives:
        st.info("برای رتبه‌بندی بین‌منبعی، به خبرهایی از یک منبع دیگر نیاز است.")
        return
    st.subheader("دامنهٔ جست‌وجو")
    filters = st.columns(2)
    platforms = sorted({source.platform for source in alternatives})
    platform = filters[0].selectbox(
        "پلتفرم مقصد",
        [None, *platforms],
        format_func=lambda value: (
            platform_label(value) if value else "همهٔ پلتفرم‌های ذخیره‌شده"
        ),
        key="target_platform",
        on_change=_clear_results,
    )
    targets = {
        source.id: source.name
        for source in alternatives
        if platform is None or source.platform == platform
    }
    target = filters[1].selectbox(
        "منبع مقصد",
        [None, *targets],
        format_func=lambda key: targets.get(key, "همهٔ منبع‌های دیگر"),
        key="target_source",
        on_change=_clear_results,
    )
    with st.form("explorer_form", border=False):
        cap, result_count = st.columns(2)
        limit = cap.selectbox("حداکثر خبرهای جدیدتر برای بررسی", [20, 50, 100], index=1)
        top_k = result_count.slider("تعداد نتیجه", 1, 20, 5)
        submitted = st.form_submit_button("یافتن خبرهای مرتبط", type="primary")
    st.caption(
        "این جست‌وجو فقط خبرهای ذخیره‌شده از منبع‌های دیگر را "
        "رتبه‌بندی می‌کند؛ بالاتر بودن امتیاز، تصمیم یکسان بودن"
        " رویداد نیست."
    )
    if submitted:
        _clear_results()
        with st.spinner("در حال مقایسهٔ خبرهای ذخیره‌شده با مدل محلی…"):
            ranked = facade.rank(
                query.id,
                target_source_id=target,
                platform=platform,
                limit=limit,
                top_k=top_k,
            )
        st.session_state["explorer_results"] = (query.id, ranked, limit)
    state = st.session_state.get("explorer_results")
    if state and state[0] == query.id:
        ranked = state[1]
        st.divider()
        st.subheader("نتیجهٔ آخرین جست‌وجوی ثبت‌شده")
        if not ranked:
            st.info("خبری از منبع‌های دیگر در این دامنه پیدا نشد.")
        for index, item in enumerate(ranked):
            score = item.result["combined_ranking_score"]
            value = f"{score:.4f}" if score is not None else "بدون امتیاز"
            label = DECISIONS.get(item.result["decision"], DECISIONS["uncertain"])
            with st.expander(
                f"{fa_number(index + 1)} · {item.news.source_name} · {value} · {label}",
                expanded=index == 0,
            ):
                news_card(item.news)
                score_display(item.result)
                evidence_panel(item.result["event_evidence"])


if __name__ == "__main__":
    from news_similarity.ui.runtime import get_facade

    render(get_facade())
