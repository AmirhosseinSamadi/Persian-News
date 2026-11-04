import pandas as pd
import streamlit as st

from news_similarity.ui.presentation import MODEL_LABELS, SCENARIOS, fa_number
from news_similarity.ui.services.benchmarks import presentation_metrics, read_benchmarks

METRICS = {
    "precision": "دقت مثبت",
    "recall": "بازخوانی",
    "f1": "F1",
    "accuracy": "صحت",
    "false_positive_rate": "مثبت کاذب",
    "false_negative_rate": "منفی کاذب",
    "coverage": "پوشش تصمیم",
    "abstention_rate": "انصراف",
}


def _rows(models):
    return [
        {
            "مدل": MODEL_LABELS.get(name, name),
            **{label: entry["metrics"].get(key) for key, label in METRICS.items()},
        }
        for name, entry in models.items()
    ]


def _table(rows):
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            label: st.column_config.NumberColumn(format="%.3f")
            for label in METRICS.values()
        },
    )


def render(facade, *, compact=False):
    (st.subheader if compact else st.title)("مدل‌ها چه چیزی را نشان داده‌اند؟")
    st.write("نتایج اندازه‌گیری‌شدهٔ فایل‌های ارزیابی؛ هر مجموعه‌داده جدا از دیگری.")
    st.info(
        "همهٔ این ارزیابی‌ها روی دادهٔ مصنوعی انجام شده‌اند. دو"
        " مجموعه قبلاً بررسی شده‌اند؛ ارزیابی مستقل روی خبر "
        "واقعی در دسترس نیست."
    )
    artifacts = read_benchmarks(facade.config.artifacts)
    family = st.selectbox("خانوادهٔ مدل", [item.family for item in artifacts], index=2)
    artifact = next(item for item in artifacts if item.family == family)
    if artifact.error:
        st.info(artifact.error)
        st.caption(
            "فایل‌های نتایج باید از اجرای قبلی CLI موجود باشند؛"
            " رابط ارزیابی یا آموزش تازه‌ای اجرا نمی‌کند."
        )
        return
    if artifact.family == "Hybrid":
        full_results = [
            dataset.models["hybrid"]["metrics"]
            for dataset in artifact.datasets
            if "hybrid" in dataset.models
        ]
        if full_results and all(metrics["coverage"] == 0 for metrics in full_results):
            total = sum(metrics["count"] for metrics in full_results)
            st.warning(
                f"مدل ترکیبی روی هر {fa_number(total)} جفت این پرونده "
                "انصراف داده است؛ پوشش و صحت سخت‌گیرانه صفرند. "
                "مثبت کاذب صفر حاصل انصراف است، نه بهبود تشخیص رویداد. "
                "مدل آمادهٔ استفادهٔ خودکار واقعی نیست."
            )
    dataset_key = st.selectbox(
        "مجموعهٔ ارزیابی",
        [item.key for item in artifact.datasets],
        format_func=lambda key: next(
            item.title for item in artifact.datasets if item.key == key
        ),
    )
    dataset = next(item for item in artifact.datasets if item.key == dataset_key)
    count = next(iter(dataset.models.values()))["metrics"]["count"]
    st.subheader(dataset.title)
    st.caption(
        f"{fa_number(count)} جفت · نرخ‌ها بین صفر و یک‌اند. "
        "امتیازهای این جدول معیار ارزیابی‌اند، نه احتمال برای یک خبر."
    )
    _table(_rows(dataset.models))
    st.caption(
        "در مدل سه‌حالته، انصراف در صحت خطا محسوب شده و انصراف "
        "از نمونهٔ مثبت در بازخوانی/منفی کاذب به‌صورت "
        "از‌دست‌رفتن نمونه حساب می‌شود. نرخ مثبت کاذب را همراه "
        "پوشش بخوانید."
    )
    selected = st.selectbox(
        "ماتریس درهم‌ریختگی مدل",
        list(dataset.models),
        format_func=lambda name: MODEL_LABELS.get(name, name),
    )
    metrics = dataset.models[selected]["metrics"]
    matrix = metrics["confusion_matrix"]
    columns = ["پیش‌بینی: متفاوت", "پیش‌بینی: یکسان"] + (
        ["نامطمئن"] if len(matrix[0]) == 3 else []
    )
    st.table(
        pd.DataFrame(matrix, index=["واقعی: متفاوت", "واقعی: یکسان"], columns=columns)
    )
    if metrics.get("decided_only"):
        conditional = metrics["decided_only"]
        st.caption("تعداد تصمیم‌های بدون انصراف: " + fa_number(conditional["count"]))
        if not conditional["count"]:
            st.caption(
                "معیارهای مشروط به تصمیم در دسترس نیستند؛ هیچ تصمیمی صادر نشده است."
            )
    with st.expander("عملکرد به تفکیک سناریو"):
        rows = []
        for name, entry in dataset.models.items():
            for category, values in entry["per_scenario"].items():
                row = {
                    "سناریو": SCENARIOS.get(category, category),
                    "مدل": MODEL_LABELS.get(name, name),
                }
                normalized = presentation_metrics(values)
                row.update(
                    {label: normalized.get(key) for key, label in METRICS.items()}
                )
                rows.append(row)
        if rows:
            _table(rows)
        else:
            st.caption("نتیجهٔ تفکیکی در این پرونده ذخیره نشده است.")
    st.caption("خوانده‌شده از: " + artifact.path.name + " · فقط خواندنی")


if __name__ == "__main__":
    from news_similarity.ui.runtime import get_facade

    render(get_facade())
