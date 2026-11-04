from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from news_similarity.hybrid import HybridMatcher
from news_similarity.ui.services.ui_facade import UiConfig, UiFacade

APP = Path(__file__).resolve().parents[1] / "src/news_similarity/ui/app.py"


@pytest.fixture
def ui_setup(repository, item, monkeypatch, tmp_path):
    from news_similarity.ui import runtime

    config = UiConfig(
        tmp_path, repository.engine.url.render_as_string(), tmp_path / "artifacts"
    )
    scorers = [Mock() for _ in range(3)]
    for scorer, score in zip(scorers, (0.25, 0.5, 0.75), strict=True):
        scorer.compare_batch.side_effect = lambda pairs, value=score: (
            [value] * len(pairs)
        )
    matcher = HybridMatcher(*scorers, model_metadata={"parameter_source": "mock_test"})
    facade = UiFacade(config, model_provider=lambda: matcher)
    monkeypatch.setattr(runtime, "get_facade", lambda: facade)
    return facade, scorers, config


def start():
    return AppTest.from_file(APP, default_timeout=15).run()


def fill_comparison(app):
    app.text_area(key="text_a").set_value("در تهران ۱۲ نفر آمدند.")
    app.text_area(key="text_b").set_value("در تهران ۱۳ نفر آمدند.")
    return app


def test_all_pages_render_and_empty_archive_is_explicit(ui_setup):
    app = start()
    assert not app.exception
    for page in ("archive",):
        app.switch_page(f"pages/{page}.py").run()
        assert not app.exception
        assert app.title
        assert app.info
    assert all(not scorer.compare_batch.called for scorer in ui_setup[1])


def test_editing_text_does_not_infer_and_scores_are_passed_through(ui_setup):
    app = fill_comparison(start())
    assert all(not scorer.compare_batch.called for scorer in ui_setup[1])
    app.button(key="compare_manual").click().run()
    assert not app.exception
    assert any("نامطمئن" in warning.value for warning in app.warning), (
        [error.value for error in app.error],
        [area.value for area in app.text_area],
        [scorer.compare_batch.call_count for scorer in ui_setup[1]],
    )
    assert app.dataframe[0].value["امتیاز خام"].tolist() == [0.25, 0.5, 0.75]
    assert all(scorer.compare_batch.call_count == 1 for scorer in ui_setup[1])
    app.text_area(key="text_a").set_value("متن تغییرکرده برای تحلیل بعدی").run()
    assert all(scorer.compare_batch.call_count == 1 for scorer in ui_setup[1])
    assert "در تهران ۱۲ نفر آمدند." in str(app.session_state["comparison_view"])


def test_empty_inputs_and_failed_submit_clear_old_results(ui_setup):
    app = start()
    app.button(key="compare_manual").click().run()
    assert app.error and not app.exception
    assert all(not scorer.compare_batch.called for scorer in ui_setup[1])
    fill_comparison(app).button(key="compare_manual").click().run()
    assert app.dataframe
    app.text_area(key="text_a").set_value("")
    app.button(key="compare_manual").click().run()
    assert app.error and not app.exception
    assert "comparison_view" not in app.session_state


def test_missing_models_are_shown_as_error_without_crashing(ui_setup, monkeypatch):
    from news_similarity.ui import runtime

    monkeypatch.setattr(runtime, "get_facade", lambda: UiFacade(ui_setup[2]))
    app = fill_comparison(start())
    app.button(key="compare_manual").click().run()
    assert not app.exception
    assert any("فایل‌های مدل" in error.value for error in app.error)
    assert not app.dataframe


def test_bad_source_link_is_rejected_before_inference(ui_setup):
    app = fill_comparison(start())
    app.text_input(key="url_a").set_value("javascript:alert(1)")
    app.button(key="compare_manual").click().run()
    assert app.error and not app.exception
    assert all(not scorer.compare_batch.called for scorer in ui_setup[1])


def test_stored_news_browse_and_rank_without_source_links(ui_setup, repository, item):
    repository.save_news(
        "telegram",
        item.channel_id,
        "مصنوعی الف",
        None,
        [replace(item, text="در تهران ۱۲ نفر آمدند.")],
    )
    other = replace(
        item,
        platform="bale",
        channel_id="other",
        text="در تهران ۱۳ نفر آمدند.",
        url=None,
    )
    repository.save_news("bale", "other", "مصنوعی ب", None, [other])
    app = start()
    assert not app.exception
    assert app.selectbox
    assert all(not scorer.compare_batch.called for scorer in ui_setup[1])
    app.button(key="compare_stored").click().run()
    assert not app.exception
    assert app.dataframe
    assert any("نامطمئن" in warning.value for warning in app.warning)
    assert all(scorer.compare_batch.call_count == 1 for scorer in ui_setup[1])
    app.switch_page("pages/archive.py").run()
    assert not app.exception
    assert app.dataframe[0].value["خبر ذخیره‌شده"].tolist() == [1, 1]
    assert (
        app.dataframe[0].value["وضعیت اتصال فعلی"].tolist()
        == ["این صفحه بررسی شبکه انجام نمی‌دهد"] * 2
    )


def test_archive_configuration_errors_are_localized(ui_setup, monkeypatch):
    from news_similarity.ui import runtime

    invalid = replace(ui_setup[2], database_url="invalid")
    monkeypatch.setattr(runtime, "get_facade", lambda: UiFacade(invalid))
    app = start().switch_page("pages/archive.py").run()
    assert not app.exception
    assert any("بایگانی" in error.value for error in app.error)


def test_actual_saved_insights_remain_separated_and_abstention_is_visible(
    ui_setup, monkeypatch
):
    from news_similarity.ui import runtime

    root = APP.parents[3]
    artifacts = root / "artifacts"
    if not (artifacts / "hybrid/hybrid.evaluation.json").exists():
        pytest.skip("Local ignored measured artifacts not present.")
    config = replace(ui_setup[2], artifacts=artifacts)
    monkeypatch.setattr(runtime, "get_facade", lambda: UiFacade(config))
    app = start().switch_page("pages/archive.py").run()
    app.checkbox(key="show_benchmarks").check().run()
    assert not app.exception
    assert any("۵۶" in warning.value for warning in app.warning)
    assert len(app.dataframe[0].value) == 5
    dataset = next(
        select for select in app.selectbox if select.label == "مجموعهٔ ارزیابی"
    )
    dataset.select("examined_challenge_diagnostic").run()
    assert not app.exception
    assert any("۳۲" in item.value for item in app.caption)
    assert "پوشش تصمیم" in app.dataframe[0].value.columns


def test_cached_model_resources_are_reused_and_artifact_change_invalidates(
    tmp_path, monkeypatch
):
    from news_similarity import hybrid_evaluation
    from news_similarity.ui.services.resources import model_resource, resource_stamp

    config = UiConfig(tmp_path, "sqlite:///:memory:", tmp_path / "artifacts")
    for path in config.model_files():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    loader = Mock(return_value=Mock())
    monkeypatch.setattr(hybrid_evaluation, "load_hybrid_matcher", loader)
    model_resource.clear()
    try:
        first = model_resource(config, resource_stamp(config))
        assert model_resource(config, resource_stamp(config)) is first
        assert loader.call_count == 1
        config.model_files()[0].write_text('{"changed":true}')
        assert model_resource(config, resource_stamp(config)) is not first
        assert loader.call_count == 2
    finally:
        model_resource.clear()
