"""Two-view UI regressions with synthetic SQLite news and existing hybrid rules."""

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from news_similarity.hybrid import HybridMatcher
from news_similarity.ui.services.ui_facade import (
    ComparisonView,
    InputError,
    SourceInput,
    UiConfig,
    UiFacade,
)

APP = Path(__file__).resolve().parents[1] / "src/news_similarity/ui/app.py"


@pytest.fixture
def workspace(repository, item, tmp_path, monkeypatch):
    from news_similarity.ui import runtime

    first = replace(
        item, text="در تهران ۱۲ نفر ثبت نام کردند؛ این خبر مصنوعی است.", url=None
    )
    second = replace(
        first,
        message_id="43",
        text="بارش در کرمان گزارش شد؛ نمونهٔ مصنوعی.",
        published_at=first.published_at + timedelta(days=1),
    )
    third = replace(
        first,
        platform="bale",
        channel_id="2002",
        text="در تهران ۱۳ نفر ثبت نام کردند؛ خبر مصنوعی.",
    )
    repository.save_news(
        "telegram", "1001", "منبع مصنوعی تلگرام", None, [first, second]
    )
    repository.save_news("bale", "2002", "منبع مصنوعی بله", None, [third])
    models = [Mock() for _ in range(3)]
    for model, value in zip(models, (0.25, 0.5, 0.75), strict=True):
        model.compare_batch.side_effect = lambda pairs, score=value: (
            [score] * len(pairs)
        )
    matcher = HybridMatcher(
        *models, model_metadata={"parameter_source": "synthetic_ui_test"}
    )
    config = UiConfig(tmp_path, str(repository.engine.url), tmp_path / "artifacts")
    facade = UiFacade(config, model_provider=lambda: matcher)
    monkeypatch.setattr(runtime, "get_facade", lambda: facade)
    return facade, models, repository


def start():
    return AppTest.from_file(APP, default_timeout=15).run()


def test_default_cross_platform_previews_do_not_infer_or_modify_sqlite(workspace):
    facade, models, repo = workspace
    path = Path(repo.engine.url.database)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    app = start()
    assert not app.exception
    assert len(app.get("page_link")) == 2
    assert not app.sidebar
    assert (
        app.selectbox(key="telegram_news").value != app.selectbox(key="bale_news").value
    )
    assert (
        facade.get_news(app.selectbox(key="telegram_news").value).platform == "telegram"
    )
    assert facade.get_news(app.selectbox(key="bale_news").value).platform == "bale"
    assert not app.button(key="compare_stored").disabled
    assert all(not model.compare_batch.called for model in models)
    assert path.read_bytes() and hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_real_hybrid_output_is_bound_and_uncertainty_is_preserved(workspace):
    facade, models, _ = workspace
    first = next(
        n for n in facade.stored_options(platform="telegram") if "۱۲" in n.text
    )
    app = start()
    app.selectbox(key="telegram_news").set_value(first.id).run()
    app.button(key="compare_stored").click().run()
    assert not app.exception
    assert any("نامطمئن" in warning.value for warning in app.warning)
    result = app.session_state["stored_comparison"]["view"]["result"]
    assert result["decision"] == "uncertain"
    assert app.dataframe[0].value["امتیاز خام"].tolist() == [
        0.25,
        0.5,
        0.75,
    ]
    assert "event_evidence" in result and result["metadata"]
    assert all(model.compare_batch.call_count == 1 for model in models)


def test_selection_and_result_survive_navigation_and_archive_filter_changes(workspace):
    _, models, _ = workspace
    app = start()
    chosen = app.selectbox(key="telegram_news").value
    app.button(key="compare_stored").click().run()
    snapshot = app.session_state["stored_comparison"]
    app.switch_page("pages/archive.py").run()
    app.text_input(key="archive_search").set_value("تهران").run()
    app.switch_page("pages/comparison.py").run()
    assert not app.exception
    assert app.selectbox(key="telegram_news").value == chosen
    assert app.session_state["stored_comparison"] == snapshot
    assert all(model.compare_batch.call_count == 1 for model in models)


def test_search_clears_stale_result_disables_empty_pair_and_never_infers(workspace):
    _, models, _ = workspace
    app = start()
    app.button(key="compare_stored").click().run()
    app.text_input(key="telegram_search").set_value("هیچ_چنین_خبری_وجود_ندارد").run()
    assert not app.exception and app.button(key="compare_stored").disabled
    assert "stored_comparison" not in app.session_state
    assert all(model.compare_batch.call_count == 1 for model in models)


def test_sqlite_search_uses_all_records_and_literal_wildcards(workspace):
    facade, models, _ = workspace
    found = facade.stored_options(platform="telegram", search="تهران")
    assert len(found) == 1 and "۱۲" in found[0].text
    assert len(facade.stored_options(platform="bale", search="منبع مصنوعی بله")) == 1
    assert facade.stored_options(search="%") == facade.stored_options(search="_") == []
    assert all(not model.compare_batch.called for model in models)


def test_archive_can_send_an_older_selected_record_to_comparison(workspace):
    facade, _, _ = workspace
    first = next(
        n for n in facade.stored_options(platform="telegram") if "۱۲" in n.text
    )
    app = start().switch_page("pages/archive.py").run()
    app.selectbox(key="archive_platform").set_value("telegram").run()
    app.selectbox(key="archive_news").set_value(first.id).run()
    app.button(key="use_archive_news").click().run()
    assert not app.exception
    assert app.selectbox(key="telegram_news").value == first.id


def test_empty_database_has_explicit_empty_panels_and_disabled_action(
    tmp_path, monkeypatch
):
    from news_similarity.ui import runtime

    provider = Mock(side_effect=AssertionError("No inference on empty archive"))
    facade = UiFacade(
        UiConfig(tmp_path, f"sqlite:///{tmp_path / 'absent.db'}", tmp_path),
        model_provider=provider,
    )
    monkeypatch.setattr(runtime, "get_facade", lambda: facade)
    app = start()
    assert not app.exception and app.button(key="compare_stored").disabled
    assert (
        app.selectbox(key="telegram_news").disabled
        and app.selectbox(key="bale_news").disabled
    )
    app.switch_page("pages/archive.py").run()
    assert any("خالی" in notice.value for notice in app.info)
    provider.assert_not_called()
    assert not (tmp_path / "absent.db").exists()


def test_same_record_and_wrong_platform_are_rejected_before_model(workspace):
    facade, models, _ = workspace
    first = facade.stored_options(platform="telegram")[0]
    with pytest.raises(InputError, match="متفاوت"):
        facade.compare_stored(first.id, first.id)
    other = facade.stored_options(platform="telegram")[1]
    with pytest.raises(InputError, match="تلگرام"):
        facade.compare_stored(first.id, other.id)
    with pytest.raises(InputError, match="بایگانی"):
        facade.compare_stored(first.id, 99999)
    assert all(not model.compare_batch.called for model in models)


def test_missing_metadata_is_explicit_and_no_url_is_invented(workspace, monkeypatch):
    facade, models, _ = workspace
    original = facade.stored_options

    def incomplete(**kwargs):
        return [
            replace(n, source_name="", published_at=None, url=None, source_url=None)
            for n in original(**kwargs)
        ]

    monkeypatch.setattr(facade, "stored_options", incomplete)
    app = start()
    assert not app.exception
    assert not app.get("link_button")
    assert all(not model.compare_batch.called for model in models)


def test_missing_scores_or_model_metadata_do_not_produce_fake_values(
    workspace, monkeypatch
):
    facade, _, _ = workspace
    monkeypatch.setattr(
        facade,
        "compare_stored",
        lambda a, b: ComparisonView(
            {"decision": "uncertain", "combined_ranking_score": None},
            SourceInput(),
            SourceInput(),
        ),
    )
    app = start()
    app.button(key="compare_stored").click().run()
    assert not app.exception
    assert any("امتیاز ترکیبی معتبر" in text.value for text in app.caption)
    assert any("اطلاعات مدل" in text.value for text in app.caption)
    assert any("شواهد ساختاری" in text.value for text in app.info)


def test_no_record_can_be_compared_with_itself_even_with_inconsistent_selector_data(
    workspace, monkeypatch
):
    facade, models, _ = workspace
    same = facade.stored_options(platform="telegram")[0]
    monkeypatch.setattr(facade, "stored_options", lambda **kwargs: [same])
    app = start()
    assert not app.exception and app.button(key="compare_stored").disabled
    assert all(not model.compare_batch.called for model in models)
