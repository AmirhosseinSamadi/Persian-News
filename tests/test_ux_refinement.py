"""Configuration regression and coherent result rendering, with no live API calls."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
from test_bot_collection import FIXTURE, TOKEN, FakeAPI

from news_similarity.collectors.bale import BaleBotCollector
from news_similarity.collectors.bot_api import (
    BotCollectionConfig,
    BotConfigurationError,
)
from news_similarity.collectors.telegram_bot import TelegramBotCollector
from news_similarity.event_comparison import compare_news_features
from news_similarity.ui import runtime
from news_similarity.ui.services import collection
from news_similarity.ui.services.ui_facade import UiConfig, UiFacade

APP = Path(__file__).resolve().parents[1] / "src/news_similarity/ui/app.py"


@pytest.fixture(autouse=True)
def isolated_bot_environment(monkeypatch):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_CHANNEL_IDS",
        "BALE_BOT_TOKEN",
        "BALE_BOT_CHAT_IDS",
        "NEWS_UI_DEMO_MODE",
        "NEWS_UI_BOT_ENV_FILE",
        "NEWS_BOT_LOCK_DIR",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def write_bot_files(root):
    (root / ".env").write_text(
        f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_BOT_CHANNEL_IDS=-100123\n"
        "DATABASE_URL=sqlite:///archive.db\n",
        encoding="utf-8",
    )
    (root / ".env.bot-probes").write_text(
        f"BALE_BOT_TOKEN={TOKEN}\nBALE_BOT_CHAT_IDS=5606750428\n",
        encoding="utf-8",
    )


def test_telegram_ui_original_wrong_file_failure_and_fixed_default(
    tmp_path,
    monkeypatch,
):
    write_bot_files(tmp_path)
    # Reproduce the original UI path: Bale's valid file lacks Telegram fields.
    with pytest.raises(BotConfigurationError) as error:
        BotCollectionConfig.load("telegram", tmp_path / ".env.bot-probes")
    assert error.value.code == "missing_token"
    other = tmp_path / "unrelated-launch-directory"
    other.mkdir()
    monkeypatch.chdir(other)
    config = UiConfig.from_environment(tmp_path, {})
    clients = {p: FakeAPI(p, FIXTURE[p]) for p in ("telegram", "bale")}
    used = {}

    def factory(kind):
        cls = TelegramBotCollector if kind == "telegram" else BaleBotCollector

        def build(bot):
            used[kind] = bot
            return cls(bot, clients[kind])

        return build

    monkeypatch.setattr(collection, "TelegramBotCollector", factory("telegram"))
    monkeypatch.setattr(collection, "BaleBotCollector", factory("bale"))
    facade = UiFacade(config)
    monkeypatch.setattr(runtime, "get_facade", lambda: facade)
    app = AppTest.from_file(APP).run()
    assert not used and not app.exception
    app.checkbox(key="collection_exclusive").check().run()
    app.button(key="fetch_news").click().run()
    assert not app.exception
    reports = app.session_state["collection_report"]["reports"]
    assert all(r["status"] == "STORED" and r["inserted"] == 2 for r in reports)
    assert all(not r["acknowledged"] for r in reports)
    assert used["telegram"].token == used["bale"].token == TOKEN
    assert used["telegram"].lock_dir == tmp_path / ".tmp/bot-locks"
    assert config.bot_env_path("telegram") == tmp_path / ".env"
    assert config.bot_env_path("bale") == tmp_path / ".env.bot-probes"
    assert (tmp_path / "archive.db").is_file()
    assert not (other / "archive.db").exists()
    before = {p: len(c.polls) for p, c in clients.items()}
    app.run()
    assert {p: len(c.polls) for p, c in clients.items()} == before
    assert all(poll["offset"] is None for c in clients.values() for poll in c.polls)


def test_default_ui_root_ignores_launch_directory(tmp_path, monkeypatch):
    from news_similarity.ui.services import ui_facade

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_facade, "dotenv_values", lambda *a, **k: {})
    config = UiConfig.from_environment(environ={})
    expected = Path(ui_facade.__file__).resolve().parents[4]
    assert config.root == expected != tmp_path
    assert config.bot_env_path("telegram") == expected / ".env"


def test_unreadable_main_environment_is_sanitized_in_streamlit(monkeypatch):
    from news_similarity.ui.services import ui_facade

    def unreadable(*args, **kwargs):
        raise PermissionError("secret-text")

    monkeypatch.setattr(ui_facade, "dotenv_values", unreadable)
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert any("فایل تنظیمات برنامه خوانده نشد" in n.value for n in app.error)
    assert "secret-text" not in " ".join(n.value for n in app.error)


def test_explicit_file_override_and_process_precedence(tmp_path, monkeypatch):
    write_bot_files(tmp_path)
    custom = tmp_path / "private" / "bots.env"
    custom.parent.mkdir()
    custom.write_text(
        f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_BOT_CHANNEL_IDS=-100123\n",
        encoding="utf-8",
    )
    config = UiConfig.from_environment(
        tmp_path, {"NEWS_UI_BOT_ENV_FILE": "private/bots.env"}
    )
    assert config.bot_env_path("telegram") == config.bot_env_path("bale") == custom
    absolute = replace(config, bot_env_file=str(custom))
    assert absolute.bot_env_path("telegram") == custom
    different = "987654321:" + "b" * 35
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", different)
    monkeypatch.setenv("TELEGRAM_BOT_CHANNEL_IDS", "-100987")
    environment_before = dict(os.environ)
    loaded = BotCollectionConfig.load("telegram", custom)
    assert loaded.token == different and loaded.authorized_ids == frozenset({"-100987"})
    assert dict(os.environ) == environment_before


@pytest.mark.parametrize(
    "content,code",
    [
        ("", "missing_token"),
        (f"TELEGRAM_BOT_TOKEN={TOKEN}\n", "missing_channels"),
        (
            f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_BOT_CHANNEL_IDS=secret-text\n",
            "invalid_channels",
        ),
        (
            "TELEGRAM_BOT_TOKEN=secret-text\nTELEGRAM_BOT_CHANNEL_IDS=-100123\n",
            "invalid_token",
        ),
        ('TELEGRAM_BOT_TOKEN="secret-text\n', "file_load"),
    ],
)
def test_configuration_failures_are_separate_and_sanitized(
    tmp_path,
    content,
    code,
    caplog,
):
    (tmp_path / ".env").write_text(content, encoding="utf-8")
    config = UiConfig(tmp_path, "sqlite:///must-not-exist.db", tmp_path)
    report = UiFacade(config).collect_news("telegram", exclusive_bot=True)
    assert report["reason"] == code and not report["acknowledged"]
    assert "secret-text" not in json.dumps(report) + caplog.text
    assert TOKEN not in json.dumps(report) + caplog.text
    assert not (tmp_path / "must-not-exist.db").exists()


def test_missing_unreadable_and_invalid_encoding_files(tmp_path, monkeypatch):
    config = UiConfig(tmp_path, "sqlite:///must-not-exist.db", tmp_path)
    facade = UiFacade(config)
    assert facade.collect_news("telegram", exclusive_bot=True)["reason"] == "file_load"
    (tmp_path / ".env").write_bytes(b"\xff\xfeinvalid")
    assert facade.collect_news("telegram", exclusive_bot=True)["reason"] == "file_load"

    def unreadable(*args, **kwargs):
        raise PermissionError("secret-text")

    monkeypatch.setattr(Path, "read_text", unreadable)
    assert facade.collect_news("telegram", exclusive_bot=True)["reason"] == "file_load"


def test_environment_only_configuration_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("BALE_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BALE_BOT_CHAT_IDS", "5606750428,")
    bot = BotCollectionConfig.load("bale", tmp_path / "absent.env")
    assert bot.token == TOKEN and bot.authorized_ids == frozenset({"5606750428"})


def render_result(result):
    return AppTest.from_string(
        "from news_similarity.ui.components.score_display import score_display\n"
        f"score_display({result!r}, key='analysis_result')\n"
    ).run()


@pytest.mark.parametrize(
    "decision,label",
    [
        ("likely_same_event", "یک رویداد"),
        ("likely_different_event", "رویدادهای متفاوت"),
        ("uncertain", "نامطمئن"),
    ],
)
def test_one_result_preserves_decision_without_duplicate_primary_score(decision, label):
    app = render_result(
        {
            "decision": decision,
            "combined_ranking_score": 0.9876,
            "word_similarity": 0.2,
            "character_similarity": 0.3,
            "semantic_similarity": -0.1,
        }
    )
    assert not app.exception
    text = " ".join(n.value for n in [*app.markdown, *app.warning])
    assert label in text
    bodies = "".join(n.value for n in app.get("html"))
    assert bodies.count("۰.۹۸۷۶") == 1 and 'role="meter"' in bodies
    assert "score-gauge" not in bodies and "model-bars" not in bodies
    assert len(app.expander) == 1 and app.expander[0].label == "جزئیات فنی تحلیل"
    assert not app.expander[0].proto.expanded
    assert app.dataframe[0].value["امتیاز خام"].tolist() == [0.2, 0.3, -0.1]
    app.run()
    assert not app.exception


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"decision": "uncertain"},
        {
            "decision": "uncertain",
            "combined_ranking_score": 1.2,
        },
    ],
)
def test_empty_and_unavailable_results_do_not_invent_scores(result):
    app = render_result(result)
    assert not app.exception
    assert any("امتیاز ترکیبی معتبر" in n.value for n in app.caption)
    assert 'role="meter"' not in "".join(n.value for n in app.get("html"))


def test_summary_evidence_is_backend_bound_and_html_safe():
    evidence = compare_news_features(
        "در تهران ۱۲ نفر ثبت نام کردند.", "در تهران ۱۳ نفر ثبت نام کردند."
    ).to_dict()
    evidence["matching_features"][0]["values_a"][0]["value"] = '<img src=x onerror="x">'
    app = render_result(
        {
            "decision": "uncertain",
            "combined_ranking_score": 0.7,
            "event_evidence": evidence,
        }
    )
    assert not app.exception
    body = "".join(n.value for n in app.get("html"))
    assert "finding-summary" in body and "&lt;img" in body and "<img" not in body
    assert (
        len(app.json) == 1
    )  # Complete structured evidence, once in technical details.
