# Phase 1.4B: Hybrid event-aware news matching

Implemented on 2026-10-28. Policy version: `hybrid-event-v1`.
This phase implements an interpretable, abstaining matching service and
development-group parameter selection. It reuses the existing TF-IDF,
MiniLM, preprocessing and Phase 1.4A evidence implementations.

**Evaluation status: diagnostic only.** Both existing synthetic sets were
previously inspected. No independently verified new real-news labels are
available, and no new synthetic set is presented as an independent substitute.
No real-world accuracy improvement or verified platform collection is claimed.

**Main measured limitation:** the full engine abstained on all 48 outer-fold
development predictions and all 56 examined test pairs. Test coverage, strict
accuracy and F1 were zero. Its zero false-positive rate is entirely an abstention
outcome, not demonstrated improvement in event discrimination. The frozen rules
were not loosened after inspecting these results. Automatic cross-platform
matching is **not ready**.

## Changed files and architecture

| File | Purpose |
| --- | --- |
| `src/news_similarity/hybrid.py` | Configuration, fusion, event decisions, explanations, pair/batch service and ranking |
| `src/news_similarity/hybrid_evaluation.py` | Nested development groups, selection, immutable freezes, bindings and diagnostic comparisons |
| `src/news_similarity/hybrid_metrics.py` | Three-category confusion matrices, strict metrics and abstention accounting |
| `src/news_similarity/hybrid_reporting.py` | Render measured baseline, scenario and paired-error tables |
| `src/news_similarity/cli.py` | `compare-hybrid`, `evaluate-hybrid` and cache/device options |
| `tests/test_hybrid.py` | Fusion, evidence policy, missing inputs, ranking, batching and metrics |
| `tests/test_hybrid_evaluation.py` | Fitting isolation, selection, freezes, provenance and diagnostic integrity |
| `tests/test_hybrid_cli.py` | CLI behavior, loading failures and argument validation |
| `tests/test_event_features_cli.py` | Extend the existing exact command-set assertion with the two new commands |
| `README.md` | Hybrid usage and current limitations |
| `docs/PHASE_1_4B_REPORT.md` | This report |

No collection/database modules, schema, dependencies, preprocessing profiles,
feature-extraction rules or previous model artifacts were modified.
No model fine-tuning, additional encoder, GUI or platform integration was added.

## Fusion and event decisions

For raw word, character and semantic cosine values `W`, `C`, `S`:

```text
L = word_weight * W + (1 - word_weight) * C
B = semantic_weight * max(0, S) + (1 - semantic_weight) * L
R = max(0, B - applied_penalty)
```

Raw semantic cosine, including negative values, is preserved in the output.
Clipping negative semantic support to zero is an explicit ranking convention.
`L`, `B` and `R` are ranking scores, not calibrated probabilities or percentages.

A single bounded penalty applies when Phase 1.4A reports a
`confirmed_explicit_conflict` in a quantity or bounded predicate, with evidence
on both sides and no qualifier cues. The fixed default penalty is 0.35; it is
configurable but was not tuned on diagnostic labels. Repeated mentions do not
multiply it. Possible conflicts and missing information apply no score penalty.
Raw normalized values, original evidence spans, clauses, rules and qualifier
flags remain available in the final result.

The full engine makes decisions in this order:

1. Empty text after the existing semantic preprocessing produces `uncertain`
   and null scores. Component scorers are not called for those pairs.
2. A confirmed explicit claim contradiction produces `uncertain`, with a ranking
   penalty. Opposite claims may refer to the same event or a correction;
   contradiction alone never forces a different-event decision.
3. `likely_different_event` requires low lexical **and** semantic support below
   the lower boundary, at least two discrepant contextual anchor types, no
   matching unqualified anchor, and no qualifier cues on the counted anchors.
   Anchor types are entity, location, date and clock. Dates need years; clocks
   need explicit timezones. This remains a tentative rule, not event verification.
4. Other possible conflicts or observed but unaligned/missing evidence produce
   `uncertain`. Missing evidence is not a factual contradiction.
5. `likely_same_event` requires a score at or above the upper boundary and at
   least two matching unqualified contextual anchor types. Counts and generic
   affirmative predicates alone are not event-identifying anchors.
6. Remaining pairs produce `uncertain`.

Phase 1.4A remains unchanged: numeric date calendars may be unspecified, and
general negation scope is unknown. Shared numeric date components are weak
contextual evidence, without calendar inference. Dates, numbers or places alone
cannot establish different events. Same-event count updates can therefore
remain uncertain even when the broad event identity may actually be shared.

The feature-free ablation uses the identical weights and boundaries with
penalties and factual gates disabled: high score means likely same, low score
means likely different, and the interval between them abstains. This deliberately
isolates the effect of event evidence; it is not independently retuned.

## Development-only selection and frozen provenance

Only the original 48 development pairs in 16 event groups select fusion weights
and the upper threshold. The fixed, existing lexical configurations are reused;
each validation vocabulary and IDF is fitted on that fold's training articles.
The pretrained semantic encoder has no fitted corpus parameters.

The predeclared fusion grid tries semantic weights `[0.5, 0.25, 0.75]` crossed
with word shares `[0.5, 1.0, 0.0]`. For each combination, the existing threshold
selector maximizes pooled grouped out-of-fold binary **ranking-proxy** F1,
then precision, accuracy and higher threshold. Grid order resolves equal
configuration ranks. This selects ranking support, not the full abstaining
decision policy. The lower threshold is half the selected upper threshold,
a fixed engineering convention without a calibration claim.

Four outer development folds assess the complete abstaining policy. Within each
outer training partition, inner grouped out-of-fold scores select fusion
parameters without seeing the outer validation labels or articles. The final
configuration uses grouped out-of-fold scores from all development data.
Outer and inner group/pair audits are saved with the freeze. Exact prepared
article overlap across development groups is rejected.

These are conditional development diagnostics: the lexical configurations and
synthetic corpus have a history of prior examination. The ranking-proxy objective
may select weights that do not optimize the full engine's strict F1 or coverage.
Factual decision rules, anchor count requirements and the contradiction penalty
were engineering choices tested with fictional rule examples, not optimized
using historical/fresh test labels.

The immutable `hybrid.freeze.json` is created before either examined test set is
scored. It binds development IDs/groups/digest, configuration, fold audits,
source/feature/preprocessing fingerprints, lexical artifact SHA-256 values and
the existing semantic freeze's SHA-256/model revision/runtime identity.
Comparisons validate these bindings and never refit. A changed protocol or
artifact requires a separate output directory. Model or loading failures return
an error, with no fabricated fallback scores.

## Evaluation definitions and integrity

All five systems use the same diagnostic pairs and existing binary labels:
word TF-IDF, character TF-IDF, MiniLM, hybrid without events and full hybrid.
Legacy baseline thresholds remain unchanged. Existing binary labels represent
strict event-and-fact agreement; they are an imperfect proxy for evolving event
identity. In particular, a correction or updated count may share event identity
while failing strict fact agreement. No unseen verified update benchmark exists.

Confusion matrices have true rows `[different, same]` and predicted columns
`[likely_different_event, likely_same_event, uncertain]`. Let the rows be
`[TN, FP, U_negative]` and `[FN, TP, U_positive]`:

- Precision is `TP / (TP + FP)`.
- Recall is `TP / (TP + FN + U_positive)`.
- F1 uses that precision and recall.
- Primary accuracy is `(TP + TN) / all_pairs`; **all abstentions are errors**.
- FPR is `FP / all_negative_pairs`, including abstained negatives in its
  denominator. It can fall simply because the model abstains.
- Primary FNR is `(FN + U_positive) / all_positive_pairs`. Explicit decided
  false-negative rate is also recorded separately.
- Coverage is `decided_pairs / all_pairs`; abstention rate/counts are reported
  overall, by true label and by scenario.
- Decided-only binary metrics and confusion matrices are reported separately.
  They are null when nothing was decided, never silently presented as perfect.

The historical test has 24 pairs; the previously examined challenge has 32.
Their existing group/event-ID and number-masked near-duplicate screening is
reused, but it cannot restore independence once the sets have been inspected.
No diagnostic label enters parameter selection or contradiction-rule tuning.
Metamorphic tests change held-out labels and confirm that the selection/freeze
remains unchanged. Previous datasets, manifests and benchmark results are read
only and checked by file digests.

## Frozen configuration and measured diagnostics

**Diagnostic only. Both synthetic sets were previously examined.**
Unavailable: no independently verified new real-news labels. Both existing sets were previously examined.

Existing binary labels mean strict event-and-fact agreement, not independently verified evolving-event identity; updates can disagree with this proxy.

Freeze SHA-256: `9754b3034780d988e634294aab697cf7f88aebfd047c0e1f082bcaac807c1248`.

Frozen configuration: `{'semantic_weight': 0.25, 'word_weight': 0.0, 'confirmed_penalty': 0.35, 'same_threshold': 0.49049888601643266, 'different_threshold': 0.24524944300821633}`.

Primary accuracy counts every abstention as an error. Recall/FNR include
positive abstentions as misses. FPR uses all negatives, so inspect coverage
and decided-only metrics before interpreting a lower FPR.

Fusion parameters use grouped development selection of a binary ranking
proxy. Factual gating rules and the 0.35 confirmed-claim penalty are fixed
engineering choices, not tuned on diagnostic labels.

### Development group validation

Conditional diagnostic validation; previous lexical configurations were fixed.

- hybrid: F1 0.0000, strict accuracy 0.0000, coverage 0.0000.
- hybrid_without_events: F1 0.3636, strict accuracy 0.2917, coverage 0.6667.

### historical_diagnostic

| Model | Precision | Recall | F1 | Strict accuracy | FPR | FNR incl. abstentions | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| word | 0.4000 | 0.8889 | 0.5517 | 0.4583 | 0.8000 | 0.1111 | 1.0000 |
| character | 0.4286 | 1.0000 | 0.6000 | 0.5000 | 0.8000 | 0.0000 | 1.0000 |
| semantic | 0.4500 | 1.0000 | 0.6207 | 0.5417 | 0.7333 | 0.0000 | 1.0000 |
| hybrid_without_events | 0.4286 | 1.0000 | 0.6000 | 0.5000 | 0.8000 | 0.0000 | 1.0000 |
| hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.0000 |

Confusion rows: true [different, same]; columns: predicted [different, same, uncertain].

- word: `[[3, 12, 0], [1, 8, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.5517.
- character: `[[3, 12, 0], [0, 9, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.6000.
- semantic: `[[4, 11, 0], [0, 9, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.6207.
- hybrid_without_events: `[[3, 12, 0], [0, 9, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.6000.
- hybrid: `[[0, 0, 15], [0, 0, 9]]`; abstentions `{'negative': 15, 'positive': 9, 'total': 24}`; decided-only F1 n/a.

#### Scenario diagnostics

| Scenario | Model | F1 | Strict accuracy | FPR | Coverage |
| --- | --- | --- | --- | --- | --- |
| different_numbers | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | word | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | word | 0.8000 | 0.6667 | n/a | 1.0000 |
| same_location_different_dates | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | word | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | word | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | character | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | character | 1.0000 | 1.0000 | n/a | 1.0000 |
| same_location_different_dates | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | character | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | character | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | semantic | 0.0000 | 0.3333 | 0.6667 | 1.0000 |
| near_identical | semantic | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | semantic | 1.0000 | 1.0000 | n/a | 1.0000 |
| same_location_different_dates | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | semantic | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | semantic | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | hybrid_without_events | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | hybrid_without_events | 1.0000 | 1.0000 | n/a | 1.0000 |
| same_location_different_dates | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | hybrid_without_events | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | hybrid_without_events | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| near_identical | hybrid | 0.0000 | 0.0000 | n/a | 0.0000 |
| negation_difference | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| same_event_paraphrase | hybrid | 0.0000 | 0.0000 | n/a | 0.0000 |
| same_location_different_dates | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| same_topic_different_events | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| short_long | hybrid | 0.0000 | 0.0000 | n/a | 0.0000 |
| unrelated | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Full per-scenario precision, recall, FNR, confusion matrices and conditional metrics are in `hybrid.evaluation.json`.

#### False-positive transitions

- Against word: FPR delta -0.8000; 12 false positives became uncertain; 0 became different-event decisions.
- Against character: FPR delta -0.8000; 12 false positives became uncertain; 0 became different-event decisions.
- Against semantic: FPR delta -0.7333; 11 false positives became uncertain; 0 became different-event decisions.
- Against hybrid_without_events: FPR delta -0.8000; 12 false positives became uncertain; 0 became different-event decisions.

#### Evidence changed score or decision

| Pair | Category | Label | Score-only decision | Full decision | Penalty |
| --- | --- | --- | --- | --- | --- |
| synthetic-004 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-005 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-006 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-013 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-014 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-015 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-025 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-026 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-027 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-031 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-032 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-033 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-043 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-044 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-045 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-046 | unrelated | 0 | likely_different_event | uncertain | 0.0 |
| synthetic-047 | unrelated | 0 | likely_different_event | uncertain | 0.0 |
| synthetic-048 | unrelated | 0 | likely_different_event | uncertain | 0.0 |
| synthetic-055 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-056 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-057 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| synthetic-064 | short_long | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-065 | short_long | 1 | likely_same_event | uncertain | 0.0 |
| synthetic-066 | short_long | 1 | likely_same_event | uncertain | 0.0 |

Error-analysis evidence tags (not separate independently labeled benchmarks):

- dates_times: synthetic-004, synthetic-005, synthetic-006, synthetic-013, synthetic-014, synthetic-015, synthetic-025, synthetic-026, synthetic-027, synthetic-031, synthetic-032, synthetic-033, synthetic-043, synthetic-044, synthetic-045, synthetic-046, synthetic-047, synthetic-048, synthetic-055, synthetic-056, synthetic-057, synthetic-064, synthetic-065, synthetic-066.
- numbers: synthetic-004, synthetic-005, synthetic-006, synthetic-013, synthetic-014, synthetic-015, synthetic-031, synthetic-032, synthetic-033, synthetic-043, synthetic-044, synthetic-045.
- negation: synthetic-025, synthetic-026, synthetic-027, synthetic-055, synthetic-056, synthetic-057.
- locations: synthetic-004, synthetic-005, synthetic-006, synthetic-025, synthetic-026, synthetic-027, synthetic-031, synthetic-032, synthetic-033, synthetic-046, synthetic-047, synthetic-055, synthetic-056, synthetic-057.
- update_cues: none observed.
- same_topic_different_events: synthetic-025, synthetic-026, synthetic-027.
- paraphrases: synthetic-004, synthetic-005, synthetic-006.

### examined_challenge_diagnostic

| Model | Precision | Recall | F1 | Strict accuracy | FPR | FNR incl. abstentions | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| word | 0.3182 | 0.5833 | 0.4118 | 0.3750 | 0.7500 | 0.4167 | 1.0000 |
| character | 0.4286 | 1.0000 | 0.6000 | 0.5000 | 0.8000 | 0.0000 | 1.0000 |
| semantic | 0.4286 | 1.0000 | 0.6000 | 0.5000 | 0.8000 | 0.0000 | 1.0000 |
| hybrid_without_events | 0.4286 | 1.0000 | 0.6000 | 0.4688 | 0.8000 | 0.0000 | 0.9688 |
| hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.0000 |

Confusion rows: true [different, same]; columns: predicted [different, same, uncertain].

- word: `[[5, 15, 0], [5, 7, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.4118.
- character: `[[4, 16, 0], [0, 12, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.6000.
- semantic: `[[4, 16, 0], [0, 12, 0]]`; abstentions `{'negative': 0, 'positive': 0, 'total': 0}`; decided-only F1 0.6000.
- hybrid_without_events: `[[3, 16, 1], [0, 12, 0]]`; abstentions `{'negative': 1, 'positive': 0, 'total': 1}`; decided-only F1 0.6000.
- hybrid: `[[0, 0, 20], [0, 0, 12]]`; abstentions `{'negative': 20, 'positive': 12, 'total': 32}`; decided-only F1 n/a.

#### Scenario diagnostics

| Scenario | Model | F1 | Strict accuracy | FPR | Coverage |
| --- | --- | --- | --- | --- | --- |
| different_numbers | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | word | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | word | 0.0000 | 0.2500 | 0.7500 | 1.0000 |
| same_event_paraphrase | word | 0.6667 | 0.5000 | n/a | 1.0000 |
| same_location_different_dates | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | word | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | word | 0.4000 | 0.2500 | n/a | 1.0000 |
| unrelated | word | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | character | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | character | 1.0000 | 1.0000 | n/a | 1.0000 |
| same_location_different_dates | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | character | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | character | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | character | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | semantic | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | semantic | 1.0000 | 1.0000 | n/a | 1.0000 |
| same_location_different_dates | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | semantic | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | semantic | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | semantic | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| different_numbers | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| near_identical | hybrid_without_events | 1.0000 | 1.0000 | n/a | 1.0000 |
| negation_difference | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_event_paraphrase | hybrid_without_events | 1.0000 | 1.0000 | n/a | 1.0000 |
| same_location_different_dates | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| same_topic_different_events | hybrid_without_events | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| short_long | hybrid_without_events | 1.0000 | 1.0000 | n/a | 1.0000 |
| unrelated | hybrid_without_events | 0.0000 | 0.7500 | 0.0000 | 0.7500 |
| different_numbers | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| near_identical | hybrid | 0.0000 | 0.0000 | n/a | 0.0000 |
| negation_difference | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| same_event_paraphrase | hybrid | 0.0000 | 0.0000 | n/a | 0.0000 |
| same_location_different_dates | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| same_topic_different_events | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| short_long | hybrid | 0.0000 | 0.0000 | n/a | 0.0000 |
| unrelated | hybrid | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Full per-scenario precision, recall, FNR, confusion matrices and conditional metrics are in `hybrid.evaluation.json`.

#### False-positive transitions

- Against word: FPR delta -0.7500; 15 false positives became uncertain; 0 became different-event decisions.
- Against character: FPR delta -0.8000; 16 false positives became uncertain; 0 became different-event decisions.
- Against semantic: FPR delta -0.8000; 16 false positives became uncertain; 0 became different-event decisions.
- Against hybrid_without_events: FPR delta -0.8000; 16 false positives became uncertain; 0 became different-event decisions.

#### Evidence changed score or decision

| Pair | Category | Label | Score-only decision | Full decision | Penalty |
| --- | --- | --- | --- | --- | --- |
| fresh-synthetic-001 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-002 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-003 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-004 | same_event_paraphrase | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-005 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-006 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-007 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-008 | near_identical | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-009 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-010 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-011 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-012 | same_topic_different_events | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-013 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-014 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-015 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-016 | same_location_different_dates | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-017 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-018 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-019 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-020 | different_numbers | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-021 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-022 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-023 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-024 | negation_difference | 0 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-025 | unrelated | 0 | likely_different_event | uncertain | 0.0 |
| fresh-synthetic-027 | unrelated | 0 | likely_different_event | uncertain | 0.0 |
| fresh-synthetic-028 | unrelated | 0 | likely_different_event | uncertain | 0.0 |
| fresh-synthetic-029 | short_long | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-030 | short_long | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-031 | short_long | 1 | likely_same_event | uncertain | 0.0 |
| fresh-synthetic-032 | short_long | 1 | likely_same_event | uncertain | 0.0 |

Error-analysis evidence tags (not separate independently labeled benchmarks):

- dates_times: fresh-synthetic-001, fresh-synthetic-002, fresh-synthetic-003, fresh-synthetic-004, fresh-synthetic-005, fresh-synthetic-006, fresh-synthetic-007, fresh-synthetic-008, fresh-synthetic-009, fresh-synthetic-010, fresh-synthetic-011, fresh-synthetic-012, fresh-synthetic-013, fresh-synthetic-014, fresh-synthetic-015, fresh-synthetic-016, fresh-synthetic-017, fresh-synthetic-018, fresh-synthetic-019, fresh-synthetic-020, fresh-synthetic-021, fresh-synthetic-022, fresh-synthetic-023, fresh-synthetic-024, fresh-synthetic-025, fresh-synthetic-026, fresh-synthetic-027, fresh-synthetic-028, fresh-synthetic-029, fresh-synthetic-030, fresh-synthetic-031, fresh-synthetic-032.
- numbers: fresh-synthetic-001, fresh-synthetic-002, fresh-synthetic-017, fresh-synthetic-018, fresh-synthetic-019, fresh-synthetic-020.
- negation: fresh-synthetic-021, fresh-synthetic-022, fresh-synthetic-023, fresh-synthetic-024.
- locations: none observed.
- update_cues: fresh-synthetic-004, fresh-synthetic-028.
- same_topic_different_events: fresh-synthetic-009, fresh-synthetic-010, fresh-synthetic-011, fresh-synthetic-012.
- paraphrases: fresh-synthetic-001, fresh-synthetic-002, fresh-synthetic-003, fresh-synthetic-004.

Lower false-positive rates may reflect abstention rather than better binary discrimination.
No independent real-world accuracy claim is supported. Same-event update labels require a separate, independently reviewed identity policy and untouched event groups.

## Case inspection and error analysis

All following cases are fictional dataset examples. Scores are measured ranking
support, not confidence estimates. The feature-free hybrid and full model use
the same frozen fusion configuration.

| Case | Observation | Effect of event evidence |
| --- | --- | --- |
| Dates: `synthetic-031` | Rainfall on `۱۴۰۵/۰۸/۰۳` versus `۱۴۰۵/۰۸/۱۳`, score 0.9074 | Score-only same became uncertain; numeric date/calendar and temporal roles remain unresolved |
| Times: `synthetic-014` | Near-identical flight reports share `۱۰:۳۰`, score 0.9997 | Same became uncertain; timezone is unspecified and other usable anchor types are insufficient |
| Numbers: `synthetic-043` | Budget is 150 versus 15 billion tomans, score 0.9772 | Same became uncertain; possible conflict is warned without a numeric score penalty |
| Negation: `synthetic-055` | Approval `تصویب کرد` versus `تصویب نکرد`, score 0.8677 | Same became uncertain; bounded opposite polarity is not a fully anchored event contradiction |
| Location: `fresh-synthetic-009` | Fiber outages in Borujerd versus Torbat Heydariyeh, score 0.9277 | Same became uncertain; those locations are outside the fixed gazetteer, so insufficient anchors drive abstention rather than an invented location conflict |
| Same topic/different event: `synthetic-025` | Architecture versus music entrance exams on different dates, score 0.8940 | Same became uncertain; no supported different-event verdict |
| Paraphrase: `synthetic-004` | Solar-plant reports agree, score 0.6550 | Same became uncertain because `۱۲ مگاوات` is typed as watts but `۱۲ مگاواتی` remains an untyped number; unmatched evidence blocks the positive decision |
| Short/long: `synthetic-064` | Museum reopening and expanded context, score 0.6173 | Same became uncertain due to insufficient supported contextual anchors |
| Unrelated: `synthetic-046` | Astronomy versus bread prices, score 0.0939 | Score-only different became uncertain; the full policy requires multiple supported anchor discrepancies even at very low cosine |

The historical set contains six extracted clock mentions across three flight
pairs. The examined challenge has no extracted clocks or recognized locations.
This is a serious feature-coverage limitation, not evidence that those reports
lack times or places in reality. No confirmed-claim penalty was applied to any
of the 56 examined test pairs; the practical usefulness of that penalty has no
statistical evidence here. Its mechanics are exercised only by rule tests.

The challenge has two texts with broad update cues (`fresh-synthetic-004` and
`fresh-synthetic-028`), but neither is a verified longitudinal count-update
benchmark. `تازه` describes a new sensor or play. Treating these cues as broad
qualifiers can suppress otherwise useful anchors. The test suite separately
checks fictional same-event count updates (8 then 10 participants) and requires
uncertainty with no strong penalty; no update accuracy is claimed.

Every historical diagnostic outcome changed to uncertain relative to the
feature-free hybrid (24/24). On the challenge, 31/32 changed and one was already
uncertain. All false positives that disappeared became abstentions; none became
a supported different-event decision. Conditional decided-only metrics for the
full model are unavailable because it made no decisions.

The main causes are narrow lexical/entity coverage, unresolved measurement roles,
the two-anchor gate, broad qualifier filters and the rule that unaligned observed
facts block a positive decision. The ranking-proxy selection objective does not
reward usable decision coverage. These are research limitations to address with
new development evidence and a clearly reviewed identity/update policy, not by
tuning against the already inspected test labels.

## Verification

Actual final checks on the existing Windows Python 3.12.14 virtual environment:

| Check | Result |
| --- | --- |
| Full `python -m pytest -q`, cached semantic integration enabled | **438 passed in 32.02s**, no skips or failures |
| New Phase 1.4B tests | **46 passed**, with expensive encoder operations mocked |
| Ruff lint | All checks passed |
| Ruff format check | 62 files already formatted |
| Dependency validation | No broken requirements found |
| Actual `evaluate-hybrid --freeze-only` CLI | Frozen configuration and grouped development provenance written successfully |
| Actual `evaluate-hybrid` CLI | Five-model diagnostics written for 24 historical and 32 examined challenge pairs |
| Actual `compare-hybrid` CLI with identical fully anchored fictional news | `likely_same_event`, score approximately 1, complete JSON evidence and no probability claim |
| Protected-file digests | Of 57 pre-existing protected files, only CLI source and its exact command-set test changed; other 55 retained their bytes |

The existing Phase 1.4A test assertion was extended with both new command names;
no previous test or command was removed. Prior datasets, manifests, model results,
phase reports, feature rules and `data/news.db` remain unchanged. The hybrid
freeze SHA-256 still matches the digest recorded before diagnostic evaluation.
No verification failures remain unresolved. Windows asynchronous tests were run
with the normal local socket-pair capability outside the restricted sandbox.

Generated local files are `artifacts/hybrid/hybrid.freeze.json`,
`artifacts/hybrid/hybrid.evaluation.json` and
`artifacts/hybrid/hybrid.report.md`. They are new files in the existing ignored
artifact tree; the measured results are also included in this implementation report.

## Public API and CLI

```python
from news_similarity.hybrid import HybridConfig, HybridMatcher

# Existing fitted lexical scorers and a SemanticSimilarity instance:
matcher = HybridMatcher(word_model, character_model, semantic_model, HybridConfig())
pair_result = matcher.compare(text_a, text_b).to_dict()
batch = matcher.compare_batch([(text_a, text_b), (text_c, text_d)])
ranked = matcher.rank(query, candidates, top_k=5)
```

Direct construction records `manual_unvalidated` parameters. Use
`load_hybrid_matcher()` from `news_similarity.hybrid_evaluation` to load and
validate the development-selected freeze and model bindings.

JSON results contain word/character/lexical/semantic similarities, unpenalized
and combined ranking scores, the applied penalty, complete event evidence,
conflict warnings, decision, explanation, configuration and model metadata.
Original evidence uses the existing Python code-point offset convention.
Batch calls reuse each existing scorer once for all valid input pairs. Ranking
keeps input indices, sorts descending score with stable input-order ties, and
places null-score candidates last. Empty batches do not load any models.

PowerShell commands from the existing checkout:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-hybrid --freeze-only
.\.venv\Scripts\python.exe -m news_similarity.cli evaluate-hybrid
.\.venv\Scripts\python.exe -m news_similarity.cli compare-hybrid --text-a 'در تهران ۱۲ نفر آمدند.' --text-b 'در تهران ۱۴ نفر آمدند.'

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

All text examples here are fictional, not platform reporting. On this machine,
the explicit cache option is
`--cache-folder 'C:\Users\p Lenovo\.cache\huggingface\hub'` if required.
Default inference is cache-only; no model is downloaded by these commands.
The previous semantic extra, pinned cache, lexical artifacts and semantic freeze
are prerequisites. This phase adds no dependencies.

To include the existing opt-in cached pretrained integration test:

```powershell
$env:RUN_SEMANTIC_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:RUN_SEMANTIC_INTEGRATION
```

## Limitations and readiness

This is an inspectable prototype with potentially substantial abstention.
The small synthetic data, limited location/name rules, missing semantic roles,
unknown numeric calendars and negation scope restrict event decisions. Low
scores and multiple anchor differences still do not prove separate events;
matching recurring names/places/dates still does not verify one shared event.
The 0.35 penalty and half-threshold lower boundary lack independent calibration.
The short MiniLM context window can omit facts in long news; evidence extraction
still examines the original full text, so truncation can produce disagreements.

The service and evidence contracts are ready for further research integration.
Reliable real cross-platform matching still requires authorized real texts,
independently reviewed event/update labels, a frozen identity policy and a new
untouched evaluation set with event-group and near-duplicate separation.
Telegram collection remains unverified; Bale integration remains outside scope.
