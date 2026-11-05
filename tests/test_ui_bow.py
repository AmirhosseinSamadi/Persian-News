"""Opt-in BoW integration, with the existing Hybrid path left as default."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
from test_ui_redesign import workspace as workspace

from news_similarity.bow import BagOfWordsSimilarity
from news_similarity.ui.services.bow_comparison import compare_stored_bow
from news_similarity.ui.services.ui_facade import InputError

APP = Path(__file__).resolve().parents[1] / "src/news_similarity/ui/app.py"


def test_hybrid_default_bow_is_opt_in_and_cached_results_do_not_cross_methods(
    workspace,
):
    facade, models, _ = workspace
    app = AppTest.from_file(APP).run()
    assert app.selectbox(key="comparison_method").value == "hybrid"
    app.button(key="compare_stored").click().run()
    hybrid_state = app.session_state["stored_comparison"]
    assert all(model.compare_batch.call_count == 1 for model in models)
    app.selectbox(key="comparison_method").set_value("bow").run()
    assert not app.exception and not app.warning
    assert "stored_bow_comparison" not in app.session_state
    app.button(key="compare_stored").click().run()
    assert not app.exception
    first = facade.get_news(app.selectbox(key="telegram_news").value)
    second = facade.get_news(app.selectbox(key="bale_news").value)
    result = app.session_state["stored_bow_comparison"]["view"]["result"]
    assert result["cosine_similarity"] == BagOfWordsSimilarity().compare(
        first.text, second.text
    )
    assert result["method"] == "bow_cosine" and "decision" not in result
    assert any("Bag of Words + Cosine Similarity" in m.value for m in app.markdown)
    assert all(model.compare_batch.call_count == 1 for model in models)
    app.run()
    app.switch_page("pages/archive.py").run()
    app.switch_page("pages/comparison.py").run()
    assert app.selectbox(key="comparison_method").value == "bow"
    assert app.session_state["stored_bow_comparison"]["view"]["result"] == result
    app.selectbox(key="comparison_method").set_value("hybrid").run()
    assert not app.exception and app.session_state["stored_comparison"] == hybrid_state
    assert all(model.compare_batch.call_count == 1 for model in models)


def test_manual_bow_does_not_load_models_and_record_guards_stay_strict(workspace):
    facade, models, _ = workspace
    app = AppTest.from_file(APP).run()
    app.selectbox(key="comparison_method").set_value("bow").run()
    app.text_area(key="text_a").set_value("باران تهران")
    app.text_area(key="text_b").set_value("باران شیراز")
    app.button(key="compare_manual").click().run()
    assert not app.exception
    result = app.session_state["bow_comparison_view"]["result"]
    assert result["cosine_similarity"] == pytest.approx(0.5)
    assert all(not model.compare_batch.called for model in models)
    items = facade.stored_options(platform="telegram")
    with pytest.raises(InputError):
        compare_stored_bow(facade, items[0].id, items[0].id)
    with pytest.raises(InputError):
        compare_stored_bow(facade, items[0].id, items[1].id)
    with pytest.raises(InputError):
        compare_stored_bow(facade, items[0].id, 999999)
    app.text_input(key="telegram_search").set_value("هیچ_خبر_مصنوعی_اینجا_نیست").run()
    assert not app.exception and app.button(key="compare_stored").disabled
    assert all(not model.compare_batch.called for model in models)
