"""Measured diagnostic tables, explicit abstention accounting and paired errors."""


def _number(value):
    return "n/a" if value is None else f"{value:.4f}"


def render_hybrid_report(report):
    lines = [
        "# Hybrid matching: measured diagnostic results",
        "",
        "**Diagnostic only. Both synthetic sets were previously examined.**",
        report["independent_evaluation"],
        "",
        report["classification_definition"],
        "",
        f"Freeze SHA-256: `{report['freeze_sha256']}`.",
        "",
        "Frozen configuration: `" + str(report["configuration"]) + "`.",
        "",
        "Primary accuracy counts every abstention as an error. Recall/FNR include",
        "positive abstentions as misses. FPR uses all negatives, so inspect coverage",
        "and decided-only metrics before interpreting a lower FPR.",
        "",
        "Fusion parameters use grouped development selection of a binary ranking",
        "proxy. Factual gating rules and the 0.35 confirmed-claim penalty are fixed",
        "engineering choices, not tuned on diagnostic labels.",
        "",
    ]
    nested = report["selection"]["nested_group_validation"]
    lines += [
        "## Development group validation",
        "",
        "Conditional diagnostic validation; previous lexical "
        "configurations were fixed.",
        "",
    ]
    for name, metrics in nested.items():
        lines.append(
            f"- {name}: F1 {_number(metrics['f1'])}, "
            f"strict accuracy {_number(metrics['accuracy'])}, "
            f"coverage {_number(metrics['coverage'])}."
        )
    for name, evaluation in report["evaluations"].items():
        lines += [
            "",
            f"## {name}",
            "",
            "| Model | Precision | Recall | F1 | Strict accuracy | FPR | "
            "FNR incl. abstentions | Coverage |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for kind, result in evaluation["models"].items():
            metrics = result["metrics"]
            lines.append(
                "| "
                + kind
                + " | "
                + " | ".join(
                    _number(metrics[key])
                    for key in (
                        "precision",
                        "recall",
                        "f1",
                        "accuracy",
                        "false_positive_rate",
                        "false_negative_rate",
                        "coverage",
                    )
                )
                + " |"
            )
        lines += [
            "",
            "Confusion rows: true [different, same]; "
            "columns: predicted [different, same, uncertain].",
            "",
        ]
        for kind, result in evaluation["models"].items():
            metrics = result["metrics"]
            lines.append(
                f"- {kind}: `{metrics['confusion_matrix']}`; "
                f"abstentions `{metrics['abstentions']}`; "
                f"decided-only F1 {_number(metrics['decided_only']['f1'])}."
            )
        lines += [
            "",
            "### Scenario diagnostics",
            "",
            "| Scenario | Model | F1 | Strict accuracy | FPR | Coverage |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for kind, result in evaluation["models"].items():
            for scenario, metrics in result["per_scenario"].items():
                lines.append(
                    f"| {scenario} | {kind} | "
                    + " | ".join(
                        _number(metrics[key])
                        for key in ("f1", "accuracy", "false_positive_rate", "coverage")
                    )
                    + " |"
                )
        lines += [
            "",
            "Full per-scenario precision, recall, FNR, confusion matrices "
            "and conditional metrics are in `hybrid.evaluation.json`.",
            "",
            "### False-positive transitions",
            "",
        ]
        for kind, change in evaluation["false_positive_changes"].items():
            lines.append(
                f"- Against {kind}: FPR delta {_number(change['delta'])}; "
                f"{len(change['false_positives_to_uncertain'])} false positives "
                f"became uncertain; {len(change['false_positives_to_different'])} "
                "became different-event decisions."
            )
        lines += [
            "",
            "### Evidence changed score or decision",
            "",
            "| Pair | Category | Label | Score-only decision | "
            "Full decision | Penalty |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in evaluation["evidence_changes"]:
            lines.append(
                f"| {row['pair_id']} | {row['category']} | {row['label']} | "
                f"{row['without_events']} | {row['with_events']} | "
                f"{row['penalty']} |"
            )
        if not evaluation["evidence_changes"]:
            lines.append("| none | | | | | |")
        lines += [
            "",
            "Error-analysis evidence tags "
            "(not separate independently labeled benchmarks):",
            "",
        ]
        for tag, pair_ids in evaluation["error_analysis_pair_ids"].items():
            lines.append(
                f"- {tag}: {', '.join(pair_ids) if pair_ids else 'none observed'}."
            )
    lines += [
        "",
        "Lower false-positive rates may reflect abstention rather than "
        "better binary discrimination.",
        "No independent real-world accuracy claim is supported. "
        "Same-event update labels require a separate, independently reviewed "
        "identity policy and untouched event groups.",
        "",
    ]
    return "\n".join(lines)
