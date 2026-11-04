"""Production-path transactions with synthetic API fixtures and isolated SQLite."""

import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from news_similarity import cli
from news_similarity.collectors.bale import BaleBotCollector
from news_similarity.collectors.bot_api import (
    BotCollectionConfig,
    ProductionBotClient,
    bot_lock,
)
from news_similarity.collectors.telegram_bot import TelegramBotCollector
from news_similarity.database.bot_storage import BotCheckpoint, BotStorage
from news_similarity.database.repository import NewsRepository
from news_similarity.integrations.bot_probe import ProbeError
from news_similarity.services.bot_collection import (
    BotCollectionService,
    collection_status,
)
from news_similarity.ui.services.ui_facade import UiConfig, UiFacade

TOKEN = "123456789:" + "a" * 35
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/production_bot_updates.json").read_text(
        encoding="utf-8"
    )
)


class FakeAPI:
    def __init__(self, platform, pending):
        self.platform = platform
        self.pending = copy.deepcopy(pending)
        self.calls, self.polls = [], []
        self.webhook, self.lose_ack_response, self.before_ack = "", False, None

    def call(self, method, parameters, timeout):
        self.calls.append((method, parameters))
        assert 0 < timeout <= 8
        if method == "getMe":
            return {"id": 123, "is_bot": True}
        if method == "getWebhookInfo":
            return {"url": self.webhook}
        if method == "getChat":
            return {"id": parameters["chat_id"], "type": "channel"}
        assert method == "getChatMember" and self.platform == "telegram"
        return {"status": "administrator", "user": {"id": 123}}

    def poll(self, limit, timeout, request_timeout, *, offset=None):
        assert 0 < request_timeout <= 25 and 0 <= timeout <= 20
        self.polls.append({"offset": offset, "limit": limit})
        if offset is not None:
            if self.before_ack:
                self.before_ack(offset)
            self.pending = [u for u in self.pending if u["update_id"] >= offset]
            if self.lose_ack_response:
                raise ProbeError("Simulated response loss after remote application")
        return copy.deepcopy(self.pending[:limit])


def setup(tmp_path, platform="bale", updates=None, limit=30):
    path = tmp_path / "archive.db"
    repository = NewsRepository(f"sqlite:///{path.as_posix()}")
    channel = "-100123" if platform == "telegram" else "5606750428"
    config = BotCollectionConfig(
        platform, TOKEN, frozenset({channel}), limit=limit, lock_dir=tmp_path / "locks"
    )
    client = FakeAPI(platform, FIXTURE[platform] if updates is None else updates)
    collector = (TelegramBotCollector if platform == "telegram" else BaleBotCollector)(
        config, client
    )
    return repository, collector, client


def collect(repository, collector, *, ack=False):
    return BotCollectionService(repository, collector).collect(
        exclusive_test_bot=True, acknowledge_stored=ack
    )


def checkpoint(repository):
    with Session(repository.engine) as session:
        return session.scalar(select(BotCheckpoint))


def body(update, platform="bale"):
    return update["channel_post" if platform == "telegram" else "message"]


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_authorized_channel_text_caption_and_atomic_checkpoint_default_no_ack(
    tmp_path, platform
):
    repo, collector, client = setup(tmp_path, platform)
    result = collect(repo, collector)
    assert result["status"] == "STORED" and result["inserted"] == 2
    assert result["next_offset"] == 3 and not result["acknowledged"]
    assert [p["offset"] for p in client.polls] == [None]
    news = repo.recent_news()
    assert news[1].text == body(FIXTURE[platform][0], platform)["text"]
    assert news[0].text == "زیرنویس مصنوعی فارسی"
    assert all(n.url is None and n.published_at.tzinfo is not None for n in news)
    row = checkpoint(repo)
    assert row.next_offset == 3 and len(json.loads(row.state)["inbox"]) == 2
    assert set(inspect(repo.engine).get_table_names()) == {
        "news",
        "sources",
        "bot_checkpoints",
    }
    assert not any(
        method in {"deleteWebhook", "setWebhook"} for method, _ in client.calls
    )
    repo.close()


def test_restart_duplicate_updates_and_identical_text_with_different_message_ids(
    tmp_path,
):
    updates = copy.deepcopy(FIXTURE["bale"])
    body(updates[1]).pop("caption")
    body(updates[1])["text"] = body(updates[0])["text"]
    repo, collector, client = setup(tmp_path, updates=updates)
    assert collect(repo, collector)["inserted"] == 2
    database_url = str(repo.engine.url)
    repo.close()
    repo = NewsRepository(database_url)
    result = collect(repo, collector)
    assert result["inserted"] == 0 and result["duplicates"] == 2
    assert repo.count_news() == 2 and len(repo.list_sources()) == 1
    assert checkpoint(repo).next_offset == 3
    repo.close()


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_acknowledges_only_committed_news_and_journals_fresh_returned_update(
    tmp_path, platform
):
    repo, collector, client = setup(tmp_path, platform, limit=1)

    def assert_durable(offset):
        reopened = NewsRepository(str(repo.engine.url))
        assert reopened.count_news() == 1
        row = checkpoint(reopened)
        assert (
            row.next_offset == offset and json.loads(row.state)["ack_intent"] == offset
        )
        reopened.close()

    client.before_ack = assert_durable
    result = collect(repo, collector, ack=True)
    assert result["acknowledged"] and result["acknowledged_offset"] == 2
    assert client.polls == [{"offset": None, "limit": 1}, {"offset": 2, "limit": 1}]
    state = json.loads(checkpoint(repo).state)
    assert state["acknowledged_offset"] == 2
    assert state["inbox"][0]["id"] == 2 and state["inbox"][0]["outcome"] == "pending"
    assert (
        repo.count_news() == 1
    )  # No acknowledgement/processing of the fresh response.
    client.before_ack = None
    result = collect(repo, collector)
    assert result["inserted"] == 1 and repo.count_news() == 2
    assert client.polls[-1]["offset"] is None
    repo.close()


@pytest.mark.parametrize(
    "kind", ["unauthorized", "service", "unknown", "edit", "malformed"]
)
def test_blocked_events_are_journaled_not_news_and_no_checkpoint_leap(tmp_path, kind):
    bad = copy.deepcopy(FIXTURE["bale"][0])
    if kind == "unauthorized":
        body(bad)["chat"].update(id=987654321, type="private")
    elif kind == "service":
        body(bad).pop("text")
        body(bad).update(
            message_id=0,
            new_chat_members=[{"id": 9, "is_bot": True, "first_name": "مصنوعی"}],
        )
    elif kind == "unknown":
        bad = {"update_id": 1, "callback_query": {"data": "private"}}
    elif kind == "edit":
        bad["edited_message"] = bad.pop("message")
    else:
        body(bad)["text"] = 123
    repo, collector, client = setup(tmp_path, updates=[bad, FIXTURE["bale"][1]])
    result = collect(repo, collector, ack=True)
    assert result["status"] == "BLOCKED" and not result["acknowledged"]
    assert result["next_offset"] is None and result["blocked_updates"] == 1
    assert repo.count_news() == 1
    assert len(client.polls) == 1 and client.polls[0]["offset"] is None
    saved = json.loads(checkpoint(repo).state)
    assert saved["inbox"][0]["raw"] == bad
    assert saved["inbox"][0]["outcome"].startswith("blocked_")
    assert "private" not in json.dumps(BotStorage(repo).status())
    repo.close()


def test_partial_safe_prefix_can_be_confirmed_without_skipping_blocker(tmp_path):
    updates = copy.deepcopy(FIXTURE["bale"])
    body(updates[1])["chat"]["id"] = 999
    later = copy.deepcopy(FIXTURE["bale"][0])
    later["update_id"], body(later)["message_id"] = 3, 23
    repo, collector, client = setup(tmp_path, updates=[*updates, later])
    result = collect(repo, collector, ack=True)
    assert result["acknowledged"] and result["acknowledged_offset"] == 2
    assert result["status"] == "BLOCKED" and result["next_offset"] is None
    assert [u["update_id"] for u in client.pending] == [2, 3]
    assert repo.count_news() == 2
    repo.close()


def test_db_failure_rolls_back_news_sources_and_checkpoint_without_ack(
    tmp_path, monkeypatch
):
    repo, collector, client = setup(tmp_path)
    service = BotCollectionService(repo, collector)
    original = service.storage._save_item
    count = 0

    def fail_second(session, item):
        nonlocal count
        count += 1
        if count == 2:
            raise OperationalError("private payload", {}, Exception(TOKEN))
        return original(session, item)

    monkeypatch.setattr(service.storage, "_save_item", fail_second)
    result = service.collect(exclusive_test_bot=True, acknowledge_stored=True)
    assert result["status"] == "ERROR" and not result["acknowledged"]
    assert (
        repo.count_news() == 0
        and repo.list_sources() == []
        and checkpoint(repo) is None
    )
    assert len(client.polls) == 1 and TOKEN not in json.dumps(result)
    repo.close()


def test_unknown_ack_result_survives_restart_and_only_explicit_retry_confirms(tmp_path):
    repo, collector, client = setup(tmp_path, updates=FIXTURE["bale"][:1])
    client.lose_ack_response = True
    result = collect(repo, collector, ack=True)
    assert result["status"] == "ACK_UNKNOWN" and result["acknowledged"] is None
    assert (
        repo.count_news() == 1 and json.loads(checkpoint(repo).state)["ack_intent"] == 2
    )
    repo.close()
    repo = NewsRepository(f"sqlite:///{(tmp_path / 'archive.db').as_posix()}")
    result = collect(repo, collector)
    assert result["status"] == "ACK_UNKNOWN" and client.polls[-1]["offset"] is None
    client.lose_ack_response = False
    result = collect(repo, collector, ack=True)
    assert result["status"] == "ACKNOWLEDGED" and result["acknowledged"]
    assert repo.count_news() == 1 and json.loads(checkpoint(repo).state)["inbox"] == []
    repo.close()


def test_failure_journaling_ack_response_keeps_old_durable_intent(
    tmp_path, monkeypatch
):
    repo, collector, client = setup(tmp_path, updates=FIXTURE["bale"][:1])
    service = BotCollectionService(repo, collector)
    original = service.storage.ingest

    def fail_after_ack(*args, **kwargs):
        if kwargs.get("acknowledged_offset") is not None:
            raise OperationalError("disk", {}, Exception("disk"))
        return original(*args, **kwargs)

    monkeypatch.setattr(service.storage, "ingest", fail_after_ack)
    result = service.collect(exclusive_test_bot=True, acknowledge_stored=True)
    assert result["status"] == "ACK_UNKNOWN" and repo.count_news() == 1
    assert json.loads(checkpoint(repo).state)["ack_intent"] == 2
    repo.close()


@pytest.mark.parametrize("variant", ["gap", "reverse", "missing_id", "conflicting_id"])
def test_unsafe_update_order_or_ids_hold_all_advancement(tmp_path, variant):
    updates = copy.deepcopy(FIXTURE["bale"])
    if variant == "gap":
        updates[1]["update_id"] = 3
    elif variant == "reverse":
        updates.reverse()
    elif variant == "missing_id":
        del updates[0]["update_id"]
    else:
        updates[1]["update_id"] = 1
    repo, collector, client = setup(tmp_path, updates=updates)
    result = collect(repo, collector, ack=True)
    assert result["next_offset"] is None and not result["acknowledged"]
    assert len(client.polls) == 1
    assert len(json.loads(checkpoint(repo).state)["inbox"]) == 2
    repo.close()


def test_duplicate_update_and_message_identity_conflict_are_explicit(tmp_path):
    update = FIXTURE["bale"][0]
    repo, collector, client = setup(tmp_path, updates=[update, update])
    result = collect(repo, collector)
    assert result["inserted"] == 1 and result["duplicate_updates"] == 1
    changed = copy.deepcopy(update)
    changed["update_id"] = 2
    body(changed)["text"] = "اصلاح با شناسهٔ پیام قبلی"
    client.pending = [changed]
    result = collect(repo, collector)
    assert result["blocked_updates"] == 1 and repo.count_news() == 1
    assert repo.recent_news()[0].text == body(update)["text"]
    repo.close()


def test_non_text_is_an_explicit_safe_skip_but_service_is_not(tmp_path):
    update = copy.deepcopy(FIXTURE["bale"][1])
    body(update).pop("caption")
    repo, collector, client = setup(tmp_path, updates=[update])
    result = collect(repo, collector, ack=True)
    assert result["skipped"] == 1 and result["acknowledged"] and repo.count_news() == 0
    repo.close()


@pytest.mark.parametrize(
    "variant", ["unknown_service", "unknown_with_text", "empty", "bad_photo"]
)
def test_unrecognized_textless_or_malformed_media_never_becomes_a_safe_skip(
    tmp_path, variant
):
    update = copy.deepcopy(FIXTURE["bale"][0])
    if variant != "unknown_with_text":
        body(update).pop("text")
    if variant in {"unknown_service", "unknown_with_text"}:
        body(update)["future_service_event"] = {"private": "never discarded"}
    elif variant == "bad_photo":
        body(update)["photo"] = []
    repo, collector, client = setup(tmp_path, updates=[update])
    result = collect(repo, collector, ack=True)
    assert result["status"] == "BLOCKED" and not result["acknowledged"]
    assert result["next_offset"] is None and result["skipped"] == 0
    assert repo.count_news() == 0 and len(client.polls) == 1
    assert json.loads(checkpoint(repo).state)["inbox"][0]["raw"] == update
    repo.close()


def test_local_lock_prevents_another_collector_polling_and_releases(tmp_path):
    repo, collector, client = setup(tmp_path)
    with bot_lock("bale", 123, collector.config.lock_dir):
        result = collect(repo, collector)
        assert result["status"] == "BLOCKED" and not client.polls
    assert collect(repo, collector)["inserted"] == 2
    repo.close()


def test_webhook_and_exclusive_assertion_fail_without_polling(tmp_path):
    repo, collector, client = setup(tmp_path)
    assert BotCollectionService(repo, collector).collect()["status"] == "BLOCKED"
    assert not client.calls
    client.webhook = "https://private.example/secret"
    result = collect(repo, collector)
    assert result["status"] == "BLOCKED" and not client.polls
    assert "secret" not in json.dumps(result)
    repo.close()


def test_legacy_database_status_and_ui_remain_read_only(tmp_path):
    path = tmp_path / "legacy.db"
    repo = NewsRepository(f"sqlite:///{path.as_posix()}")
    repo.initialize()
    repo.close()
    before = path.read_bytes()
    assert collection_status(f"sqlite:///{path.as_posix()}") == []
    facade = UiFacade(UiConfig(tmp_path, f"sqlite:///{path.as_posix()}", tmp_path))
    assert facade.collection_status() == []
    assert path.read_bytes() == before
    assert collection_status(f"sqlite:///{(tmp_path / 'missing.db').as_posix()}") == []
    assert not (tmp_path / "missing.db").exists()


def test_ui_reads_collected_platform_original_text_and_comparison_candidates(tmp_path):
    repo, collector, client = setup(tmp_path)
    collect(repo, collector)
    other = copy.deepcopy(FIXTURE["bale"][0])
    body(other)["chat"]["id"] = 5606750429
    other_config = BotCollectionConfig(
        "bale", TOKEN, frozenset({"5606750429"}), lock_dir=tmp_path / "locks"
    )
    # Different bot/account, same SQLite source/news schema.
    api = FakeAPI("bale", [other])
    api.call = lambda method, parameters, timeout: (
        {"id": 456, "is_bot": True}
        if method == "getMe"
        else {"url": ""}
        if method == "getWebhookInfo"
        else {"id": parameters["chat_id"], "type": "channel"}
    )
    collect(repo, BaleBotCollector(other_config, api))
    facade = UiFacade(UiConfig(tmp_path, str(repo.engine.url), tmp_path))
    assert len(facade.sources()) == 2 and len(facade.browse()) == 3
    assert all(n.platform == "bale" and n.url is None for n in facade.browse())
    assert all(row["evidence_origin"] == "mocked" for row in facade.collection_status())
    assert len(repo.browse_news(exclude_source_id=repo.list_sources()[0].id)) == 1
    repo.close()


@pytest.mark.parametrize("command", ["collect-telegram-bot", "collect-bale"])
def test_cli_missing_credentials_does_not_create_database(
    tmp_path, monkeypatch, capsys, command
):
    monkeypatch.chdir(tmp_path)
    for key in ("TELEGRAM_BOT_TOKEN", "BALE_BOT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert cli.main([command, "--exclusive-test-bot"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert not (tmp_path / "data").exists()


def test_cli_collect_and_collection_status_in_isolated_database(
    tmp_path, monkeypatch, capsys
):
    repo, collector, client = setup(tmp_path)
    environment = tmp_path / ".env"
    environment.write_text(f"DATABASE_URL={repo.engine.url}\n", encoding="utf-8")
    monkeypatch.setattr(
        BotCollectionConfig, "load", lambda *args, **kwargs: collector.config
    )
    monkeypatch.setattr(
        "news_similarity.collectors.bale.BaleBotCollector", lambda cfg: collector
    )
    assert (
        cli.main(
            ["--env-file", str(environment), "collect-bale", "--exclusive-test-bot"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["inserted"] == 2 and not report["acknowledged"]
    digest = hashlib.sha256(Path(repo.engine.url.database).read_bytes()).hexdigest()
    assert cli.main(["--env-file", str(environment), "collection-status"]) == 0
    status = json.loads(capsys.readouterr().out)["collectors"][0]
    assert status["pending_updates"] == 2 and status["next_offset"] == 3
    assert "bot_id" not in status and TOKEN not in json.dumps(report)
    assert (
        hashlib.sha256(Path(repo.engine.url.database).read_bytes()).hexdigest()
        == digest
    )
    repo.close()


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_production_transport_uses_exact_provider_and_validated_offset(platform):
    config = BotCollectionConfig(platform, TOKEN, frozenset({"1001"}))
    client = ProductionBotClient(config)
    client._opener = Mock()
    client._opener.open.return_value = io.BytesIO(b'{"ok":true,"result":[]}')
    assert client.poll(1, 0, 8, offset=7) == []
    request = client._opener.open.call_args.args[0]
    expected = "api.telegram.org" if platform == "telegram" else "tapi.bale.ai"
    assert request.full_url == f"https://{expected}/bot{TOKEN}/getUpdates"
    assert json.loads(request.data) == {"limit": 1, "timeout": 0, "offset": 7}
    with pytest.raises(ValueError):
        client.poll(1, 0, 8, offset=-1)


def test_both_platforms_share_existing_archive_and_feed_cross_platform_ranking(
    tmp_path,
):
    repo, telegram, _ = setup(tmp_path, "telegram")
    assert collect(repo, telegram)["inserted"] == 2
    bale_repo, bale, _ = setup(tmp_path, "bale")
    assert collect(bale_repo, bale)["inserted"] == 2
    assert repo.count_news() == 4
    assert {source.platform for source in repo.list_sources()} == {"telegram", "bale"}
    assert len(BotStorage(repo).status()) == 2
    model = Mock()
    model.rank.return_value = [
        SimpleNamespace(index=0, result=Mock(to_dict=lambda: {"decision": "uncertain"}))
    ]
    facade = UiFacade(
        UiConfig(tmp_path, str(repo.engine.url), tmp_path), model_provider=lambda: model
    )
    query = next(news for news in facade.browse() if news.platform == "telegram")
    ranked = facade.rank(query.id, platform="bale", top_k=1)
    assert len(ranked) == 1 and ranked[0].news.platform == "bale"
    assert len(model.rank.call_args.args[1]) == 2
    repo.close()
    bale_repo.close()


def test_scope_changes_and_confirmed_cursor_regression_do_not_advance(tmp_path):
    repo, collector, client = setup(tmp_path, updates=FIXTURE["bale"][:1])
    assert collect(repo, collector, ack=True)["acknowledged"]
    client.pending = copy.deepcopy(FIXTURE["bale"][:1])
    result = collect(repo, collector, ack=True)
    assert result["status"] == "BLOCKED" and not result["acknowledged"]
    assert (
        BotStorage(repo).status()[0]["blocked"][0]["reason"]
        == "blocked_cursor_regression"
    )
    changed = BotCollectionConfig(
        "bale", TOKEN, frozenset({"999"}), lock_dir=collector.config.lock_dir
    )
    result = collect(repo, BaleBotCollector(changed, client), ack=True)
    assert result["status"] == "BLOCKED" and not result["acknowledged"]
    assert repo.count_news() == 1
    repo.close()


@pytest.mark.parametrize("variant", ["not_a_list", "too_many", "network"])
def test_provider_failure_or_invalid_batch_never_acknowledges(tmp_path, variant):
    repo, collector, client = setup(tmp_path)
    if variant == "network":
        client.poll = Mock(side_effect=ProbeError("API connection failed safely."))
    else:
        response = {} if variant == "not_a_list" else [FIXTURE["bale"][0]] * 31
        client.poll = Mock(return_value=response)
    result = collect(repo, collector, ack=True)
    assert result["status"] == "BLOCKED" and not result["acknowledged"]
    assert client.poll.call_count == 1 and repo.count_news() == 0
    repo.close()


def test_invalid_ack_response_is_durably_blocked_and_reported_unknown(tmp_path):
    repo, collector, client = setup(tmp_path, updates=FIXTURE["bale"][:1])
    first = client.poll

    def wrong_ack(*args, **kwargs):
        if kwargs.get("offset") is not None:
            return copy.deepcopy(FIXTURE["bale"][:1])  # Below the requested boundary.
        return first(*args, **kwargs)

    client.poll = wrong_ack
    result = collect(repo, collector, ack=True)
    assert result["status"] == "ACK_UNKNOWN" and result["acknowledged"] is None
    assert (
        repo.count_news() == 1 and json.loads(checkpoint(repo).state)["ack_intent"] == 2
    )
    repo.close()


def test_checkpoint_intent_write_failure_prevents_offset_request(tmp_path, monkeypatch):
    repo, collector, client = setup(tmp_path)
    service = BotCollectionService(repo, collector)
    monkeypatch.setattr(
        service.storage,
        "mark",
        Mock(side_effect=OperationalError("disk", {}, Exception())),
    )
    result = service.collect(exclusive_test_bot=True, acknowledge_stored=True)
    assert result["status"] == "ERROR" and not result["acknowledged"]
    assert repo.count_news() == 2 and client.polls == [{"offset": None, "limit": 30}]
    repo.close()


def test_private_urls_and_wrong_provider_envelopes_are_not_fabricated_or_accepted(
    tmp_path,
):
    repo, bale, _ = setup(tmp_path, "bale")
    assert bale.classify(FIXTURE["telegram"][0])[0] == "blocked_unsupported"
    repo.close()
    repo, telegram, _ = setup(tmp_path, "telegram")
    update = copy.deepcopy(FIXTURE["telegram"][0])
    body(update, "telegram")["chat"]["username"] = "synthetic_news"
    assert telegram.classify(update)[1].url == "https://t.me/synthetic_news/21"
    assert telegram.classify(FIXTURE["telegram"][0])[1].url is None
    repo.close()


@pytest.mark.parametrize(
    "overrides",
    [{"limit": 101}, {"duration": 0}, {"poll_seconds": 21}, {"token": "invalid"}],
)
def test_production_configuration_bounds(overrides):
    values = {"platform": "bale", "token": TOKEN, "authorized_ids": frozenset({"1001"})}
    with pytest.raises(ProbeError):
        BotCollectionConfig(**(values | overrides))


def test_streamlit_source_status_reads_real_archive_schema_without_network(
    tmp_path, monkeypatch
):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from news_similarity.ui import runtime

    repo, collector, _ = setup(tmp_path)
    collect(repo, collector)
    facade = UiFacade(UiConfig(tmp_path, str(repo.engine.url), tmp_path))
    monkeypatch.setattr(runtime, "get_facade", lambda: facade)
    app_path = Path(__file__).resolve().parents[1] / "src/news_similarity/ui/app.py"
    app = AppTest.from_file(app_path, default_timeout=15).run()
    app.switch_page("pages/archive.py").run()
    assert not app.exception
    assert any("بدون تأیید صف" in item.value for item in app.markdown)
    assert any("دادهٔ آزمایشی" in item.value for item in app.caption)
    assert "بله" in app.dataframe[0].value["پلتفرم"].tolist()
    repo.close()
