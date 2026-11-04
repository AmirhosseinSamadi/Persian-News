"""Render measured baseline results and the fixed scientific protocol."""

from typing import Any


def render_baseline_report(report: dict[str, Any]) -> str:
    test_summary = report["dataset"]["splits"]["test"]
    positive = int(test_summary["labels"].get("1", 0))
    negative = int(test_summary["labels"].get("0", 0))
    total = positive + negative
    lines = [
        "# Phase 1.3A: TF-IDF baseline and scientific evaluation",
        "",
        "All results below were computed from the explicitly synthetic v1 fixture. "
        "No real Telegram/Bale collection or real-world generalization is verified.",
        "",
        "## Mathematics",
        "",
        r"For term count $c(t,d)>0$, sublinear TF is $1+\log c(t,d)$. "
        r"Smoothed IDF is $\log((1+N)/(1+df(t)))+1$. "
        r"The product is normalized to unit L2 length.",
        "",
        r"Cosine similarity is $s(x,y)=x^Ty/(\|x\|_2\|y\|_2)$. "
        "For L2-normalized vectors this is their dot product. Empty or entirely "
        "out-of-vocabulary vectors have score 0, including two empty inputs. "
        "Cosine scores are not calibrated probabilities.",
        "The weighting and normalization follow scikit-learn's "
        "[TfidfTransformer documentation]"
        "(https://scikit-learn.org/stable/modules/generated/"
        "sklearn.feature_extraction.text.TfidfTransformer.html).",
        "",
        "## Methodology and leakage controls",
        "",
        "Use the existing lexical profile with its builtin tokenizer, join the "
        "resulting tokens, and retain dates, numbers and negative forms. Word "
        "features use whitespace tokenization so scikit-learn does not split "
        "protected dates or discard one-character terms. Character features use "
        "`char_wb` on the same prepared text. Neither method removes stopwords.",
        "",
        "Each normalized, nonempty development article occurs once in the fit "
        "corpus, regardless of how many pairs reuse it. For each predeclared "
        "candidate, grouped out-of-fold (OOF) scores are computed using a fresh "
        "vectorizer fitted only on that fold's training development groups. "
        "The fold's vocabulary and IDF never see its validation articles.",
        "",
        "Thresholds maximize pooled development OOF F1, then precision, then "
        "accuracy, then higher threshold. Configuration ties use the declared "
        "grid order. Positive prediction requires `score > 0 and score >= threshold`. "
        "The all-negative candidate threshold is `nextafter(1, +inf)`.",
        "",
        "The chosen configuration is fitted once on all development articles. "
        "All requested model configurations and thresholds are finalized before "
        "test news are transformed. No vocabulary/IDF or threshold fitting uses "
        "test text or labels. Test labels are used only for final metrics/error "
        "analysis. The two methods are reported side by side; test performance "
        "does not select a deployment winner.",
        "",
        "OOF development metrics are selection statistics, not an unbiased "
        "estimate after trying configurations/thresholds. Development in-sample "
        "metrics are descriptive training diagnostics only. The final model's "
        "IDF differs from fold IDFs; the OOF-selected threshold is transferred "
        "unchanged to the final development fit.",
        "",
        f"Dataset: `{report['dataset']['name']}`, "
        f"schema {report['dataset']['schema_version']}; "
        f"canonical SHA-256 `{report['dataset']['sha256']}`.",
        "",
        f"Split: {report['dataset']['splits']['development']['pairs']} development / "
        f"{report['dataset']['splits']['test']['pairs']} test pairs; "
        f"GroupKFold={report['protocol']['folds']}, shuffle=True, "
        f"seed={report['protocol']['seed']}.",
        "",
        "Runtime: "
        + ", ".join(f"{key}={value}" for key, value in report["runtime"].items())
        + ".",
        "",
        "## Measured results",
        "",
        "Confusion matrices use rows=true and columns=predicted, ordered `[0,1]`: "
        "`[[TN, FP], [FN, TP]]`. Metrics use class 1 as positive and "
        "zero_division=0. F1 for an all-negative scenario can therefore be zero "
        "even when every negative example is correctly classified.",
        "",
        "| Model | Evaluation | Precision | Recall | F1 | Accuracy | "
        "Confusion matrix |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for kind, result in report["models"].items():
        for stage in ("development_oof", "development_in_sample", "test"):
            metrics = result[stage]["metrics"]
            lines.append(
                f"| {kind} | {stage} | {metrics['precision']:.6f} | "
                f"{metrics['recall']:.6f} | {metrics['f1']:.6f} | "
                f"{metrics['accuracy']:.6f} | `{metrics['confusion_matrix']}` |"
            )
    for kind, result in report["models"].items():
        config = result["configuration"]
        lines.extend(
            [
                "",
                f"## {kind.title()} model",
                "",
                f"Selected n-grams: ({config['ngram_min']}, {config['ngram_max']}); "
                f"min_df={config['min_df']}; sublinear_tf={config['sublinear_tf']}; "
                f"smooth_idf=True; L2 norm; lowercase=False; float64. "
                f"Threshold: **{result['threshold']:.17g}**. "
                f"Final fit: {result['fit_provenance']['document_count']} "
                "unique development "
                f"articles, {result['features']} features.",
                "",
                "### Development-only search",
                "",
                "| N-grams | Threshold | OOF precision | OOF recall | "
                "OOF F1 | OOF accuracy |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for trial in result["trials"]:
            metrics = trial["development_oof_metrics"]
            config = trial["configuration"]
            lines.append(
                f"| ({config['ngram_min']}, {config['ngram_max']}) | "
                f"{trial['threshold']:.9f} | {metrics['precision']:.6f} | "
                f"{metrics['recall']:.6f} | {metrics['f1']:.6f} | "
                f"{metrics['accuracy']:.6f} |"
            )
        lines.extend(
            [
                "",
                "### Performance by scenario",
                "",
                "| Scenario | Stage | N | Precision | Recall | F1 | Accuracy |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for stage in ("development_oof", "test"):
            for category, metrics in result[stage]["per_scenario"].items():
                lines.append(
                    f"| {category} | {stage} | {metrics['count']} | "
                    f"{metrics['precision']:.6f} | {metrics['recall']:.6f} | "
                    f"{metrics['f1']:.6f} | {metrics['accuracy']:.6f} |"
                )
        lines.extend(
            [
                "",
                "### Score distributions",
                "",
                "| Stage | True label | N | Min | Q25 | Median | Q75 | "
                "Max | Mean | Std |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for stage in ("development_oof", "test"):
            for label in ("0", "1"):
                stats = result[stage]["score_distributions"][label]
                values = " | ".join(
                    f"{stats[key]:.6f}" if stats[key] is not None else "n/a"
                    for key in ("min", "q25", "median", "q75", "max", "mean", "std")
                )
                lines.append(f"| {stage} | {label} | {stats['count']} | {values} |")
        for field, title in (
            ("false_positives", "False positives"),
            ("false_negatives", "False negatives"),
        ):
            errors = result["test"][field]
            lines.extend(["", f"### Held-out {title.lower()} ({len(errors)})", ""])
            if errors:
                lines.extend(["| Pair | Scenario | Score |", "| --- | --- | ---: |"])
                lines.extend(
                    f"| {row['pair_id']} | {row['category']} | {row['score']:.9f} |"
                    for row in errors
                )
                if field == "false_negatives":
                    for row in errors:
                        lines.extend(
                            [
                                "",
                                f"`{row['pair_id']}` missed paraphrase:",
                                "",
                                f"A: {row['text_a']}",
                                "",
                                f"B: {row['text_b']}",
                            ]
                        )
            else:
                lines.append("None in this synthetic test partition.")
        lines.extend(["", "### Factual-contrast diagnostics", ""])
        for category in (
            "negation_difference",
            "same_location_different_dates",
            "different_numbers",
            "same_topic_different_events",
        ):
            row = next(
                (row for row in result["test"]["pairs"] if row["category"] == category),
                None,
            )
            if row:
                lines.extend(
                    [
                        f"- `{row['pair_id']}` ({category}): "
                        f"label={row['label']}, prediction={row['prediction']}, "
                        f"score={row['score']:.9f}.",
                        f"  A: {row['text_a']}",
                        f"  B: {row['text_b']}",
                        "",
                    ]
                )
    lines.extend(
        [
            "## Interpretation and limitations",
            "",
            "Lexical overlap can stay high when dates, counts or negation change. "
            "Word and character n-grams do not reason about factual compatibility. "
            "Character features can retain partial spelling matches but also share "
            "substrings across contradictory claims; higher recall alone does not "
            "establish better robustness or real-news performance. Held-out group "
            "vocabulary can be OOV; even identical unseen inputs can score zero. "
            "Conversely, distinguishing dates/counts/words absent from the "
            "development vocabulary disappear from word vectors: contradictory "
            "claims can share a vector and score 1. This is not factual certainty.",
            "",
            f"The test partition has {positive} positives and {negative} negatives. "
            f"Always-negative prediction has accuracy {negative / total:.6f} "
            "and positive F1 0. Always-positive prediction has precision "
            f"{positive / total:.6f}, recall {int(positive > 0)}, "
            f"F1 {2 * positive / (total + positive):.6f} and accuracy "
            f"{positive / total:.6f}. These are descriptive reference policies, "
            "not tuned models.",
            "",
            f"Only {total} synthetic test pairs from "
            f"{test_summary['event_groups']} event groups are available. "
            "Within-group pairs are correlated and partly templated. There is no "
            "independent annotation agreement, domain coverage or uncertainty "
            "interval justifying strong conclusions. The development selection "
            "space is small and predeclared. Test results must not be used to "
            "revise this search while continuing to call the same test set untouched.",
            "",
            "## Persistence and reproducibility",
            "",
            "`artifacts/tfidf/` contains locally generated JSON models and measured "
            "evaluation outputs, excluded from Git. Each model records vocabulary, "
            "IDF, configuration, threshold, development fit IDs/count/corpus hash, "
            "dataset checksum, runtime versions and preprocessing fingerprint. "
            "Loading reconstructs state without fitting, pickle or joblib. Only "
            "use locally generated artifacts; schema validation is not an "
            "authenticity "
            "guarantee. A preprocessing or numerical-library version mismatch is "
            "rejected; regenerate with the documented environment.",
            "",
            "```powershell",
            "Set-Location -LiteralPath "
            "'D:\\University\\داده کاوی\\PersianNewsSimilarity'",
            ".\\.venv\\Scripts\\python.exe -m pip install "
            f"'scikit-learn=={report['runtime']['scikit-learn']}' "
            f"'numpy=={report['runtime']['numpy']}' "
            f"'scipy=={report['runtime']['scipy']}'",
            ".\\.venv\\Scripts\\python.exe -m pip install -e '.[dev,persian]'",
            ".\\.venv\\Scripts\\python.exe -m news_similarity.cli evaluate-tfidf "
            "--model both --output-dir artifacts/tfidf "
            "--report-path docs/PHASE_1_3A_REPORT.md",
            ".\\.venv\\Scripts\\python.exe -m news_similarity.cli compare "
            "--text-a 'خبر اول' --text-b 'خبر دوم'",
            ".\\.venv\\Scripts\\python.exe -m news_similarity.cli compare "
            "--model character --text-a 'خبر اول' --text-b 'خبر دوم'",
            ".\\.venv\\Scripts\\python.exe -m pytest -q",
            ".\\.venv\\Scripts\\python.exe -m ruff check .",
            ".\\.venv\\Scripts\\python.exe -m ruff format --check .",
            ".\\.venv\\Scripts\\python.exe -m pip check",
            "```",
            "",
            "Run with the recorded numerical versions for exact reproduction. "
            "`evaluate-tfidf --model word` and `--model character` also work "
            "separately; "
            "both use the same fixed split, folds and selection policy. `compare` "
            "loads the requested fitted artifact and never fits on its inputs. "
            "Complete per-pair scores, errors, distributions, fold audits and "
            "all development trials are in `evaluation.json`.",
            "",
            "## Phase 1.3B readiness",
            "",
            "The reusable fitted-model API and development/test evaluation contracts "
            "are ready for a future semantic-baseline comparison. No semantic "
            "embeddings, transformers, Bale integration or UI were implemented. "
            "Live Telegram remains unverified. Future work needs more independently "
            "reviewed event groups and an additional untouched test set if existing "
            "test errors inform feature or model design.",
            "",
        ]
    )
    return "\n".join(lines)
