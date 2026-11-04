# Phase 1.3A: TF-IDF baseline and scientific evaluation

All results below were computed from the explicitly synthetic v1 fixture. No real Telegram/Bale collection or real-world generalization is verified.

## Mathematics

For term count $c(t,d)>0$, sublinear TF is $1+\log c(t,d)$. Smoothed IDF is $\log((1+N)/(1+df(t)))+1$. The product is normalized to unit L2 length.

Cosine similarity is $s(x,y)=x^Ty/(\|x\|_2\|y\|_2)$. For L2-normalized vectors this is their dot product. Empty or entirely out-of-vocabulary vectors have score 0, including two empty inputs. Cosine scores are not calibrated probabilities.
The weighting and normalization follow scikit-learn's [TfidfTransformer documentation](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfTransformer.html).

## Methodology and leakage controls

Use the existing lexical profile with its builtin tokenizer, join the resulting tokens, and retain dates, numbers and negative forms. Word features use whitespace tokenization so scikit-learn does not split protected dates or discard one-character terms. Character features use `char_wb` on the same prepared text. Neither method removes stopwords.

Each normalized, nonempty development article occurs once in the fit corpus, regardless of how many pairs reuse it. For each predeclared candidate, grouped out-of-fold (OOF) scores are computed using a fresh vectorizer fitted only on that fold's training development groups. The fold's vocabulary and IDF never see its validation articles.

Thresholds maximize pooled development OOF F1, then precision, then accuracy, then higher threshold. Configuration ties use the declared grid order. Positive prediction requires `score > 0 and score >= threshold`. The all-negative candidate threshold is `nextafter(1, +inf)`.

The chosen configuration is fitted once on all development articles. All requested model configurations and thresholds are finalized before test news are transformed. No vocabulary/IDF or threshold fitting uses test text or labels. Test labels are used only for final metrics/error analysis. The two methods are reported side by side; test performance does not select a deployment winner.

OOF development metrics are selection statistics, not an unbiased estimate after trying configurations/thresholds. Development in-sample metrics are descriptive training diagnostics only. The final model's IDF differs from fold IDFs; the OOF-selected threshold is transferred unchanged to the final development fit.

Dataset: `synthetic-persian-news-v1`, schema 1; canonical SHA-256 `b547f8ed1378217c0aa7dc91bcaff8c8b5cd71b78add91635f9b6a32bec88dfd`.

Split: 48 development / 24 test pairs; GroupKFold=4, shuffle=True, seed=42.

Runtime: python=3.12.14, unicode=15.0.0, scikit-learn=1.7.2, numpy=2.5.4, scipy=1.18.1.

## Measured results

Confusion matrices use rows=true and columns=predicted, ordered `[0,1]`: `[[TN, FP], [FN, TP]]`. Metrics use class 1 as positive and zero_division=0. F1 for an all-negative scenario can therefore be zero even when every negative example is correctly classified.

| Model | Evaluation | Precision | Recall | F1 | Accuracy | Confusion matrix |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| word | development_oof | 0.405405 | 0.833333 | 0.545455 | 0.479167 | `[[8, 22], [3, 15]]` |
| word | development_in_sample | 0.354839 | 0.611111 | 0.448980 | 0.437500 | `[[10, 20], [7, 11]]` |
| word | test | 0.400000 | 0.888889 | 0.551724 | 0.458333 | `[[3, 12], [1, 8]]` |
| character | development_oof | 0.473684 | 1.000000 | 0.642857 | 0.583333 | `[[10, 20], [0, 18]]` |
| character | development_in_sample | 0.447368 | 0.944444 | 0.607143 | 0.541667 | `[[9, 21], [1, 17]]` |
| character | test | 0.428571 | 1.000000 | 0.600000 | 0.500000 | `[[3, 12], [0, 9]]` |

## Word model

Selected n-grams: (1, 2); min_df=1; sublinear_tf=True; smooth_idf=True; L2 norm; lowercase=False; float64. Threshold: **0.3515757351916628**. Final fit: 50 unique development articles, 769 features.

### Development-only search

| N-grams | Threshold | OOF precision | OOF recall | OOF F1 | OOF accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| (1, 1) | 0.174101801 | 0.390244 | 0.888889 | 0.542373 | 0.437500 |
| (1, 2) | 0.351575735 | 0.405405 | 0.833333 | 0.545455 | 0.479167 |

### Performance by scenario

| Scenario | Stage | N | Precision | Recall | F1 | Accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| different_numbers | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| near_identical | development_oof | 6 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| negation_difference | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.500000 |
| same_event_paraphrase | development_oof | 6 | 1.000000 | 0.500000 | 0.666667 | 0.500000 |
| same_location_different_dates | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_topic_different_events | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| short_long | development_oof | 6 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| unrelated | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.833333 |
| different_numbers | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| near_identical | test | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| negation_difference | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_event_paraphrase | test | 3 | 1.000000 | 0.666667 | 0.800000 | 0.666667 |
| same_location_different_dates | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_topic_different_events | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| short_long | test | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| unrelated | test | 3 | 0.000000 | 0.000000 | 0.000000 | 1.000000 |

### Score distributions

| Stage | True label | N | Min | Q25 | Median | Q75 | Max | Mean | Std |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| development_oof | 0 | 30 | 0.036817 | 0.347353 | 0.563583 | 1.000000 | 1.000000 | 0.617413 | 0.372442 |
| development_oof | 1 | 18 | 0.000000 | 0.359890 | 0.469232 | 0.536098 | 1.000000 | 0.489740 | 0.287451 |
| test | 0 | 15 | 0.000000 | 0.499177 | 1.000000 | 1.000000 | 1.000000 | 0.731705 | 0.360561 |
| test | 1 | 9 | 0.291586 | 0.406445 | 0.470845 | 0.631280 | 1.000000 | 0.536841 | 0.195196 |

### Held-out false positives (12)

| Pair | Scenario | Score |
| --- | --- | ---: |
| synthetic-025 | same_topic_different_events | 1.000000000 |
| synthetic-026 | same_topic_different_events | 1.000000000 |
| synthetic-027 | same_topic_different_events | 1.000000000 |
| synthetic-031 | same_location_different_dates | 1.000000000 |
| synthetic-032 | same_location_different_dates | 1.000000000 |
| synthetic-033 | same_location_different_dates | 1.000000000 |
| synthetic-043 | different_numbers | 1.000000000 |
| synthetic-044 | different_numbers | 1.000000000 |
| synthetic-045 | different_numbers | 1.000000000 |
| synthetic-055 | negation_difference | 0.655222606 |
| synthetic-056 | negation_difference | 0.524268265 |
| synthetic-057 | negation_difference | 0.474085276 |

### Held-out false negatives (1)

| Pair | Scenario | Score |
| --- | --- | ---: |
| synthetic-006 | same_event_paraphrase | 0.291586269 |

`synthetic-006` missed paraphrase:

A: تولید برق نیروگاه ۱۲ مگاواتی خورشیدی باران در یزد از ۱۴۰۵/۰۶/۱۵ آغاز شد.

B: یزد در ۱۴۰۵/۰۶/۱۵ نیروگاه خورشیدی باران را با توان ۱۲ مگاوات به شبکه متصل کرد.

### Factual-contrast diagnostics

- `synthetic-055` (negation_difference): label=0, prediction=1, score=0.655222606.
  A: شورای شهر اصفهان در ۱۴۰۵/۰۵/۱۰ طرح پارکینگ لاله را تصویب کرد.
  B: شورای شهر اصفهان در ۱۴۰۵/۰۵/۱۰ طرح پارکینگ لاله را تصویب نکرد.

- `synthetic-031` (same_location_different_dates): label=0, prediction=1, score=1.000000000.
  A: بارش ۸ میلی‌متری باران در ایلام برای روز ۱۴۰۵/۰۸/۰۳ ثبت شد.
  B: بارش ۸ میلی‌متری باران در ایلام برای روز ۱۴۰۵/۰۸/۱۳ ثبت شد.

- `synthetic-043` (different_numbers): label=0, prediction=1, score=1.000000000.
  A: بودجه پل سرو سنندج در ۱۴۰۵/۰۴/۰۱ برابر ۱۵۰ میلیارد تومان اعلام شد.
  B: بودجه پل سرو سنندج در ۱۴۰۵/۰۴/۰۱ برابر ۱۵ میلیارد تومان اعلام شد.

- `synthetic-025` (same_topic_different_events): label=0, prediction=1, score=1.000000000.
  A: آزمون ورودی رشته معماری دانشگاه اندیشه در کرمان روز ۱۴۰۵/۰۳/۰۱ برگزار شد.
  B: آزمون ورودی رشته موسیقی دانشگاه اندیشه در کرمان روز ۱۴۰۵/۰۳/۰۸ برگزار شد.


## Character model

Selected n-grams: (3, 5); min_df=1; sublinear_tf=True; smooth_idf=True; L2 norm; lowercase=False; float64. Threshold: **0.39967131106135645**. Final fit: 50 unique development articles, 2491 features.

### Development-only search

| N-grams | Threshold | OOF precision | OOF recall | OOF F1 | OOF accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| (3, 5) | 0.399671311 | 0.473684 | 1.000000 | 0.642857 | 0.583333 |
| (4, 6) | 0.418102534 | 0.473684 | 1.000000 | 0.642857 | 0.583333 |

### Performance by scenario

| Scenario | Stage | N | Precision | Recall | F1 | Accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| different_numbers | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| near_identical | development_oof | 6 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| negation_difference | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_event_paraphrase | development_oof | 6 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| same_location_different_dates | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_topic_different_events | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 0.666667 |
| short_long | development_oof | 6 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| unrelated | development_oof | 6 | 0.000000 | 0.000000 | 0.000000 | 1.000000 |
| different_numbers | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| near_identical | test | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| negation_difference | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_event_paraphrase | test | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| same_location_different_dates | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| same_topic_different_events | test | 3 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| short_long | test | 3 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| unrelated | test | 3 | 0.000000 | 0.000000 | 0.000000 | 1.000000 |

### Score distributions

| Stage | True label | N | Min | Q25 | Median | Q75 | Max | Mean | Std |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| development_oof | 0 | 30 | 0.033230 | 0.279966 | 0.848454 | 0.983101 | 1.000000 | 0.657429 | 0.369316 |
| development_oof | 1 | 18 | 0.399671 | 0.557361 | 0.698520 | 0.885081 | 1.000000 | 0.714893 | 0.189882 |
| test | 0 | 15 | 0.066833 | 0.802128 | 0.880248 | 0.938253 | 1.000000 | 0.741885 | 0.332502 |
| test | 1 | 9 | 0.483079 | 0.594551 | 0.611557 | 0.902583 | 1.000000 | 0.706231 | 0.174030 |

### Held-out false positives (12)

| Pair | Scenario | Score |
| --- | --- | ---: |
| synthetic-025 | same_topic_different_events | 0.921358838 |
| synthetic-026 | same_topic_different_events | 0.831262305 |
| synthetic-027 | same_topic_different_events | 0.846511823 |
| synthetic-031 | same_location_different_dates | 0.880247652 |
| synthetic-032 | same_location_different_dates | 0.929819486 |
| synthetic-033 | same_location_different_dates | 0.946686604 |
| synthetic-043 | different_numbers | 0.985265644 |
| synthetic-044 | different_numbers | 1.000000000 |
| synthetic-045 | different_numbers | 0.985265644 |
| synthetic-055 | negation_difference | 0.898555514 |
| synthetic-056 | negation_difference | 0.866874665 |
| synthetic-057 | negation_difference | 0.772993179 |

### Held-out false negatives (0)

None in this synthetic test partition.

### Factual-contrast diagnostics

- `synthetic-055` (negation_difference): label=0, prediction=1, score=0.898555514.
  A: شورای شهر اصفهان در ۱۴۰۵/۰۵/۱۰ طرح پارکینگ لاله را تصویب کرد.
  B: شورای شهر اصفهان در ۱۴۰۵/۰۵/۱۰ طرح پارکینگ لاله را تصویب نکرد.

- `synthetic-031` (same_location_different_dates): label=0, prediction=1, score=0.880247652.
  A: بارش ۸ میلی‌متری باران در ایلام برای روز ۱۴۰۵/۰۸/۰۳ ثبت شد.
  B: بارش ۸ میلی‌متری باران در ایلام برای روز ۱۴۰۵/۰۸/۱۳ ثبت شد.

- `synthetic-043` (different_numbers): label=0, prediction=1, score=0.985265644.
  A: بودجه پل سرو سنندج در ۱۴۰۵/۰۴/۰۱ برابر ۱۵۰ میلیارد تومان اعلام شد.
  B: بودجه پل سرو سنندج در ۱۴۰۵/۰۴/۰۱ برابر ۱۵ میلیارد تومان اعلام شد.

- `synthetic-025` (same_topic_different_events): label=0, prediction=1, score=0.921358838.
  A: آزمون ورودی رشته معماری دانشگاه اندیشه در کرمان روز ۱۴۰۵/۰۳/۰۱ برگزار شد.
  B: آزمون ورودی رشته موسیقی دانشگاه اندیشه در کرمان روز ۱۴۰۵/۰۳/۰۸ برگزار شد.

## Interpretation and limitations

Lexical overlap can stay high when dates, counts or negation change. Word and character n-grams do not reason about factual compatibility. Character features can retain partial spelling matches but also share substrings across contradictory claims; higher recall alone does not establish better robustness or real-news performance. Held-out group vocabulary can be OOV; even identical unseen inputs can score zero. Conversely, distinguishing dates/counts/words absent from the development vocabulary disappear from word vectors: contradictory claims can share a vector and score 1. This is not factual certainty.

The test partition has 9 positives and 15 negatives. Always-negative prediction has accuracy 0.625000 and positive F1 0. Always-positive prediction has precision 0.375000, recall 1, F1 0.545455 and accuracy 0.375000. These are descriptive reference policies, not tuned models.

Only 24 synthetic test pairs from 8 event groups are available. Within-group pairs are correlated and partly templated. There is no independent annotation agreement, domain coverage or uncertainty interval justifying strong conclusions. The development selection space is small and predeclared. Test results must not be used to revise this search while continuing to call the same test set untouched.

## Persistence and reproducibility

`artifacts/tfidf/` contains locally generated JSON models and measured evaluation outputs, excluded from Git. Each model records vocabulary, IDF, configuration, threshold, development fit IDs/count/corpus hash, dataset checksum, runtime versions and preprocessing fingerprint. Loading reconstructs state without fitting, pickle or joblib. Only use locally generated artifacts; schema validation is not an authenticity guarantee. A preprocessing or numerical-library version mismatch is rejected; regenerate with the documented environment.

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m pip install 'scikit-learn==1.7.2' 'numpy==2.5.4' 'scipy==1.18.1'
.\.venv\Scripts\python.exe -m pip install -e '.[dev,persian]'
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-tfidf --model both --output-dir artifacts/tfidf --report-path docs/PHASE_1_3A_REPORT.md
.\.venv\Scripts\python.exe -m news_similarity.cli compare --text-a 'خبر اول' --text-b 'خبر دوم'
.\.venv\Scripts\python.exe -m news_similarity.cli compare --model character --text-a 'خبر اول' --text-b 'خبر دوم'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

Run with the recorded numerical versions for exact reproduction. `evaluate-tfidf --model word` and `--model character` also work separately; both use the same fixed split, folds and selection policy. `compare` loads the requested fitted artifact and never fits on its inputs. Complete per-pair scores, errors, distributions, fold audits and all development trials are in `evaluation.json`.

## Phase 1.3B readiness

The reusable fitted-model API and development/test evaluation contracts are ready for a future semantic-baseline comparison. No semantic embeddings, transformers, Bale integration or UI were implemented. Live Telegram remains unverified. Future work needs more independently reviewed event groups and an additional untouched test set if existing test errors inform feature or model design.
