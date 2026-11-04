"""Measured semantic comparison reports; never manufacture missing model scores."""

from typing import Any


def _number(value: Any) -> str:
    return "undefined" if value is None else f"{value:.6f}"


def _table_row(values: list[Any]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def render_semantic_report(report: dict[str, Any]) -> str:
    model = report["model"]
    config = model["configuration"]
    lines = [
        "# Phase 1.3B: semantic similarity and comparative evaluation",
        "",
        "All measured datasets in this report are synthetic. Historical results "
        "are exploratory because Phase 1.3A already exposed those test pairs. "
        "No real Telegram/Bale performance is claimed.",
        "",
        "## Model architecture and source",
        "",
        f"Model: `{config['model_id']}`. Commit: `{config['revision']}`. "
        "The fixed multilingual MiniLM sentence encoder uses a transformer "
        "and mean-token pooling. It is not fine-tuned in this project.",
        "",
        "[Official model card](https://huggingface.co/"
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) and "
        "[SentenceTransformer loading/encoding API](https://www.sbert.net/"
        "docs/package_reference/sentence_transformer/model.html).",
        "",
        f"Loaded metadata: embedding dimension={model['embedding_dimension']}; "
        f"maximum sequence length={model['max_seq_length']} tokens; "
        f"execution device={model['execution_device']}. "
        "Dimensions come from the encoder, not a global constant.",
        "",
        "## Embedding and similarity methodology",
        "",
        "Use the existing conservative semantic profile's normalized prose, "
        "retaining sentence order, dates, numbers, names, locations and negation. "
        "There is no stopword filtering, stemming or lexical token rejoining. "
        "Empty input is rejected before model loading. Repeated normalized "
        "documents reuse a bounded in-memory LRU cache.",
        "",
        r"Embeddings are L2-normalized: $\hat e=e/\|e\|_2$. "
        r"Similarity is $s(a,b)=\hat e_a^T\hat e_b$, in $[-1,1]$. "
        "Raw cosine scores are saved separately from thresholded predictions "
        "and are not calibrated probabilities. A score at or above the frozen "
        "threshold is predicted positive.",
        "",
        "## Threshold selection and freezing",
        "",
        f"Selected threshold: **{report['threshold']:.17g}**. "
        "Only the original development labels selected this value: maximize "
        "F1, then precision, accuracy and higher threshold. The pretrained "
        "encoder/configuration is fixed and has no fitted corpus statistics.",
        "",
        "A four-fold, seed-42 GroupKFold diagnostic selects a threshold on "
        "each training-group subset and applies it to its validation groups. "
        "Embeddings can be reused across folds because the frozen encoder "
        "does not learn from them. The final threshold uses all development "
        "groups. Selection-set metrics are optimistic; group-CV diagnostics "
        "do not change the final threshold.",
        "",
        "| Development statistic | Precision | Recall | F1 | Accuracy | FPR | FNR |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    keys = (
        "precision",
        "recall",
        "f1",
        "accuracy",
        "false_positive_rate",
        "false_negative_rate",
    )
    for name in ("development", "group_cv_threshold_metrics"):
        lines.append(_table_row([name, *[_number(report[name][key]) for key in keys]]))
    lines.extend(
        [
            "",
            "`freeze.json` records the threshold, revision, runtime, preprocessing "
            "fingerprint, development pair IDs and unchanged TF-IDF artifact hashes. "
            "It was saved before historical/fresh inference. Frozen TF-IDF "
            "vocabulary, IDF, configurations and thresholds are loaded without "
            "refitting. All methods receive identical pairs within each comparison.",
            "",
            f"Original dataset checksum: `{report['original_dataset']['sha256']}`.",
            "",
        ]
    )
    if report["fresh_manifest"]:
        manifest = report["fresh_manifest"]
        overlap = manifest["screening"]["maximum_number_masked_sequence_similarity"]
        lines.extend(
            [
                "## Fresh-set manifest",
                "",
                f"Dataset `{manifest['dataset']['name']}`: "
                f"{manifest['dataset']['total_pairs']} pairs across "
                f"{manifest['dataset']['event_groups']} event groups. "
                f"Canonical checksum `{manifest['dataset']['sha256']}`. "
                f"Freeze anchor `{manifest['freeze_sha256']}`.",
                "",
                "Fresh groups were authored after model/threshold freezing and "
                "locked before final inference. Pair/group/event IDs are disjoint "
                "from all original splits. Exact/near-duplicate screening masks "
                "digits and compares lexical-normalized character sequences, "
                "rejecting ratios >=0.85. This is a surface leakage check, "
                "not proof that every semantic relation is independent.",
                "",
                f"Maximum screened overlap: {overlap:.6f}.",
                "",
                "These are new synthetic event groups with same-author labels, "
                "not independently annotated real news or an unbiased population "
                "sample. No independent-annotator final performance is available. "
                "After this evaluation the fresh set is also inspected and must "
                "not be reused as pristine evidence for subsequent model design.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Fresh evaluation unavailable",
                "",
                "No independent newly labeled dataset was supplied. "
                "Historical exploratory results do not substitute for it.",
                "",
            ]
        )
    for stage, evaluation in report["evaluations"].items():
        lines.extend(
            [
                f"## {stage}",
                "",
                "Confusion matrices are `[[TN, FP], [FN, TP]]`; class 1 is positive. "
                "FPR=FP/(TN+FP), FNR=FN/(FN+TP). A missing denominator is undefined, "
                "not zero. Other undefined positive metrics use zero_division=0.",
                "",
                (
                    "| Model | N | Precision | Recall | F1 | Accuracy | FPR | "
                    "FNR | Matrix |"
                ),
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for kind, result in evaluation["models"].items():
            metrics = result["metrics"]
            lines.append(
                _table_row(
                    [
                        kind,
                        metrics["count"],
                        *[_number(metrics[key]) for key in keys],
                        f"`{metrics['confusion_matrix']}`",
                    ]
                )
            )
        lines.extend(
            [
                "",
                "### Per-scenario performance",
                "",
                (
                    "| Model | Scenario | N | Precision | Recall | F1 | "
                    "Accuracy | FPR | FNR |"
                ),
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for kind, result in evaluation["models"].items():
            for category, metrics in result["per_scenario"].items():
                lines.append(
                    _table_row(
                        [
                            kind,
                            category,
                            metrics["count"],
                            *[_number(metrics[key]) for key in keys],
                        ]
                    )
                )
        lines.extend(["", "### Paired error changes", ""])
        for kind, differences in evaluation["paired_error_differences"].items():
            lines.extend(
                [
                    f"Against {kind}, semantic correct / baseline wrong: "
                    + (
                        ", ".join(differences["semantic_correct_baseline_wrong"])
                        or "none"
                    )
                    + ".",
                    "",
                    f"Against {kind}, semantic wrong / baseline correct: "
                    + (
                        ", ".join(differences["semantic_wrong_baseline_correct"])
                        or "none"
                    )
                    + ".",
                    "",
                ]
            )
        semantic = evaluation["models"]["semantic"]
        for field in ("false_positives", "false_negatives"):
            lines.extend(
                [
                    f"### Semantic {field} ({len(semantic[field])})",
                    "",
                    "| Pair | Scenario | Raw cosine |",
                    "| --- | --- | ---: |",
                ]
            )
            for row in semantic[field]:
                lines.append(
                    _table_row([row["pair_id"], row["category"], _number(row["score"])])
                )
            lines.append("")
        lines.extend(["### Qualitative diagnostics", ""])
        for category in semantic["per_scenario"]:
            rows = [row for row in semantic["pairs"] if row["category"] == category]
            row = next(
                (row for row in rows if row["label"] != row["prediction"]), rows[0]
            )
            lines.extend(
                [
                    f"- `{row['pair_id']}` ({category}): true={row['label']}, "
                    f"predicted={row['prediction']}, cosine={row['score']:.6f}.",
                    f"  A: {row['text_a']}",
                    f"  B: {row['text_b']}",
                    "",
                ]
            )
    lines.extend(
        [
            "## Computational requirements and runtime",
            "",
            f"CPU thread limit={config['cpu_threads']}; "
            f"batch size={config['batch_size']}; "
            f"embedding LRU capacity={config['embedding_cache_size']}. "
            f"This run encoded {model['encoded_documents']} unique uncached documents. "
            f"Model load={model['load_seconds']:.3f}s; "
            f"encoding={model['inference_seconds']:.3f}s "
            "(measured wall time, excluding "
            "dependency installation). Hardware memory use was not profiled.",
            "",
            "The cached safetensors weight file is approximately 471 MB. Inference "
            "uses float32 model weights; cached vectors are explicitly normalized "
            "in float64. Longer texts can be truncated at the recorded token limit, "
            "potentially dropping a late number or negation. CPU works without "
            "CUDA; a requested unavailable CUDA device falls back to "
            "CPU and is recorded.",
            "",
            "Runtime versions: "
            + ", ".join(f"{key}={value}" for key, value in model["runtime"].items())
            + ".",
            "",
            "## Threats to validity and recommendations",
            "",
            "The old test set informed prior analysis, so that comparison is "
            "exploratory. The fresh set is a small synthetic challenge with related "
            "pairs within each family, targeted categories, same-author labels "
            "and no annotation agreement study. Do not infer general superiority "
            "or unbiased real-news accuracy from these scores or selected examples.",
            "",
            "Embedding proximity need not preserve factual equality: similar "
            "topics, changed dates/counts, negation or location names can remain "
            "close. Different n-gram and embedding preprocessing profiles are "
            "intentional method-specific choices. Pretraining contamination cannot "
            "be ruled out merely by local group separation. No model was fine-tuned.",
            "",
            "Before cross-platform matching, collect authorized real examples, "
            "obtain independent event-level annotations, create a new untouched "
            "evaluation set, and examine truncation and factual-contrast errors. "
            "Telegram remains unverified; Bale integration and UI are outside scope.",
            "",
            "## Reproduction and safe loading",
            "",
            "Artifacts and any downloaded weights stay under ignored "
            "`artifacts/semantic/`. Existing Hugging Face snapshots are reused. "
            "Loading is pinned to the recorded revision, uses safetensors, sets "
            "trust_remote_code=False and defaults to cache-only. No credentials "
            "are required for the public model. Use --allow-download only when "
            "the pinned snapshot is absent. Ordinary tests mock all heavy model "
            "operations; real pretrained integration is explicitly opt-in.",
            "",
            "```powershell",
            (
                "Set-Location -LiteralPath 'D:\\University\\داده "
                "کاوی\\PersianNewsSimilarity'"
            ),
            ".\\.venv\\Scripts\\python.exe -m pip install -e '.[dev,persian,semantic]'",
            (
                ".\\.venv\\Scripts\\python.exe -m news_similarity.cli "
                "evaluate-semantic --freeze-only"
            ),
            (
                ".\\.venv\\Scripts\\python.exe -m news_similarity.cli "
                "evaluate-semantic --fresh-dataset "
                "src/news_similarity/data/synthetic_fresh_v1.json"
            ),
            (
                ".\\.venv\\Scripts\\python.exe -m news_similarity.cli "
                "compare-semantic --text-a 'خبر اول' --text-b 'خبر دوم'"
            ),
            ".\\.venv\\Scripts\\python.exe -m pytest -q",
            "$env:RUN_SEMANTIC_INTEGRATION = '1'",
            ".\\.venv\\Scripts\\python.exe -m pytest -q -m semantic_integration",
            "Remove-Item Env:RUN_SEMANTIC_INTEGRATION",
            "```",
            "",
            "Pin the recorded runtime versions for numeric reproduction. "
            "Thresholds and baseline hashes are immutable in an artifact directory; "
            "a new protocol needs a separate directory. The checked-in report and "
            "JSON outputs contain actual measured scores, not mocked test outputs.",
            "",
        ]
    )
    return "\n".join(lines)
