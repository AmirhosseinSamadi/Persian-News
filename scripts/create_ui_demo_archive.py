"""Explicitly create a separate, labeled synthetic UI demo; never collect news."""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from news_similarity.database.repository import NewsRepository
from news_similarity.evaluation import load_dataset
from news_similarity.records import NewsItem


def create_demo_archive(path: Path) -> int:
    path = path.resolve()
    production = Path(__file__).resolve().parents[1] / "data/news.db"
    if path == production.resolve() or path.exists():
        raise ValueError(
            "Choose a new, separate demo file; "
            "existing databases are never overwritten."
        )
    pairs, groups = [], set()
    for pair in load_dataset().pairs:
        if pair.event_group_id not in groups:
            pairs.append(pair)
            groups.add(pair.event_group_id)
        if len(pairs) == 8:
            break
    repository = NewsRepository(f"sqlite:///{path.as_posix()}")
    try:
        repository.initialize()
        for side, label in (("a", "الف"), ("b", "ب")):
            name = f"منبع نمایشی {label} · مصنوعی"
            items = [
                NewsItem(
                    "synthetic",
                    f"demo-{side}",
                    name,
                    pair.pair_id,
                    getattr(pair, f"text_{side}"),
                    datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
                )
                for index, pair in enumerate(pairs)
            ]
            repository.save_news("synthetic", f"demo-{side}", name, None, items)
        return repository.count_news()
    finally:
        repository.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".tmp/ui-demo.db"))
    args = parser.parse_args()
    count = create_demo_archive(args.output)
    print(
        f"Created {count} SYNTHETIC fixture records; "
        "timestamps are fictional demo metadata."
    )
    print("Use NEWS_UI_DEMO_MODE=1 and DATABASE_URL pointing to this separate file.")
