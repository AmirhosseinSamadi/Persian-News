# Phase 1.3B: semantic similarity and comparative evaluation

All measured datasets in this report are synthetic. Historical results are exploratory because Phase 1.3A already exposed those test pairs. No real Telegram/Bale performance is claimed.

## Model architecture and source

Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Commit: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. The fixed multilingual MiniLM sentence encoder uses a transformer and mean-token pooling. It is not fine-tuned in this project.

[Official model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) and [SentenceTransformer loading/encoding API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).

Loaded metadata: embedding dimension=384; maximum sequence length=128 tokens; execution device=cpu. Dimensions come from the encoder, not a global constant.

## Embedding and similarity methodology

Use the existing conservative semantic profile's normalized prose, retaining sentence order, dates, numbers, names, locations and negation. There is no stopword filtering, stemming or lexical token rejoining. Empty input is rejected before model loading. Repeated normalized documents reuse a bounded in-memory LRU cache.

Embeddings are L2-normalized: $\hat e=e/\|e\|_2$. Similarity is $s(a,b)=\hat e_a^T\hat e_b$, in $[-1,1]$. Raw cosine scores are saved separately from thresholded predictions and are not calibrated probabilities. A score at or above the frozen threshold is predicted positive.

## Threshold selection and freezing

Selected threshold: **0.6604582132926925**. Only the original development labels selected this value: maximize F1, then precision, accuracy and higher threshold. The pretrained encoder/configuration is fixed and has no fitted corpus statistics.

A four-fold, seed-42 GroupKFold diagnostic selects a threshold on each training-group subset and applies it to its validation groups. Embeddings can be reused across folds because the frozen encoder does not learn from them. The final threshold uses all development groups. Selection-set metrics are optimistic; group-CV diagnostics do not change the final threshold.

| Development statistic | Precision | Recall | F1 | Accuracy | FPR | FNR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| development | 0.461538 | 1.000000 | 0.631579 | 0.562500 | 0.700000 | 0.000000 |
| group_cv_threshold_metrics | 0.333333 | 0.500000 | 0.400000 | 0.437500 | 0.600000 | 0.500000 |

`freeze.json` records the threshold, revision, runtime, preprocessing fingerprint, development pair IDs and unchanged TF-IDF artifact hashes. It was saved before historical/fresh inference. Frozen TF-IDF vocabulary, IDF, configurations and thresholds are loaded without refitting. All methods receive identical pairs within each comparison.

Original dataset checksum: `b547f8ed1378217c0aa7dc91bcaff8c8b5cd71b78add91635f9b6a32bec88dfd`.

## Fresh-set manifest

Dataset `synthetic-persian-news-fresh-v1`: 32 pairs across 16 event groups. Canonical checksum `27876f613af2b197ee7e8c2c24b6085d0580310ad83c6cf3e9ca3c91b49fbfaa`. Freeze anchor `49a7893cf6aaa89638094d97f042d91fa38214204a3b1f6bf79062a684fc841a`.

Fresh groups were authored after model/threshold freezing and locked before final inference. Pair/group/event IDs are disjoint from all original splits. Exact/near-duplicate screening masks digits and compares lexical-normalized character sequences, rejecting ratios >=0.85. This is a surface leakage check, not proof that every semantic relation is independent.

Maximum screened overlap: 0.623656.

These are new synthetic event groups with same-author labels, not independently annotated real news or an unbiased population sample. No independent-annotator final performance is available. After this evaluation the fresh set is also inspected and must not be reused as pristine evidence for subsequent model design.

## historical_exploratory

Confusion matrices are `[[TN, FP], [FN, TP]]`; class 1 is positive. FPR=FP/(TN+FP), FNR=FN/(FN+TP). A missing denominator is undefined, not zero. Other undefined positive metrics use zero_division=0.

| Model | N | Precision | Recall | F1 | Accuracy | FPR | FNR | Matrix |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| word | 24 | 0.400000 | 0.888889 | 0.551724 | 0.458333 | 0.800000 | 0.111111 | `[[3, 12], [1, 8]]` |
| character | 24 | 0.428571 | 1.000000 | 0.600000 | 0.500000 | 0.800000 | 0.000000 | `[[3, 12], [0, 9]]` |
| semantic | 24 | 0.450000 | 1.000000 | 0.620690 | 0.541667 | 0.733333 | 0.000000 | `[[4, 11], [0, 9]]` |

### Per-scenario performance

| Model | Scenario | N | Precision | Recall | F1 | Accuracy | FPR | FNR |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| word | different_numbers | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | near_identical | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| word | negation_difference | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | same_event_paraphrase | 3 | 1.000000 | 0.666667 | 0.800000 | 0.666667 | undefined | 0.333333 |
| word | same_location_different_dates | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | same_topic_different_events | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | short_long | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| word | unrelated | 3 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 0.000000 | undefined |
| character | different_numbers | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | near_identical | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| character | negation_difference | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | same_event_paraphrase | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| character | same_location_different_dates | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | same_topic_different_events | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | short_long | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| character | unrelated | 3 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 0.000000 | undefined |
| semantic | different_numbers | 3 | 0.000000 | 0.000000 | 0.000000 | 0.333333 | 0.666667 | undefined |
| semantic | near_identical | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| semantic | negation_difference | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | same_event_paraphrase | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| semantic | same_location_different_dates | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | same_topic_different_events | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | short_long | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| semantic | unrelated | 3 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 0.000000 | undefined |

### Paired error changes

Against word, semantic correct / baseline wrong: synthetic-006, synthetic-045.

Against word, semantic wrong / baseline correct: none.

Against character, semantic correct / baseline wrong: synthetic-045.

Against character, semantic wrong / baseline correct: none.

### Semantic false_positives (11)

| Pair | Scenario | Raw cosine |
| --- | --- | ---: |
| synthetic-025 | same_topic_different_events | 0.812018 |
| synthetic-026 | same_topic_different_events | 0.772711 |
| synthetic-027 | same_topic_different_events | 0.717536 |
| synthetic-031 | same_location_different_dates | 0.988741 |
| synthetic-032 | same_location_different_dates | 0.983561 |
| synthetic-033 | same_location_different_dates | 0.987789 |
| synthetic-043 | different_numbers | 0.952915 |
| synthetic-044 | different_numbers | 0.712812 |
| synthetic-055 | negation_difference | 0.774977 |
| synthetic-056 | negation_difference | 0.772910 |
| synthetic-057 | negation_difference | 0.879553 |

### Semantic false_negatives (0)

| Pair | Scenario | Raw cosine |
| --- | --- | ---: |

### Qualitative diagnostics

- `synthetic-043` (different_numbers): true=0, predicted=1, cosine=0.952915.
  A: بودجه پل سرو سنندج در ۱۴۰۵/۰۴/۰۱ برابر ۱۵۰ میلیارد تومان اعلام شد.
  B: بودجه پل سرو سنندج در ۱۴۰۵/۰۴/۰۱ برابر ۱۵ میلیارد تومان اعلام شد.

- `synthetic-013` (near_identical): true=1, predicted=1, cosine=0.998924.
  A: پرواز ۷۲۰ مشهد در ۱۴۰۵/۰۳/۱۸ به ساعت ۱۰:۳۰ منتقل شد.
  B: پرواز ۷۲۰ مشهد در تاریخ ۱۴۰۵/۰۳/۱۸ به ساعت ۱۰:۳۰ منتقل شد.

- `synthetic-055` (negation_difference): true=0, predicted=1, cosine=0.774977.
  A: شورای شهر اصفهان در ۱۴۰۵/۰۵/۱۰ طرح پارکینگ لاله را تصویب کرد.
  B: شورای شهر اصفهان در ۱۴۰۵/۰۵/۱۰ طرح پارکینگ لاله را تصویب نکرد.

- `synthetic-004` (same_event_paraphrase): true=1, predicted=1, cosine=0.836497.
  A: نیروگاه خورشیدی باران در یزد روز ۱۴۰۵/۰۶/۱۵ با ظرفیت ۱۲ مگاوات وارد مدار شد.
  B: تولید برق نیروگاه ۱۲ مگاواتی خورشیدی باران در یزد از ۱۴۰۵/۰۶/۱۵ آغاز شد.

- `synthetic-031` (same_location_different_dates): true=0, predicted=1, cosine=0.988741.
  A: بارش ۸ میلی‌متری باران در ایلام برای روز ۱۴۰۵/۰۸/۰۳ ثبت شد.
  B: بارش ۸ میلی‌متری باران در ایلام برای روز ۱۴۰۵/۰۸/۱۳ ثبت شد.

- `synthetic-025` (same_topic_different_events): true=0, predicted=1, cosine=0.812018.
  A: آزمون ورودی رشته معماری دانشگاه اندیشه در کرمان روز ۱۴۰۵/۰۳/۰۱ برگزار شد.
  B: آزمون ورودی رشته موسیقی دانشگاه اندیشه در کرمان روز ۱۴۰۵/۰۳/۰۸ برگزار شد.

- `synthetic-064` (short_long): true=1, predicted=1, cosine=0.855108.
  A: موزه سفال میبد در ۱۴۰۵/۰۲/۱۱ بازگشایی شد.
  B: موزه سفال میبد در ۱۴۰۵/۰۲/۱۱ بازگشایی شد. مدیر این مجموعه گفت درهای موزه پس از پایان تعمیرات دوباره به روی بازدیدکنندگان باز شده است و علاقه‌مندان می‌توانند از بخش نمایش ظروف سفالی و کارگاه آموزشی آن دیدن کنند.

- `synthetic-046` (unrelated): true=0, predicted=0, cosine=0.127307.
  A: گروه نجوم آسمان در اردبیل روز ۱۴۰۵/۰۵/۰۵ یک دنباله‌دار را رصد کرد.
  B: قیمت نان سنتی در بندر لنگه در ۱۴۰۵/۰۲/۰۴ ثابت ماند.

## fresh_synthetic_challenge

Confusion matrices are `[[TN, FP], [FN, TP]]`; class 1 is positive. FPR=FP/(TN+FP), FNR=FN/(FN+TP). A missing denominator is undefined, not zero. Other undefined positive metrics use zero_division=0.

| Model | N | Precision | Recall | F1 | Accuracy | FPR | FNR | Matrix |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| word | 32 | 0.318182 | 0.583333 | 0.411765 | 0.375000 | 0.750000 | 0.416667 | `[[5, 15], [5, 7]]` |
| character | 32 | 0.428571 | 1.000000 | 0.600000 | 0.500000 | 0.800000 | 0.000000 | `[[4, 16], [0, 12]]` |
| semantic | 32 | 0.428571 | 1.000000 | 0.600000 | 0.500000 | 0.800000 | 0.000000 | `[[4, 16], [0, 12]]` |

### Per-scenario performance

| Model | Scenario | N | Precision | Recall | F1 | Accuracy | FPR | FNR |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| word | different_numbers | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | near_identical | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| word | negation_difference | 4 | 0.000000 | 0.000000 | 0.000000 | 0.250000 | 0.750000 | undefined |
| word | same_event_paraphrase | 4 | 1.000000 | 0.500000 | 0.666667 | 0.500000 | undefined | 0.500000 |
| word | same_location_different_dates | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | same_topic_different_events | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| word | short_long | 4 | 1.000000 | 0.250000 | 0.400000 | 0.250000 | undefined | 0.750000 |
| word | unrelated | 4 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 0.000000 | undefined |
| character | different_numbers | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | near_identical | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| character | negation_difference | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | same_event_paraphrase | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| character | same_location_different_dates | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | same_topic_different_events | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| character | short_long | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| character | unrelated | 4 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 0.000000 | undefined |
| semantic | different_numbers | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | near_identical | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| semantic | negation_difference | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | same_event_paraphrase | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| semantic | same_location_different_dates | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | same_topic_different_events | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | undefined |
| semantic | short_long | 4 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | undefined | 0.000000 |
| semantic | unrelated | 4 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 0.000000 | undefined |

### Paired error changes

Against word, semantic correct / baseline wrong: fresh-synthetic-001, fresh-synthetic-002, fresh-synthetic-029, fresh-synthetic-030, fresh-synthetic-032.

Against word, semantic wrong / baseline correct: fresh-synthetic-021.

Against character, semantic correct / baseline wrong: none.

Against character, semantic wrong / baseline correct: none.

### Semantic false_positives (16)

| Pair | Scenario | Raw cosine |
| --- | --- | ---: |
| fresh-synthetic-009 | same_topic_different_events | 0.817835 |
| fresh-synthetic-010 | same_topic_different_events | 0.961080 |
| fresh-synthetic-011 | same_topic_different_events | 0.892549 |
| fresh-synthetic-012 | same_topic_different_events | 0.973544 |
| fresh-synthetic-013 | same_location_different_dates | 0.904887 |
| fresh-synthetic-014 | same_location_different_dates | 0.940420 |
| fresh-synthetic-015 | same_location_different_dates | 0.968902 |
| fresh-synthetic-016 | same_location_different_dates | 0.976437 |
| fresh-synthetic-017 | different_numbers | 0.973268 |
| fresh-synthetic-018 | different_numbers | 0.962864 |
| fresh-synthetic-019 | different_numbers | 0.981515 |
| fresh-synthetic-020 | different_numbers | 0.935281 |
| fresh-synthetic-021 | negation_difference | 0.917155 |
| fresh-synthetic-022 | negation_difference | 0.886073 |
| fresh-synthetic-023 | negation_difference | 0.769552 |
| fresh-synthetic-024 | negation_difference | 0.702227 |

### Semantic false_negatives (0)

| Pair | Scenario | Raw cosine |
| --- | --- | ---: |

### Qualitative diagnostics

- `fresh-synthetic-017` (different_numbers): true=0, predicted=1, cosine=0.973268.
  A: بازده گندم مزرعه آزمایشی بدره در ۱۴۰۶/۰۳/۲۵ برابر ۳٫۲ تن در هکتار بود.
  B: بازده گندم مزرعه آزمایشی بدره در ۱۴۰۶/۰۳/۲۵ برابر ۴٫۲ تن در هکتار بود.

- `fresh-synthetic-005` (near_identical): true=1, predicted=1, cosine=0.959820.
  A: سامانه هشدار بهمن فریدون‌شهر در ۱۴۰۶/۰۹/۲۱ فعال شد.
  B: سامانه هشدار بهمن فریدون‌شهر، در ۱۴۰۶/۰۹/۲۱ فعال شد.

- `fresh-synthetic-021` (negation_difference): true=0, predicted=1, cosine=0.917155.
  A: پناهگاه نیستان میانه در ۱۴۰۶/۰۸/۱۳ مجوز بازدید شبانه دریافت کرد.
  B: پناهگاه نیستان میانه در ۱۴۰۶/۰۸/۱۳ مجوز بازدید شبانه دریافت نکرد.

- `fresh-synthetic-001` (same_event_paraphrase): true=1, predicted=1, cosine=0.909408.
  A: گروه مرجان در چابهار روز ۱۴۰۶/۰۱/۱۶ تعداد ۱۸ لاک‌پشت را به دریا بازگرداند.
  B: ۱۸ لاک‌پشت روز ۱۴۰۶/۰۱/۱۶ به دست گروه مرجان در ساحل چابهار رهاسازی شدند.

- `fresh-synthetic-013` (same_location_different_dates): true=0, predicted=1, cosine=0.904887.
  A: سرشماری زنبورستان‌های شهرضا در تاریخ ۱۴۰۶/۰۶/۰۴ آغاز شد.
  B: سرشماری زنبورستان‌های شهرضا در تاریخ ۱۴۰۶/۰۶/۱۴ آغاز شد.

- `fresh-synthetic-009` (same_topic_different_events): true=0, predicted=1, cosine=0.817835.
  A: ارتباط فیبر نوری بروجرد در ۱۴۰۶/۰۴/۲۲ به علت حفاری قطع شد.
  B: ارتباط فیبر نوری تربت‌حیدریه در ۱۴۰۶/۰۴/۲۲ به علت حفاری قطع شد.

- `fresh-synthetic-029` (short_long): true=1, predicted=1, cosine=0.844074.
  A: برنامه بازیافت زباله الکترونیکی قشم در ۱۴۰۶/۰۷/۰۳ آغاز شد.
  B: برنامه بازیافت زباله الکترونیکی قشم در ۱۴۰۶/۰۷/۰۳ آغاز شد. شهروندان می‌توانند دستگاه‌های ازکارافتاده را به محل تعیین‌شده تحویل دهند. مسئول برنامه گفت قطعات پس از جداسازی برای بازیابی مواد به مرکز تخصصی منتقل می‌شوند و هدف این طرح کاهش دورریز تجهیزات الکترونیکی است.

- `fresh-synthetic-025` (unrelated): true=0, predicted=0, cosine=0.092307.
  A: گروه روباتیک رها در شوشتر روز ۱۴۰۶/۰۱/۲۳ بازوی برداشت خرما ساخت.
  B: نقشه گویش‌های محلی در کتابخانه دیجیتال اهر روز ۱۴۰۶/۰۵/۱۷ منتشر شد.

## Computational requirements and runtime

CPU thread limit=2; batch size=16; embedding LRU capacity=4096. This run encoded 74 unique uncached documents. Model load=4.503s; encoding=0.798s (measured wall time, excluding dependency installation). Hardware memory use was not profiled.

The cached safetensors weight file is approximately 471 MB. Inference uses float32 model weights; cached vectors are explicitly normalized in float64. Longer texts can be truncated at the recorded token limit, potentially dropping a late number or negation. CPU works without CUDA; a requested unavailable CUDA device falls back to CPU and is recorded.

Runtime versions: sentence-transformers=5.7.0, transformers=4.57.6, torch=2.6.0, numpy=2.5.4, safetensors=0.8.0, tokenizers=0.22.2, huggingface-hub=0.36.2.

## Threats to validity and recommendations

The old test set informed prior analysis, so that comparison is exploratory. The fresh set is a small synthetic challenge with related pairs within each family, targeted categories, same-author labels and no annotation agreement study. Do not infer general superiority or unbiased real-news accuracy from these scores or selected examples.

Embedding proximity need not preserve factual equality: similar topics, changed dates/counts, negation or location names can remain close. Different n-gram and embedding preprocessing profiles are intentional method-specific choices. Pretraining contamination cannot be ruled out merely by local group separation. No model was fine-tuned.

Before cross-platform matching, collect authorized real examples, obtain independent event-level annotations, create a new untouched evaluation set, and examine truncation and factual-contrast errors. Telegram remains unverified; Bale integration and UI are outside scope.

## Reproduction and safe loading

Artifacts and any downloaded weights stay under ignored `artifacts/semantic/`. Existing Hugging Face snapshots are reused. Loading is pinned to the recorded revision, uses safetensors, sets trust_remote_code=False and defaults to cache-only. No credentials are required for the public model. Use --allow-download only when the pinned snapshot is absent. Ordinary tests mock all heavy model operations; real pretrained integration is explicitly opt-in.

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m pip install -e '.[dev,persian,semantic]'
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-semantic --freeze-only
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-semantic --fresh-dataset src/news_similarity/data/synthetic_fresh_v1.json
.\.venv\Scripts\python.exe -m news_similarity.cli compare-semantic --text-a 'خبر اول' --text-b 'خبر دوم'
.\.venv\Scripts\python.exe -m pytest -q
$env:RUN_SEMANTIC_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q -m semantic_integration
Remove-Item Env:RUN_SEMANTIC_INTEGRATION
```

Pin the recorded runtime versions for numeric reproduction. Thresholds and baseline hashes are immutable in an artifact directory; a new protocol needs a separate directory. The checked-in report and JSON outputs contain actual measured scores, not mocked test outputs.

## Implementation and verification receipt (2026-10-28)

Created:

- `src/news_similarity/semantic.py`
- `src/news_similarity/semantic_evaluation.py`
- `src/news_similarity/semantic_reporting.py`
- `src/news_similarity/data/synthetic_fresh_v1.json`
- `src/news_similarity/data/synthetic_fresh_v1.manifest.json`
- `scripts/build_fresh_semantic_dataset.py`
- `tests/test_semantic.py`
- `tests/test_semantic_evaluation.py`
- `tests/test_semantic_cli.py`
- `docs/FRESH_DATASET.md`
- `docs/PHASE_1_3B_REPORT.md`

Modified: `src/news_similarity/cli.py`, `pyproject.toml`, `README.md`.
Generated ignored outputs: `artifacts/semantic/freeze.json`,
`fresh_manifest.json`, `evaluation.json`, and `report.md`.

The ordinary suite completed with **278 passed, 1 skipped, 0 failed**.
The skipped actual-model test was then run separately with
`RUN_SEMANTIC_INTEGRATION=1`: **1 passed, 278 deselected**.
Ruff lint/format checks, `pip check`, editable installation, both semantic CLI
commands, fresh fixture reproduction and sensitive-artifact ignore checks passed.
Historical TF-IDF confusion matrices reproduce Phase 1.3A exactly.
Hashes confirm that all pre-existing source modules except the CLI, the original
72-pair dataset, TF-IDF artifacts and the SQLite file retain their initial bytes.

The pinned local safetensors snapshot was reused with offline flags. Actual
inference ran on CPU, with no CUDA available, no weight redownload and no fine-tuning.
The observed backbone configuration has 12 transformer layers, hidden size 384
and 12 attention heads, followed by the pinned mean-token pooling module.
This architecture information is model-specific metadata, not an application-wide
dimension assumption.
