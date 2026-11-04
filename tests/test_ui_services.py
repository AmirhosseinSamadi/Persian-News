import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("streamlit")

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from news_similarity.database.repository import NewsRepository
from news_similarity.event_comparison import compare_news_features
from news_similarity.hybrid import HybridConfig, HybridModelError, assess_scores
from news_similarity.records import NewsItem
from news_similarity.ui.components.evidence_panel import highlighted_evidence
from news_similarity.ui.services.benchmarks import presentation_metrics, read_benchmarks
from news_similarity.ui.services.ui_facade import (
    InputError,
    SourceInput,
    UiConfig,
    UiError,
    UiFacade,
    safe_url,
)


def measured_result(a="در تهران ۱۲ نفر آمدند.", b="در تهران ۱۳ نفر آمدند."):
    return assess_scores(0.25, 0.5, 0.75, compare_news_features(a, b), HybridConfig())


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "اخبار آزمایشی.db"
    repository = NewsRepository(f"sqlite:///{path.as_posix()}")
    repository.initialize()
    for channel, platform, count in (
        ("a", "telegram", 2),
        ("b", "telegram", 2),
        ("c", "synthetic", 1),
    ):
        items = [
            NewsItem(
                platform,
                channel,
                None,
                str(index),
                f"خبر مصنوعی {channel} شمارهٔ {index} در تهران؛ نمی‌رود.",
                datetime(2026, 1, index + 1, tzinfo=UTC),
                None,
            )
            for index in range(count)
        ]
        repository.save_news(platform, channel, None, None, items)
    repository.get_or_create_source("telegram", "empty", "منبع خالی", None)
    repository.close()
    config = UiConfig(tmp_path, f"sqlite:///{path.as_posix()}", tmp_path / "artifacts")
    return path, config


def test_read_only_archive_preserves_bytes_counts_and_original_unicode(archive):
    path, config = archive
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    facade = UiFacade(config)
    sources = facade.sources()
    assert [source.news_count for source in sources] == [2, 2, 1, 0]
    assert sources[0].latest_publication == datetime(2026, 1, 2, tzinfo=UTC)
    assert sources[-1].latest_publication is None
    assert facade.count_news() == 5
    news = facade.browse(limit=2)
    assert len(news) == 2
    assert news[0].published_at.tzinfo is not None
    assert "نمی‌رود" in news[0].text
    assert facade.get_news(news[0].id) == news[0]
    assert news[0].url is news[0].source_url is None
    assert facade.get_news(99999) is None
    assert len(facade.browse(limit=2, offset=2)) == 2
    assert facade.browse(source_id=sources[-1].id) == []
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_repository_read_only_mode_enforces_no_writes_and_does_not_create_file(
    archive, tmp_path
):
    path, _ = archive
    repository = NewsRepository(f"sqlite:///{path.as_posix()}", read_only=True)
    try:
        with pytest.raises(OperationalError):
            with repository.engine.begin() as connection:
                connection.execute(text("DELETE FROM news"))
        assert repository.count_news() == 5
    finally:
        repository.close()
    missing = tmp_path / "missing" / "news.db"
    with pytest.raises(FileNotFoundError):
        NewsRepository(f"sqlite:///{missing.as_posix()}", read_only=True)
    assert not missing.parent.exists()


def test_missing_empty_and_unavailable_database_are_graceful(tmp_path):
    missing = tmp_path / "missing.db"
    facade = UiFacade(UiConfig(tmp_path, f"sqlite:///{missing.as_posix()}", tmp_path))
    assert facade.sources() == facade.browse() == []
    assert facade.get_news(1) is None
    assert facade.count_news() == 0
    assert not missing.exists()
    with pytest.raises(InputError):
        facade.rank(1)
    repository = NewsRepository(f"sqlite:///{missing.as_posix()}")
    repository.initialize()
    repository.close()
    assert facade.sources() == []
    assert facade.count_news() == 0
    broken = UiFacade(UiConfig(tmp_path, "not a database URL", tmp_path))
    with pytest.raises(UiError, match="بایگانی"):
        broken.sources()
    missing.write_bytes(b"not sqlite")
    with pytest.raises(UiError):
        facade.browse()


@pytest.mark.parametrize(
    "a,b",
    [
        ("", "خبر"),
        ("خبر", "  "),
        ("\u200f", "خبر"),
        (None, "خبر"),
        ("ا" * 30001, "خبر"),
    ],
)
def test_empty_or_invalid_inputs_do_not_load_models(tmp_path, a, b):
    provider = Mock(side_effect=AssertionError("No loading"))
    facade = UiFacade(
        UiConfig(tmp_path, "sqlite:///:memory:", tmp_path), model_provider=provider
    )
    with pytest.raises(InputError):
        facade.compare(a, b)
    provider.assert_not_called()


def test_actual_service_result_and_uncertainty_are_passed_through(archive):
    _, config = archive
    model = Mock()
    result = measured_result()
    model.compare.return_value = result
    facade = UiFacade(config, model_provider=lambda: model)
    view = facade.compare(
        "خبر فارسی", "متن فارسی", SourceInput("منبع الف", "https://example.org/a")
    )
    assert view.result == result.to_dict()
    assert view.result["decision"] == "uncertain"
    assert view.result["word_similarity"] == 0.25
    assert view.source_a.name == "منبع الف"
    model.compare.assert_called_once_with("خبر فارسی", "متن فارسی")
    json.dumps(view.to_dict(), ensure_ascii=False)
    with pytest.raises(InputError):
        facade.compare("خبر", "متن", SourceInput(url="javascript:alert(1)"))


def test_missing_model_artifacts_are_not_substituted(archive):
    _, config = archive
    with pytest.raises(UiError, match="فایل‌های مدل"):
        UiFacade(config).compare("خبر فارسی", "متن فارسی")


def test_failed_model_inference_has_localized_error_without_private_exception(archive):
    _, config = archive
    model = Mock()
    model.compare.side_effect = HybridModelError("private token ABC")
    with pytest.raises(UiError) as caught:
        UiFacade(config, model_provider=lambda: model).compare("خبر", "متن")
    assert "private" not in str(caught.value)


def test_ranking_uses_cross_source_candidates_and_stable_record_mapping(archive):
    _, config = archive
    model = Mock()
    result = measured_result()

    def rank(query, candidates, top_k):
        assert query and len(candidates) == 2
        assert all("خبر مصنوعی b" in text for text in candidates)
        return [
            SimpleNamespace(index=1, result=result),
            SimpleNamespace(index=0, result=result),
        ]

    model.rank.side_effect = rank
    facade = UiFacade(config, model_provider=lambda: model)
    sources = facade.sources()
    query = facade.browse(source_id=sources[0].id)[0]
    ranked = facade.rank(
        query.id, target_source_id=sources[1].id, platform="telegram", top_k=2
    )
    assert len(ranked) == 2
    assert ranked[0].news.source_id == sources[1].id
    assert ranked[0].result == result.to_dict()
    assert ranked[0].news.published_at < ranked[1].news.published_at
    with pytest.raises(InputError):
        facade.rank(query.id, target_source_id=query.source_id)
    with pytest.raises(InputError):
        facade.rank(99999)
    assert facade.rank(query.id, platform="not-stored") == []
    assert model.rank.call_count == 1


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "javascript:alert(1)",
        "data:text/html,x",
        "https://",
        "https://user:secret@example.org",
        "https://example.org\nx",
        "https://example.org:abc",
    ],
)
def test_missing_and_unsafe_urls_are_not_linked(url):
    assert safe_url(url) is None


def test_safe_source_urls_and_environment_configuration(tmp_path):
    assert safe_url("https://example.org/خبر") == "https://example.org/خبر"
    config = UiConfig.from_environment(
        tmp_path,
        {
            "NEWS_UI_ARTIFACT_DIR": "custom",
            "NEWS_UI_MODEL_CACHE": "cache",
            "NEWS_UI_DEMO_MODE": "1",
        },
    )
    assert config.artifacts == tmp_path / "custom"
    assert config.demo_mode
    assert config.cache_folder == "cache"


def test_evidence_html_escapes_untrusted_source_text():
    text = "متن <script>alert(1)</script> فارسی"
    item = {
        "span": {"start": 4, "end": 12, "text": text[4:12]},
        "clause": {"start": 0, "end": len(text), "text": text},
    }
    html = highlighted_evidence(item)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<mark>" in html


def test_benchmark_missing_and_malformed_artifacts(tmp_path):
    assert all(artifact.error for artifact in read_benchmarks(tmp_path))
    folder = tmp_path / "tfidf"
    folder.mkdir()
    (folder / "evaluation.json").write_text('{"models": null}')
    assert read_benchmarks(tmp_path)[0].error


def test_benchmark_rates_derive_from_binary_counts_and_abstentions_are_preserved():
    binary = presentation_metrics(
        {"count": 4, "confusion_matrix": [[1, 1], [1, 1]], "f1": 0.5}
    )
    assert binary["coverage"] == 1
    assert binary["false_positive_rate"] == 0.5
    tri = presentation_metrics(
        {"count": 4, "confusion_matrix": [[0, 0, 2], [0, 0, 2]], "f1": 0}
    )
    assert tri["coverage"] == 0
    assert tri["abstention_rate"] == 1
    assert tri["false_negative_rate"] == 1
    with pytest.raises(ValueError):
        presentation_metrics({"count": 5, "confusion_matrix": [[1, 1], [1, 1]]})


def test_saved_benchmarks_are_read_without_inference_or_recalculation():
    root = Path(__file__).resolve().parents[1] / "artifacts"
    if not (root / "hybrid/hybrid.evaluation.json").exists():
        pytest.skip("Local ignored benchmark artifacts not present.")
    reports = read_benchmarks(root)
    assert not any(report.error for report in reports)
    assert len(reports[2].datasets) == 2
    full = [dataset.models["hybrid"]["metrics"] for dataset in reports[2].datasets]
    assert sum(metrics["count"] for metrics in full) == 56
    assert all(metrics["coverage"] == 0 for metrics in full)
