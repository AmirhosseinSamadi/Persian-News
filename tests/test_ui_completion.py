"""Button-to-storage-to-analysis workflow using synthetic provider responses."""

import copy
import json
import re
from dataclasses import replace
from html import unescape
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
from test_bot_collection import FIXTURE, setup

from news_similarity.collectors.bot_api import bot_lock
from news_similarity.event_comparison import compare_news_features
from news_similarity.hybrid import HybridMatcher
from news_similarity.integrations.bot_probe import ProbeError
from news_similarity.ui.components.analysis_visuals import (
    evidence_spans,
    highlighted_text,
    lexical_spans,
    model_bars,
    score_gauge,
)
from news_similarity.ui.services import collection
from news_similarity.ui.services.ui_facade import UiConfig, UiFacade

APP = Path(__file__).resolve().parents[1] / "src/news_similarity/ui/app.py"


@pytest.fixture
def collection_workspace(tmp_path, monkeypatch):
    repo, bale, bale_api = setup(tmp_path)
    _, telegram, telegram_api = setup(tmp_path, platform="telegram")
    calls = []

    def load(platform, path, **options):
        calls.append((platform, path, options))
        return (bale if platform == "bale" else telegram).config

    monkeypatch.setattr(collection.BotCollectionConfig, "load", load)
    monkeypatch.setattr(collection, "BaleBotCollector", lambda config: bale)
    monkeypatch.setattr(collection, "TelegramBotCollector", lambda config: telegram)
    scorers = [Mock() for _ in range(3)]
    for scorer in scorers:
        scorer.compare_batch.side_effect = lambda pairs: [0.6] * len(pairs)
    matcher = HybridMatcher(*scorers, model_metadata={"origin": "synthetic_ui_test"})
    config = UiConfig(tmp_path, str(repo.engine.url), tmp_path)
    facade = UiFacade(config, model_provider=lambda: matcher)
    from news_similarity.ui import runtime

    monkeypatch.setattr(runtime, "get_facade", lambda: facade)
    yield facade, bale_api, telegram_api, calls, scorers
    repo.close()


def test_explicit_fetch_stores_refreshes_compares_and_does_not_repeat_on_rerun(
    collection_workspace,
):
    facade, bale, telegram, calls, scorers = collection_workspace
    app = AppTest.from_file(APP, default_timeout=20).run()
    assert not app.exception and app.button(key="fetch_news").disabled
    assert not calls and facade.count_news() == 0
    app.checkbox(key="collection_exclusive").check().run()
    assert not calls
    app.button(key="fetch_news").click().run()
    assert not app.exception
    assert facade.count_news() == 4
    assert app.selectbox(key="telegram_news").value is not None
    assert app.selectbox(key="bale_news").value is not None
    for api in (bale, telegram):
        assert api.polls == [{"offset": None, "limit": 30}]
    assert all(
        path == facade.config.bot_env_path(platform) for platform, path, _ in calls
    )
    chosen = app.selectbox(key="telegram_news").value
    app.button(key="compare_stored").click().run()
    assert not app.exception
    result = app.session_state["stored_comparison"]["view"]["result"]
    assert result["combined_ranking_score"] == pytest.approx(0.6)
    assert result["decision"] == "uncertain"
    assert any(e.label == "جزئیات فنی تحلیل" for e in app.expander)
    app.run()
    assert not app.exception and len(calls) == 2
    app.button(key="fetch_news").click().run()
    assert facade.count_news() == 4
    reports = app.session_state["collection_report"]["reports"]
    assert all(r["inserted"] == 0 and r["duplicates"] == 2 for r in reports)
    assert all(not r["acknowledged"] for r in reports)
    assert all(p["offset"] is None for api in (bale, telegram) for p in api.polls)
    app.switch_page("pages/archive.py").run()
    app.switch_page("pages/comparison.py").run()
    assert app.selectbox(key="telegram_news").value == chosen
    assert all(scorer.compare_batch.call_count == 1 for scorer in scorers)
    assert len(calls) == 4


def test_ui_no_updates_and_selection_state(collection_workspace):
    _, bale, telegram, _, _ = collection_workspace
    bale.pending = telegram.pending = []
    app = AppTest.from_file(APP).run()
    app.checkbox(key="collection_exclusive").check().run()
    app.button(key="fetch_news").click().run()
    assert not app.exception and app.button(key="compare_stored").disabled
    assert sum("تازه‌ای برنگشت" in item.value for item in app.info) == 2
    app.run()
    assert len(bale.polls) == len(telegram.polls) == 1


def test_collection_guards_never_open_transport(collection_workspace):
    facade, bale, telegram, calls, _ = collection_workspace
    assert facade.collect_news("bale")["reason"] == "exclusive_required"
    assert facade.collect_news("other", exclusive_bot=True)["reason"] == "configuration"
    demo = replace(facade.config, demo_mode=True)
    assert collection.collect_news(demo, "bale", exclusive_bot=True)["reason"] == "demo"
    assert not calls and not bale.calls and not telegram.calls


def test_missing_credentials_and_errors_are_sanitized(
    collection_workspace, monkeypatch
):
    facade, bale, _, _, _ = collection_workspace

    def failure(*args, **kwargs):
        raise ProbeError("SECRET_TOKEN personal-id message-body")

    monkeypatch.setattr(bale, "call", failure)
    report = facade.collect_news("bale", exclusive_bot=True)
    assert report["status"] == "BLOCKED" and report["reason"] == "unavailable"
    assert "SECRET" not in json.dumps(report)
    monkeypatch.setattr(collection.BotCollectionConfig, "load", failure)
    assert (
        facade.collect_news("telegram", exclusive_bot=True)["reason"] == "configuration"
    )


def test_locked_or_webhook_bot_cannot_poll(collection_workspace):
    facade, bale, _, calls, _ = collection_workspace
    config = collection.BotCollectionConfig.load("bale", "ignored")
    with bot_lock("bale", 123, config.lock_dir):
        report = facade.collect_news("bale", exclusive_bot=True)
    assert report["status"] == "BLOCKED" and not bale.polls
    bale.webhook = "https://example.invalid/webhook"
    assert facade.collect_news("bale", exclusive_bot=True)["status"] == "BLOCKED"
    assert not bale.polls


def test_blocked_updates_are_retained_without_ack(collection_workspace):
    facade, bale, _, _, _ = collection_workspace
    update = copy.deepcopy(FIXTURE["bale"][0])
    update["message"]["chat"]["type"] = "private"
    bale.pending = [update]
    report = facade.collect_news("bale", exclusive_bot=True)
    assert report["blocked_updates"] == 1 and report["reason"] == "blocked"
    assert report["inserted"] == 0 and not report["acknowledged"]
    assert bale.polls[0]["offset"] is None


def test_gauge_and_bars_bind_actual_values_and_preserve_negative_cosine():
    gauge = score_gauge(0.4321, "uncertain")
    assert "۰.۴۳۲۱" in gauge and 'class="score-gauge uncertain"' in gauge
    for invalid in (None, float("nan"), True, 1.5):
        assert "—" in score_gauge(invalid, "uncertain")
    bars = model_bars({"semantic_similarity": -0.5, "word_similarity": 0.25})
    assert "-۰.۵۰۰۰" in bars and "۰.۲۵۰۰" in bars
    assert "left:25.0%;width:25.0%" in bars
    assert bars.count("موجود نیست") == 4  # Visible label and accessible description.


def test_original_evidence_offsets_and_conflict_categories_are_validated():
    first = "در تهران ۱۲ نفر ثبت نام کردند."
    second = "در تهران ۱۳ نفر ثبت نام کردند."
    evidence = compare_news_features(first, second).to_dict()
    spans = evidence_spans(first, evidence, "a")
    assert spans and any(s[2] == "shared" for s in spans)
    assert all(first[s:e] for s, e, *_ in spans)
    filtered = evidence_spans(first, evidence, "a", kinds={"location"})
    assert all(first[s:e] == "تهران" for s, e, *_ in filtered)
    assert evidence_spans("different text", evidence, "a") == []
    # A mismatched or invalid backend span must never highlight unrelated text.
    broken = {
        "matching_features": [
            {
                "feature_type": "location",
                "evidence_a": [{"span": {"start": -1, "end": 4, "text": "تهران"}}],
            }
        ]
    }
    assert evidence_spans(first, broken, "a") == []


def test_highlight_html_preserves_full_text_and_escapes_markup():
    first = 'خبر <script>alert("x")</script> تهران ۱۲ نفر\nحاضر شدند.'
    second = "تهران 12 نفر حاضر شدند."
    spans, _ = lexical_spans(first, second)
    rendered = highlighted_text(first, spans)
    assert "<script>" not in rendered and "ev-lexical" in rendered
    assert unescape(re.sub(r"<[^>]+>", "", rendered)) == first
    assert any(first[s:e] == "۱۲" for s, e, *_ in spans)
    assert lexical_spans("", "") == ([], [])


def test_missing_credentials_without_mock_leave_database_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("BALE_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BALE_BOT_CHAT_IDS", raising=False)
    config = UiConfig(tmp_path, "sqlite:///empty.db", tmp_path)
    (tmp_path / ".env.bot-probes").write_text("", encoding="utf-8")
    report = collection.collect_news(config, "bale", exclusive_bot=True)
    assert report["reason"] == "missing_token" and not (tmp_path / "empty.db").exists()
