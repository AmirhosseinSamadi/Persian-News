import copy
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from news_similarity.integrations.bot_parsing import parse_updates
from news_similarity.integrations.bot_probe import (
    HttpBotClient,
    ProbeConfig,
    ProbeError,
    _NoRedirect,
    live_probe,
    preview_updates,
)
from news_similarity.integrations.probe_cli import run_cli, sanitized_json

TOKEN = "123456789:" + "a" * 35  # Deliberately fictional; never used on the network.
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(platform):
    return json.loads(
        (FIXTURES / f"{platform}_bot_updates.json").read_text(encoding="utf-8")
    )


def config(platform="telegram", **overrides):
    values = {
        "platform": platform,
        "token": TOKEN,
        "authorized_ids": frozenset({"-100123"} if platform == "telegram" else {"345"}),
    }
    return ProbeConfig(**(values | overrides))


class FakeClient:
    origin = "mock"

    def __init__(
        self, platform="telegram", updates=None, webhook="", member="administrator"
    ):
        self.platform, self.updates = platform, updates or []
        self.webhook, self.member = webhook, member
        self.calls = []

    @property
    def requests(self):
        return len(self.calls)

    def call(self, method, parameters, timeout):
        self.calls.append((method, parameters, timeout))
        return {
            "getMe": {"id": 123, "is_bot": True},
            "getWebhookInfo": {"url": self.webhook},
            "getChat": {
                "id": -100123 if self.platform == "telegram" else 345,
                "type": "channel",
            },
            "getChatMember": {"status": self.member, "user": {"id": 123}},
            "getUpdates": self.updates,
        }[method]


@pytest.fixture(autouse=True)
def no_bot_environment(monkeypatch):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_CHANNEL_IDS",
        "BALE_BOT_TOKEN",
        "BALE_BOT_CHAT_IDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_telegram_preserves_unicode_metadata_edits_and_per_update_deduplication():
    document = fixture("telegram")
    result = parse_updates("telegram", document["result"], frozenset({"-100123"}))
    assert len(result.records) == 3
    first, edited, caption = result.records
    assert first.news.text == document["result"][0]["channel_post"]["text"]
    assert "نمی‌رود" in first.news.text and first.news.text.startswith("  ")
    assert first.news.url == "https://t.me/synthetic_news/7"
    assert first.news.channel_id == "-100123"
    assert first.news.published_at == datetime.fromtimestamp(1793264400, UTC)
    assert edited.news.message_id == first.news.message_id
    assert edited.edited_at == datetime.fromtimestamp(1793264460, UTC)
    assert edited.news.url is None
    assert caption.body_text is None
    assert caption.news.text == caption.caption
    assert result.next_offset_candidate == 13
    assert [item["status"] for item in result.dispositions] == [
        "accepted",
        "duplicate",
        "accepted",
        "accepted",
    ]


def test_bale_dispatch_is_not_assumed_to_use_telegram_channel_keys():
    document = fixture("bale")
    result = parse_updates("bale", document["result"], frozenset({"345"}))
    assert len(result.records) == 3
    assert result.records[0].news.text == document["result"][0]["message"]["text"]
    assert all(record.news.platform == "bale" for record in result.records)
    assert all(
        record.chat_type == "private" and record.news.url is None
        for record in result.records
    )
    assert result.records[1].event_type == "edited_message"
    assert result.records[0].news.channel_name is None
    undocumented = {
        "update_id": 3,
        "channel_post": {
            "chat": {"id": 345, "type": "channel"},
            "message_id": 3,
            "date": 1,
            "text": "مصنوعی",
        },
    }
    rejected = parse_updates("bale", [undocumented], frozenset({"345"}))
    assert not rejected.records
    assert rejected.dispositions[0]["status"] == "unsupported_update"
    assert rejected.next_offset_candidate is None


def test_bale_channel_shaped_documented_message_is_only_an_offline_candidate():
    update = copy.deepcopy(fixture("bale")["result"][0])
    update["message"]["chat"].update(type="channel", username="synthetic_news")
    report = preview_updates(config("bale"), [update])
    assert report["records"][0]["chat_type"] == "channel"
    assert report["records"][0]["news"]["url"] is None
    assert report["status"] == "DOCUMENTED_ONLY" and not report["live_verified"]


@pytest.mark.parametrize(
    "extra",
    [
        {"update_id": 12, "callback_query": {"data": "private unrelated content"}},
        {
            "update_id": 12,
            "message": {
                "chat": {"id": 999, "type": "private"},
                "text": "private unrelated content",
            },
        },
        {
            "update_id": 12,
            "channel_post": {
                "chat": {"id": -100999, "type": "channel"},
                "text": "private unrelated content",
            },
        },
    ],
)
def test_unrelated_or_unsupported_updates_hold_the_cursor_and_hide_payload(extra):
    updates = [fixture("telegram")["result"][0], extra]
    report = preview_updates(config(), updates)
    assert len(report["records"]) == 1
    assert report["next_offset_candidate"] is None
    assert report["requested_offset"] is None and not report["acknowledged_by_probe"]
    assert "private unrelated content" not in json.dumps(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("message_id", 0),
        ("message_id", True),
        ("date", "now"),
        ("date", 10**40),
        ("text", 12),
        ("text", "\ud800"),
        ("chat", None),
    ],
)
def test_malformed_messages_are_safe_and_never_advance_offset(field, value):
    update = copy.deepcopy(fixture("telegram")["result"][0])
    update["channel_post"][field] = value
    parsed = parse_updates("telegram", [update], frozenset({"-100123"}))
    assert not parsed.records
    assert parsed.next_offset_candidate is None


@pytest.mark.parametrize(
    "update", [{}, {"update_id": True}, None, "bad", {"update_id": -1}]
)
def test_invalid_update_ids_are_not_acknowledged(update):
    parsed = parse_updates("telegram", [update], frozenset({"-100123"}))
    assert not parsed.records and parsed.next_offset_candidate is None


def test_empty_media_missing_optional_edit_date_and_changed_duplicate_ids():
    update = copy.deepcopy(fixture("telegram")["result"][0])
    del update["channel_post"]["text"]
    update["channel_post"]["edit_date"] = None
    assert not parse_updates("telegram", [update], frozenset({"-100123"})).records
    update["channel_post"]["caption"] = "زیرنویس"
    assert (
        parse_updates("telegram", [update], frozenset({"-100123"})).records[0].edited_at
        is None
    )
    changed = copy.deepcopy(update)
    changed["channel_post"]["caption"] = "متن متفاوت با همان update_id"
    parsed = parse_updates("telegram", [update, changed], frozenset({"-100123"}))
    assert parsed.next_offset_candidate is None
    assert parsed.dispositions[-1]["status"] == "inconsistent_duplicate_id"


@pytest.mark.parametrize(
    "overrides",
    [
        {"token": "secret"},
        {"token": 123},
        {"authorized_ids": frozenset({"@public_channel"})},
        {"duration": 0},
        {"duration": 61},
        {"poll_seconds": 21},
        {"limit": 101},
        {"limit": True},
        {"authorized_ids": frozenset(str(x) for x in range(6))},
    ],
)
def test_configuration_validation_never_echoes_credentials(overrides):
    with pytest.raises(ProbeError) as caught:
        config(**overrides)
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(config())


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_live_missing_credentials_or_exclusive_assertion_never_calls_network(platform):
    fake = Mock()
    report = live_probe(ProbeConfig(platform), client=fake, exclusive_test_bot=True)
    assert report["status"] == "BLOCKED" and report["network_requests"] == 0
    report = live_probe(config(platform), client=fake)
    assert report["status"] == "BLOCKED"
    fake.call.assert_not_called()


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_mocked_live_workflow_never_claims_verification_or_changes_polling(platform):
    updates = fixture(platform)["result"]
    fake = FakeClient(platform, updates)
    fake.origin = "live_http"  # A test double cannot self-authorize live evidence.
    report = live_probe(config(platform), client=fake, exclusive_test_bot=True)
    assert report["status"] == "DOCUMENTED_ONLY"
    assert report["evidence_origin"] == "injected_mock"
    assert not report["live_verified"] and not report["authentication_verified"]
    assert report["network_requests"] == 0
    assert len([method for method, _, _ in fake.calls if method == "getUpdates"]) == 1
    poll = next(params for method, params, _ in fake.calls if method == "getUpdates")
    assert set(poll) == {"limit", "timeout"}
    assert not any(
        method in {"deleteWebhook", "setWebhook", "sendMessage"}
        for method, _, _ in fake.calls
    )
    assert all(0 < timeout <= 30 for _, _, timeout in fake.calls)


def test_existing_webhook_is_preserved_and_polling_stops():
    fake = FakeClient(webhook="https://example.org/private-hook-token")
    report = live_probe(config(), client=fake, exclusive_test_bot=True)
    assert report["status"] == "BLOCKED"
    assert "webhook is active" in report["reason"]
    assert [method for method, _, _ in fake.calls] == ["getMe", "getWebhookInfo"]
    assert "private-hook-token" not in json.dumps(report)


def test_membership_and_deadline_fail_closed_without_polling():
    fake = FakeClient(member="left")
    report = live_probe(config(), client=fake, exclusive_test_bot=True)
    assert report["status"] == "BLOCKED"
    assert not any(method == "getUpdates" for method, _, _ in fake.calls)
    ticks = iter([0, 31])
    fake = FakeClient()
    report = live_probe(
        config(), client=fake, exclusive_test_bot=True, clock=lambda: next(ticks)
    )
    assert report["status"] == "BLOCKED" and not fake.calls


def test_membership_response_must_identify_the_authenticated_bot():
    fake = FakeClient()
    original = fake.call

    def call(method, parameters, timeout):
        result = original(method, parameters, timeout)
        if method == "getChatMember":
            result["user"]["id"] = 999
        return result

    fake.call = call
    report = live_probe(config(), client=fake, exclusive_test_bot=True)
    assert report["status"] == "BLOCKED"
    assert not any(method == "getUpdates" for method, _, _ in fake.calls)


class Response(io.BytesIO):
    pass


def test_http_transport_uses_official_https_post_and_rejects_destructive_methods():
    client = HttpBotClient(config())
    opener = Mock()
    opener.open.return_value = Response(b'{"ok":true,"result":[]}')
    client._opener = opener
    assert client.call("getUpdates", {"limit": 20, "timeout": 10}, 10) == []
    request = opener.open.call_args.args[0]
    assert request.full_url == f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"limit": 20, "timeout": 10}
    with pytest.raises(ProbeError):
        client.call("deleteWebhook", {}, 10)
    with pytest.raises(ProbeError):
        client.call("getUpdates", {"offset": 100}, 10)
    with pytest.raises(ProbeError):
        client.call("getUpdates", {"allowed_updates": []}, 10)
    assert opener.open.call_count == 1


def test_http_errors_rate_limits_and_redirects_are_sanitized():
    client = HttpBotClient(config("bale"))
    client._opener = Mock()
    client._opener.open.side_effect = URLError(f"https://tapi.bale.ai/bot{TOKEN}/getMe")
    with pytest.raises(ProbeError) as caught:
        client.call("getMe", {}, 1)
    assert TOKEN not in str(caught.value)
    body = json.dumps({"description": TOKEN, "parameters": {"retry_after": 7}}).encode()
    client._opener.open.side_effect = HTTPError(TOKEN, 429, TOKEN, {}, io.BytesIO(body))
    with pytest.raises(ProbeError, match="Retry after 7") as caught:
        client.call("getMe", {}, 1)
    assert TOKEN not in str(caught.value)
    with pytest.raises(ProbeError, match="redirect"):
        _NoRedirect().redirect_request(
            None, None, 302, "", {}, f"https://evil.example/{TOKEN}"
        )


@pytest.mark.parametrize(
    "body", [b"not JSON", b'{"ok":false,"description":"secret"}', b"[]", b'{"ok":true}']
)
def test_invalid_api_envelopes_fail_without_raw_response(body):
    client = HttpBotClient(config())
    client._opener = Mock()
    client._opener.open.return_value = Response(body)
    with pytest.raises(ProbeError) as caught:
        client.call("getMe", {}, 1)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("platform,chat", [("telegram", "-100123"), ("bale", "345")])
def test_offline_cli_is_explicitly_not_live_and_writes_no_database(
    platform, chat, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert (
        run_cli(
            platform,
            [
                "--offline",
                str(FIXTURES / f"{platform}_bot_updates.json"),
                f"--chat-id={chat}",
            ],
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "DOCUMENTED_ONLY" and report["synthetic"]
    assert not report["live_verified"] and report["network_requests"] == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_dry_run_and_live_missing_environment_are_actionable(
    platform, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert run_cli(platform, []) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert run_cli(platform, ["--live", "--exclusive-test-bot"]) == 2
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0


def test_credentials_stay_out_of_success_errors_and_argparse_output(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_CHANNEL_IDS", "-100123")
    assert run_cli("telegram", []) == 0
    assert TOKEN not in capsys.readouterr().out
    assert TOKEN not in sanitized_json({"body_text": "خبر فارسی " + TOKEN}, TOKEN)
    with pytest.raises(SystemExit):
        run_cli("telegram", ["--token", TOKEN])
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err


def test_malformed_offline_fixture_and_invalid_token_are_safe(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "bad.json"
    path.write_text('{"ok":false}')
    assert run_cli("bale", ["--offline", str(path), "--chat-id=345"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    monkeypatch.setenv("BALE_BOT_TOKEN", "sensitive malformed credential")
    assert run_cli("bale", []) == 2
    output = capsys.readouterr().out
    assert "sensitive malformed credential" not in output
