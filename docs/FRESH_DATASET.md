# Fresh synthetic semantic challenge v1

Every statement is fictional. This set contains no collected or verified news.
Its labels were authored in this task, without independent human review. It is
an event-disjoint synthetic challenge, not an unbiased real-news benchmark.

The original 72-pair dataset is unchanged. The new UTF-8 fixture is
`src/news_similarity/data/synthetic_fresh_v1.json`, with a separate checked-in
`synthetic_fresh_v1.manifest.json`. The existing schema and strict event-claim
label definition are reused. All new pairs use `split: test`.

| Property | Value |
| --- | --- |
| Pairs | 32 |
| New event families | 16 |
| Positive / negative labels | 12 / 20 |
| Pairs per original scenario | 4 |
| Canonical SHA-256 | `27876f613af2b197ee7e8c2c24b6085d0580310ad83c6cf3e9ca3c91b49fbfaa` |

Categories cover paraphrases, near-identical headlines, different events or
locations, changed dates/counts, negation, unrelated stories and short/long
versions. Location contrasts use the existing `same_topic_different_events`
category, preserving the original schema. New topics include turtle releases,
underwater acoustic sensors, avalanche warnings, accessibility software,
fiber outages, beehive surveys, grain yield and electronic-waste recycling.

## Freeze and screening protocol

1. Reuse the untouched Phase 1.3A TF-IDF model files and their thresholds.
2. Freeze the prescribed pretrained revision and semantic development threshold
   **0.6604582132926925** before authoring this fixture.
3. Author new event families and strict labels without calling any encoder or
   choosing examples based on scores.
4. Validate schema and pair/group/event ID separation from every original split.
5. Screen digit-masked lexical-normalized character sequences against every
   original article. SequenceMatcher ratios >=0.85 are rejected. Maximum
   observed overlap was **0.6236559139784946**.
6. Save the fixture, source manifest and freeze anchor before evaluation.
7. Evaluate all three frozen methods on the identical 32 pairs without tuning.

The source manifest records the original freeze SHA-256, revision, threshold,
baseline artifact hashes and dataset checksum. Generated
`artifacts/semantic/fresh_manifest.json` additionally records the evaluation's
freeze anchor, complete pair IDs and distribution. An existing manifest cannot
silently switch to another dataset or freeze.

`scripts/build_fresh_semantic_dataset.py` contains the authored examples and
does not perform inference. It refuses to overwrite an existing evaluated set.
Its `--check` verifies the committed fixture against that source and manifest:

```powershell
.\.venv\Scripts\python.exe scripts\build_fresh_semantic_dataset.py --check
.\.venv\Scripts\python.exe -m news_similarity.cli dataset-stats --path src/news_similarity/data/synthetic_fresh_v1.json
```

Rebuilding requires a local development freeze and absent output files. Do not
delete or relabel an evaluated set to seek better metrics. A genuinely new
challenge should receive a new identity and manifest.

## Limits

Digit masking and string similarity are conservative surface checks, not
semantic leakage detection or external fact validation. Same-author scenario
design and templated contrasts can introduce systematic bias. Groups contain
related pairs, so 32 pairs are not 32 independent events. The previous test
errors were known when designing this targeted challenge. No independent
annotator agreement or unbiased population-performance estimate is available.

This fresh set has now been scored and inspected; it is no longer pristine for
future feature/model design. Use independently reviewed real data and another
untouched event-level holdout before making deployment or generalization claims.
