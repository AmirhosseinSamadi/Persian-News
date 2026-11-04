"""PowerShell-friendly, explicitly triggered command-line operations."""

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from news_similarity.collectors.telegram import TelegramCollector
from news_similarity.config import ConfigurationError, Settings
from news_similarity.database.repository import NewsRepository
from news_similarity.evaluation import DatasetValidationError, load_dataset
from news_similarity.preprocessing import PersianPreprocessor, PreprocessingOptions
from news_similarity.records import CollectionSummary
from news_similarity.services.collection import CollectionService


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Persian news collection and preprocessing"
    )
    root.add_argument(
        "--env-file", default=".env", help="Environment file (default: .env)"
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="Create missing SQLite tables")
    collect = commands.add_parser(
        "collect-telegram", help="Collect authorized channel history"
    )
    collect.add_argument("--channel", required=True)
    collect.add_argument("--limit", type=positive_integer, default=30)
    listing = commands.add_parser("list-news", help="List recent news as JSON")
    listing.add_argument("--limit", type=positive_integer, default=10)
    listing.add_argument("--source-id", type=positive_integer)
    stats = commands.add_parser("stats", help="Show counts and source IDs as JSON")
    stats.add_argument("--source-id", type=positive_integer)
    commands.add_parser("collection-status", help="Read durable bot collection status")
    for name in ("collect-telegram-bot", "collect-bale"):
        bot = commands.add_parser(name, help="One-shot authorized Bot API collection")
        bot.add_argument("--limit", type=positive_integer, default=30)
        bot.add_argument("--duration", type=int, default=30)
        bot.add_argument("--poll-seconds", type=int, default=15)
        bot.add_argument("--bot-env-file", default=".env.bot-probes")
        bot.add_argument("--exclusive-test-bot", action="store_true")
        bot.add_argument(
            "--acknowledge-stored",
            action="store_true",
            help="Irreversibly confirm only durably processed updates",
        )
    preprocess = commands.add_parser(
        "preprocess", help="Preprocess text without changing the database"
    )
    preprocess.add_argument("--text", required=True)
    preprocess.add_argument(
        "--profile", choices=["lexical", "semantic"], default="lexical"
    )
    preprocess.add_argument(
        "--tokenizer", choices=["builtin", "hazm"], default="builtin"
    )
    preprocess.add_argument("--zwnj", choices=["preserve", "space", "remove"])
    preprocess.add_argument("--urls", choices=["keep", "remove"])
    preprocess.add_argument("--hashtags", choices=["keep", "strip", "remove"])
    preprocess.add_argument("--mentions", choices=["keep", "strip", "remove"])
    preprocess.add_argument("--remove-stopwords", action="store_true")
    dataset = commands.add_parser(
        "dataset-stats", help="Validate and summarize synthetic evaluation data"
    )
    dataset.add_argument(
        "--path",
        help="Optional UTF-8 JSON dataset; defaults to packaged synthetic data",
    )
    evaluate = commands.add_parser(
        "evaluate-tfidf", help="Select on development and evaluate frozen TF-IDF models"
    )
    evaluate.add_argument(
        "--model", choices=["word", "character", "both"], default="both"
    )
    evaluate.add_argument("--dataset", help="Optional validated synthetic dataset JSON")
    evaluate.add_argument("--output-dir", default="artifacts/tfidf")
    evaluate.add_argument(
        "--report-path", help="Also write the measured Markdown report here"
    )
    evaluate.add_argument("--folds", type=positive_integer, default=4)
    evaluate.add_argument("--seed", type=int, default=42)
    compare = commands.add_parser(
        "compare", help="Compare news using a saved model; never train on the inputs"
    )
    compare.add_argument("--text-a", required=True)
    compare.add_argument("--text-b", required=True)
    compare.add_argument("--model", choices=["word", "character"], default="word")
    compare.add_argument(
        "--model-path",
        help="Local JSON model; default artifacts/tfidf/<model>.model.json",
    )
    features = commands.add_parser(
        "compare-features",
        help="Compare explicit event evidence without a similarity score",
    )
    features.add_argument("--text-a", required=True)
    features.add_argument("--text-b", required=True)
    for name in ("compare-hybrid", "evaluate-hybrid"):
        hybrid = commands.add_parser(name, help="Frozen event-aware hybrid matching")
        hybrid.add_argument("--baseline-dir", default="artifacts/tfidf")
        hybrid.add_argument(
            "--semantic-freeze", default="artifacts/semantic/freeze.json"
        )
        hybrid.add_argument("--output-dir", default="artifacts/hybrid")
        hybrid.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
        hybrid.add_argument("--batch-size", type=positive_integer, default=16)
        hybrid.add_argument("--cache-folder")
        hybrid.add_argument("--allow-download", action="store_true")
        if name == "compare-hybrid":
            hybrid.add_argument("--text-a", required=True)
            hybrid.add_argument("--text-b", required=True)
            hybrid.add_argument("--freeze-path")
        else:
            hybrid.add_argument("--folds", type=positive_integer, default=4)
            hybrid.add_argument("--seed", type=int, default=42)
            hybrid.add_argument("--diagnostic-dataset")
            hybrid.add_argument("--freeze-only", action="store_true")
    for name, help_text in (
        (
            "evaluate-semantic",
            "Evaluate a frozen MiniLM model against frozen TF-IDF baselines",
        ),
        (
            "compare-semantic",
            "Compare texts with the pinned multilingual MiniLM encoder",
        ),
    ):
        semantic = commands.add_parser(name, help=help_text)
        semantic.add_argument(
            "--device", choices=["cpu", "cuda", "auto"], default="cpu"
        )
        semantic.add_argument("--batch-size", type=positive_integer, default=16)
        semantic.add_argument(
            "--cache-folder", help="Optional Hugging Face hub cache root"
        )
        semantic.add_argument(
            "--allow-download",
            action="store_true",
            help="Download missing pinned safetensors files; default is cache-only",
        )
        semantic.add_argument("--output-dir", default="artifacts/semantic")
        if name == "evaluate-semantic":
            semantic.add_argument(
                "--report-path", help="Also write the measured Markdown report here"
            )
            semantic.add_argument("--baseline-dir", default="artifacts/tfidf")
            semantic.add_argument(
                "--fresh-dataset", help="Optional independent synthetic all-test JSON"
            )
            semantic.add_argument(
                "--freeze-only",
                action="store_true",
                help="Freeze development threshold before preparing fresh event groups",
            )
        else:
            semantic.add_argument("--text-a", required=True)
            semantic.add_argument("--text-b", required=True)
    return root


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    # Python's Windows console supports Unicode; redirected PowerShell output
    # may otherwise inherit a legacy encoding that cannot represent Persian.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    repository = None
    try:
        if args.command in {
            "collect-telegram-bot",
            "collect-bale",
            "collection-status",
        }:
            from news_similarity.services.bot_collection import run_cli

            return run_cli(args)
        # Text/dataset commands need no credentials, config file or SQLite writes.
        if args.command in {"compare-hybrid", "evaluate-hybrid"}:
            from pathlib import Path

            from news_similarity.hybrid import HybridModelError
            from news_similarity.hybrid_evaluation import (
                evaluate_hybrid,
                load_hybrid_matcher,
            )
            from news_similarity.semantic import (
                SemanticConfig,
                SemanticModelError,
                SemanticSimilarity,
            )

            model = SemanticSimilarity(
                SemanticConfig(
                    device=args.device,
                    batch_size=args.batch_size,
                    cache_folder=args.cache_folder,
                    local_files_only=not args.allow_download,
                )
            )
            try:
                if args.command == "compare-hybrid":
                    matcher = load_hybrid_matcher(
                        model,
                        baseline_directory=args.baseline_dir,
                        semantic_freeze=args.semantic_freeze,
                        freeze_path=args.freeze_path
                        or Path(args.output_dir) / "hybrid.freeze.json",
                    )
                    print_json(matcher.compare(args.text_a, args.text_b).to_dict())
                else:
                    report = evaluate_hybrid(
                        load_dataset(),
                        model,
                        baseline_directory=args.baseline_dir,
                        semantic_freeze=args.semantic_freeze,
                        directory=args.output_dir,
                        diagnostic_dataset=load_dataset(args.diagnostic_dataset)
                        if args.diagnostic_dataset
                        else None,
                        folds=args.folds,
                        seed=args.seed,
                        freeze_only=args.freeze_only,
                    )
                    print_json(
                        {
                            "status": report["status"],
                            "configuration": report["configuration"],
                            "independent_evaluation": report["independent_evaluation"],
                            "output_directory": args.output_dir,
                            "evaluations": {
                                name: {
                                    kind: value["metrics"]
                                    for kind, value in result["models"].items()
                                }
                                for name, result in report.get(
                                    "evaluations", {}
                                ).items()
                            },
                        }
                    )
                return 0
            except (SemanticModelError, HybridModelError) as error:
                print(f"Hybrid model unavailable: {error}", file=sys.stderr)
                return 1
        if args.command == "compare-features":
            from news_similarity.event_comparison import compare_news_features

            print_json(compare_news_features(args.text_a, args.text_b).to_dict())
            return 0
        if args.command == "preprocess":
            overrides = {
                name: getattr(args, name)
                for name in (
                    "tokenizer",
                    "zwnj",
                    "urls",
                    "hashtags",
                    "mentions",
                    "remove_stopwords",
                )
                if getattr(args, name) is not None
            }
            options = PreprocessingOptions.for_profile(args.profile, **overrides)
            print_json(
                asdict(PersianPreprocessor(args.profile, options).process(args.text))
            )
            return 0
        if args.command == "dataset-stats":
            print_json(load_dataset(args.path).summary())
            return 0
        if args.command == "evaluate-tfidf":
            from pathlib import Path

            from news_similarity.baseline_reporting import render_baseline_report
            from news_similarity.benchmark import run_evaluation, save_evaluation

            kinds = ("word", "character") if args.model == "both" else (args.model,)
            report, models = run_evaluation(
                load_dataset(args.dataset),
                kinds=kinds,
                folds=args.folds,
                seed=args.seed,
            )
            path = save_evaluation(report, models, args.output_dir)
            if args.report_path:
                destination = Path(args.report_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(render_baseline_report(report), encoding="utf-8")
            print_json(
                {
                    "evaluation_path": str(path),
                    "models": {
                        kind: {
                            "configuration": result["configuration"],
                            "threshold": result["threshold"],
                            "development_oof": result["development_oof"]["metrics"],
                            "test": result["test"]["metrics"],
                        }
                        for kind, result in report["models"].items()
                    },
                }
            )
            return 0
        if args.command == "compare":
            from news_similarity.benchmark import predictions
            from news_similarity.tfidf import TfidfSimilarity

            path = args.model_path or f"artifacts/tfidf/{args.model}.model.json"
            model = TfidfSimilarity.load(path)
            if model.config.kind != args.model:
                raise ValueError(
                    "Requested model kind does not match the saved artifact."
                )
            score = model.compare(args.text_a, args.text_b)
            print_json(
                {
                    "model": args.model,
                    "score": score,
                    "threshold": model.threshold,
                    "prediction": predictions([score], model.threshold)[0]
                    if model.threshold is not None
                    else None,
                    "score_interpretation": "cosine similarity, "
                    "not a calibrated probability",
                    "fitted_on": model.provenance["fit_split"],
                }
            )
            return 0
        if args.command in {"evaluate-semantic", "compare-semantic"}:
            from pathlib import Path

            from news_similarity.semantic import (
                SemanticConfig,
                SemanticModelError,
                SemanticSimilarity,
            )
            from news_similarity.semantic_evaluation import (
                evaluate_semantic,
                freeze_semantic,
                load_semantic_freeze,
                semantic_predictions,
            )

            model = SemanticSimilarity(
                SemanticConfig(
                    device=args.device,
                    batch_size=args.batch_size,
                    cache_folder=args.cache_folder,
                    local_files_only=not args.allow_download,
                )
            )
            try:
                if args.command == "compare-semantic":
                    score = model.compare(args.text_a, args.text_b)
                    freeze_path = Path(args.output_dir) / "freeze.json"
                    threshold = None
                    if freeze_path.exists():
                        frozen = load_semantic_freeze(freeze_path)
                        if (
                            frozen["model"]["configuration"]["revision"]
                            != model.config.revision
                            or frozen["model"]["preprocessing_fingerprint"]
                            != model.metadata()["preprocessing_fingerprint"]
                        ):
                            raise ValueError(
                                "Saved semantic threshold does not match "
                                "the encoder/preprocessing."
                            )
                        threshold = frozen["threshold"]
                    print_json(
                        {
                            "score": score,
                            "threshold": threshold,
                            "prediction": semantic_predictions([score], threshold)[0]
                            if threshold is not None
                            else None,
                            "interpretation": "raw cosine similarity, "
                            "not a calibrated probability",
                            "model": model.metadata(),
                        }
                    )
                    return 0
                dataset = load_dataset()
                if args.freeze_only:
                    frozen = freeze_semantic(
                        model,
                        dataset,
                        baseline_directory=args.baseline_dir,
                        directory=args.output_dir,
                    )
                    print_json(
                        {
                            "status": "frozen_before_evaluation",
                            "threshold": frozen["threshold"],
                            "development": frozen["development"]["metrics"],
                            "model": frozen["model"],
                        }
                    )
                    return 0
                report = evaluate_semantic(
                    model,
                    dataset,
                    baseline_directory=args.baseline_dir,
                    directory=args.output_dir,
                    fresh=load_dataset(args.fresh_dataset)
                    if args.fresh_dataset
                    else None,
                )
                if args.report_path:
                    from news_similarity.semantic_reporting import (
                        render_semantic_report,
                    )

                    destination = Path(args.report_path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(
                        render_semantic_report(report), encoding="utf-8"
                    )
                print_json(
                    {
                        "status": report["status"],
                        "threshold": report["threshold"],
                        "execution_device": report["model"]["execution_device"],
                        "evaluations": {
                            name: {
                                kind: result["metrics"]
                                for kind, result in value["models"].items()
                            }
                            for name, value in report["evaluations"].items()
                        },
                    }
                )
                return 0
            except SemanticModelError as error:
                print(f"Semantic model unavailable: {error}", file=sys.stderr)
                return 1
        settings = Settings.load(args.env_file)
        logging.basicConfig(
            level=settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logging.getLogger("telethon").setLevel(logging.WARNING)
        if args.command == "collect-telegram":
            settings.require_telegram()
        repository = NewsRepository(settings.database_url)
        repository.initialize()
        if args.command == "init-db":
            print("Database initialized.")
        elif args.command == "collect-telegram":

            async def run_collection() -> CollectionSummary:
                # Telethon must be created and used in the same running loop.
                collector = TelegramCollector(settings)
                return await CollectionService(repository, collector).collect(
                    args.channel, args.limit
                )

            summary = asyncio.run(run_collection())
            print_json(
                {
                    **asdict(summary),
                    "requested_limit": args.limit,
                    "error_count": len(summary.errors),
                }
            )
            return 1 if summary.errors else 0
        elif args.command == "list-news":
            print_json(
                [
                    {
                        "id": item.id,
                        "source_id": item.source_id,
                        "message_id": item.external_id,
                        "text": item.text,
                        "published_at": item.published_at.isoformat(),
                        "collected_at": item.collected_at.isoformat(),
                        "url": item.url,
                    }
                    for item in repository.recent_news(args.limit, args.source_id)
                ]
            )
        elif args.command == "stats":
            print_json(
                {
                    "total_news": repository.count_news(args.source_id),
                    "sources": [
                        {
                            "id": source.id,
                            "platform": source.platform,
                            "external_id": source.external_id,
                            "name": source.name,
                            "url": source.url,
                            "news_count": repository.count_news(source.id),
                        }
                        for source in repository.list_sources()
                        if args.source_id is None or source.id == args.source_id
                    ],
                }
            )
        return 0
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except (DatasetValidationError, ValueError) as error:
        print(f"Input error: {error}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError, sqlite3.Error):
        print(
            (
                "Artifact storage failed. Check paths and permissions."
                if args.command
                in {
                    "compare",
                    "evaluate-tfidf",
                    "compare-semantic",
                    "evaluate-semantic",
                    "compare-hybrid",
                    "evaluate-hybrid",
                }
                else "Database or session storage failed. Check paths and permissions."
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Collection cancelled.", file=sys.stderr)
        return 130
    finally:
        if repository is not None:
            repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
