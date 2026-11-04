"""Authored synthetic challenge families, prepared after the semantic freeze.

These are new event groups, not independently human annotated real reporting.
No model or scoring function is called while building or labeling this file.
"""

import argparse
import json
from pathlib import Path

from news_similarity.evaluation import load_dataset, validate_dataset
from news_similarity.semantic_evaluation import (
    file_sha256,
    load_semantic_freeze,
    validate_fresh_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/news_similarity/data/synthetic_fresh_v1.json"
MANIFEST = ROOT / "src/news_similarity/data/synthetic_fresh_v1.manifest.json"

# Every statement, measurement and event below is fictional.
FAMILIES = [
    (
        "same_event_paraphrase",
        1,
        "گروه مرجان در چابهار روز ۱۴۰۶/۰۱/۱۶ تعداد ۱۸ لاک‌پشت را به دریا بازگرداند.",
        [
            "۱۸ لاک‌پشت روز ۱۴۰۶/۰۱/۱۶ به دست گروه مرجان در ساحل چابهار رهاسازی شدند.",
            (
                "چابهار در ۱۴۰۶/۰۱/۱۶ محل بازگشت ۱۸ لاک\u200cپشت به دریا با "
                "همکاری گروه مرجان بود."
            ),
        ],
    ),
    (
        "same_event_paraphrase",
        1,
        (
            "آزمایشگاه آوا در مراغه روز ۱۴۰۶/۰۲/۰۷ نخستین حسگر صوتی "
            "زیرآب خود را آزمایش کرد."
        ),
        [
            (
                "نخستین آزمایش حسگر صوتی زیرآب آزمایشگاه آوا در مراغه در "
                "۱۴۰۶/۰۲/۰۷ انجام شد."
            ),
            (
                "روز ۱۴۰۶/۰۲/۰۷ پژوهشگران آزمایشگاه آوا در مراغه حسگر صوتی "
                "زیرآب تازه خود را آزمودند."
            ),
        ],
    ),
    (
        "near_identical",
        1,
        "سامانه هشدار بهمن فریدون‌شهر در ۱۴۰۶/۰۹/۲۱ فعال شد.",
        [
            "سامانه هشدار بهمن فریدون‌شهر، در ۱۴۰۶/۰۹/۲۱ فعال شد.",
            "سامانه هشدار بهمن فریدون‌شهر در تاریخ ۱۴۰۶/۰۹/۲۱ فعال شد.",
        ],
    ),
    (
        "near_identical",
        1,
        "نسخه دسترس‌پذیر نرم‌افزار دنا در ۱۴۰۶/۰۳/۱۲ منتشر شد.",
        [
            "نسخه دسترس‌پذیر نرم‌افزار دنا در ۱۴۰۶/۰۳/۱۲، منتشر شد.",
            "نسخه دسترس‌پذیر نرم‌افزار دنا در تاریخ ۱۴۰۶/۰۳/۱۲ منتشر شد.",
        ],
    ),
    (
        "same_topic_different_events",
        0,
        "ارتباط فیبر نوری بروجرد در ۱۴۰۶/۰۴/۲۲ به علت حفاری قطع شد.",
        [
            "ارتباط فیبر نوری تربت‌حیدریه در ۱۴۰۶/۰۴/۲۲ به علت حفاری قطع شد.",
            "ارتباط فیبر نوری خوی در ۱۴۰۶/۰۴/۲۲ به علت حفاری قطع شد.",
        ],
    ),
    (
        "same_topic_different_events",
        0,
        "اجرای گروه موسیقی چکاوک در دزفول روز ۱۴۰۶/۰۵/۰۲ آغاز شد.",
        [
            "اجرای گروه موسیقی نیستان در دزفول روز ۱۴۰۶/۰۵/۰۲ آغاز شد.",
            "اجرای گروه موسیقی چکاوک در طبس روز ۱۴۰۶/۰۵/۰۲ آغاز شد.",
        ],
    ),
    (
        "same_location_different_dates",
        0,
        "سرشماری زنبورستان‌های شهرضا در تاریخ ۱۴۰۶/۰۶/۰۴ آغاز شد.",
        [
            "سرشماری زنبورستان‌های شهرضا در تاریخ ۱۴۰۶/۰۶/۱۴ آغاز شد.",
            "سرشماری زنبورستان‌های شهرضا در تاریخ ۱۴۰۶/۰۶/۲۴ آغاز شد.",
        ],
    ),
    (
        "same_location_different_dates",
        0,
        "آزمون ایمنی آسانسور مجتمع ارغوان در ملارد روز ۱۴۰۶/۰۲/۰۹ انجام شد.",
        [
            "آزمون ایمنی آسانسور مجتمع ارغوان در ملارد روز ۱۴۰۶/۰۲/۱۹ انجام شد.",
            "آزمون ایمنی آسانسور مجتمع ارغوان در ملارد روز ۱۴۰۶/۰۲/۲۹ انجام شد.",
        ],
    ),
    (
        "different_numbers",
        0,
        "بازده گندم مزرعه آزمایشی بدره در ۱۴۰۶/۰۳/۲۵ برابر ۳٫۲ تن در هکتار بود.",
        [
            "بازده گندم مزرعه آزمایشی بدره در ۱۴۰۶/۰۳/۲۵ برابر ۴٫۲ تن در هکتار بود.",
            "بازده گندم مزرعه آزمایشی بدره در ۱۴۰۶/۰۳/۲۵ برابر ۵٫۲ تن در هکتار بود.",
        ],
    ),
    (
        "different_numbers",
        0,
        "مرکز بازیافت پاکان بهبهان در ۱۴۰۶/۰۷/۱۸ تعداد ۷۶ بسته کاغذ فشرده تحویل داد.",
        [
            (
                "مرکز بازیافت پاکان بهبهان در ۱۴۰۶/۰۷/۱۸ تعداد ۶۷ بسته کاغذ"
                " فشرده تحویل داد."
            ),
            (
                "مرکز بازیافت پاکان بهبهان در ۱۴۰۶/۰۷/۱۸ تعداد ۱۷۶ بسته "
                "کاغذ فشرده تحویل داد."
            ),
        ],
    ),
    (
        "negation_difference",
        0,
        "پناهگاه نیستان میانه در ۱۴۰۶/۰۸/۱۳ مجوز بازدید شبانه دریافت کرد.",
        [
            "پناهگاه نیستان میانه در ۱۴۰۶/۰۸/۱۳ مجوز بازدید شبانه دریافت نکرد.",
            (
                "پناهگاه نیستان میانه اعلام کرد مجوز بازدید شبانه در "
                "۱۴۰۶/۰۸/۱۳ صادر نشده است."
            ),
        ],
    ),
    (
        "negation_difference",
        0,
        "آزمون سازگاری سامانه پرداخت نارون در ۱۴۰۶/۰۴/۰۶ موفق بود.",
        [
            "آزمون سازگاری سامانه پرداخت نارون در ۱۴۰۶/۰۴/۰۶ موفق نبود.",
            (
                "مسئول سامانه پرداخت نارون موفقیت آزمون سازگاری در "
                "۱۴۰۶/۰۴/۰۶ را تکذیب کرد."
            ),
        ],
    ),
    (
        "unrelated",
        0,
        "گروه روباتیک رها در شوشتر روز ۱۴۰۶/۰۱/۲۳ بازوی برداشت خرما ساخت.",
        [
            "نقشه گویش‌های محلی در کتابخانه دیجیتال اهر روز ۱۴۰۶/۰۵/۱۷ منتشر شد.",
            "بازارچه حصیربافی در ایرانشهر روز ۱۴۰۶/۰۶/۲۷ آغاز به کار کرد.",
        ],
    ),
    (
        "unrelated",
        0,
        "مدار آزمایشی بازیابی انرژی ترمز در کارگاه پیشرو آمل روز ۱۴۰۶/۰۹/۱۱ ساخته شد.",
        [
            "فهرست گونه‌های پروانه در باغ پژوهشی نکا روز ۱۴۰۶/۰۲/۲۱ تکمیل شد.",
            "گروه نمایش سایه در گچساران روز ۱۴۰۶/۰۳/۰۸ نمایشنامه تازه‌ای اجرا کرد.",
        ],
    ),
    (
        "short_long",
        1,
        "برنامه بازیافت زباله الکترونیکی قشم در ۱۴۰۶/۰۷/۰۳ آغاز شد.",
        [
            (
                "برنامه بازیافت زباله الکترونیکی قشم در ۱۴۰۶/۰۷/۰۳ آغاز شد."
                " شهروندان می\u200cتوانند دستگاه\u200cهای ازکارافتاده را به محل "
                "تعیین\u200cشده تحویل دهند. مسئول برنامه گفت قطعات پس از جداسازی"
                " برای بازیابی مواد به مرکز تخصصی منتقل می\u200cشوند و هدف این "
                "طرح کاهش دورریز تجهیزات الکترونیکی است."
            ),
            (
                "قشم روز ۱۴۰۶/۰۷/۰۳ برنامه بازیافت زباله الکترونیکی را آغاز"
                " کرد. در این برنامه دستگاه\u200cهای خراب از شهروندان دریافت و "
                "قطعات آن\u200cها جداسازی می\u200cشود. مسئول طرح توضیح داد که مواد "
                "قابل بازیابی به مرکز تخصصی فرستاده می\u200cشوند تا دورریز "
                "تجهیزات الکترونیکی کاهش یابد."
            ),
        ],
    ),
    (
        "short_long",
        1,
        "پویش ثبت نام‌های بومی گیاهان در اردکان روز ۱۴۰۶/۰۵/۲۶ شروع شد.",
        [
            (
                "پویش ثبت نام\u200cهای بومی گیاهان در اردکان روز ۱۴۰۶/۰۵/۲۶ شروع"
                " شد. داوطلبان با گفت\u200cوگو با ساکنان محلی نام\u200cهای رایج "
                "گیاهان را ثبت می\u200cکنند. مسئول پویش گفت هدف این کار حفظ دانش"
                " زبانی و طبیعی منطقه است و اطلاعات پس از بررسی در یک فهرست"
                " عمومی قرار خواهد گرفت."
            ),
            (
                "اردکان در ۱۴۰۶/۰۵/۲۶ پویش ثبت نام\u200cهای بومی گیاهان را آغاز "
                "کرد. داوطلبان نام\u200cهای محلی را از ساکنان می\u200cپرسند و همراه "
                "با توضیحات ثبت می\u200cکنند. این پویش برای حفظ دانش زبانی و "
                "طبیعی منطقه طراحی شده و فهرست نهایی پس از بررسی در دسترس "
                "عموم قرار می\u200cگیرد."
            ),
        ],
    ),
]


def build_document() -> dict:
    pairs = []
    for group_index, (category, label, base, alternatives) in enumerate(FAMILIES, 1):
        group = f"fresh-family-{group_index:02}"
        for alternative_index, alternative in enumerate(alternatives, 1):
            pairs.append(
                {
                    "pair_id": f"fresh-synthetic-{len(pairs) + 1:03}",
                    "text_a": base,
                    "text_b": alternative,
                    "label": label,
                    "category": category,
                    "event_group_id": group,
                    "event_id_a": f"{group}-claim-0",
                    "event_id_b": f"{group}-claim-{0 if label else alternative_index}",
                    "split": "test",
                    ("explanation"): (
                        "نمونه کاملاً ساختگی است؛ برچسب بر اساس تطابق رویداد و "
                        "جزئیات اصلی تعیین شده و داوری انسانی مستقل ندارد."
                    ),
                }
            )
    return {
        "schema_version": 1,
        "name": "synthetic-persian-news-fresh-v1",
        ("description"): (
            "مجموعه چالشی با گروه\u200cهای رویداد تازه؛ تمام اخبار ساختگی و "
            "برچسب\u200cها هم\u200cنویسنده\u200cاند؛ خبر واقعی یا داوری مستقل نیست."
        ),
        "language": "fa",
        "synthetic": True,
        "pairs": pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    freeze_path = ROOT / "artifacts/semantic/freeze.json"
    frozen = load_semantic_freeze(freeze_path)
    document = build_document()
    fresh = validate_dataset(document)
    screening = validate_fresh_dataset(load_dataset(), fresh)
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if (
            OUTPUT.read_text(encoding="utf-8") != text
            or json.loads(MANIFEST.read_text(encoding="utf-8"))["dataset_sha256"]
            != fresh.sha256
        ):
            parser.exit(1, "Fresh fixture or manifest differs from authored source.\n")
    else:
        if OUTPUT.exists() or MANIFEST.exists():
            parser.exit(
                1,
                "Fresh data already exists; do not silently overwrite "
                "an evaluated set.\n",
            )
        OUTPUT.write_text(text, encoding="utf-8", newline="\n")
        manifest = {
            "schema_version": 1,
            "dataset_sha256": fresh.sha256,
            "freeze_sha256_at_authoring": file_sha256(freeze_path),
            "model_revision": frozen["model"]["configuration"]["revision"],
            "semantic_threshold": frozen["threshold"],
            "baseline_sha256": frozen["baseline_sha256"],
            "screening": screening,
            "event_groups": 16,
            "pairs": 32,
            ("provenance"): (
                "synthetic authored after development freeze; no inference "
                "used to label or select fresh pairs; no independent human "
                "annotation"
            ),
        }
        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(
        json.dumps(
            {"dataset": fresh.summary(), "screening": screening},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
