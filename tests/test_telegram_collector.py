from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from telethon import errors, types

from news_similarity.collectors.telegram import (
    TelegramCollector,
    channel_reference,
    message_to_news,
)


def make_channel(username="persian_news"):
    return types.Channel(
        id=1001,
        title="اخبار فارسی",
        photo=types.ChatPhotoEmpty(),
        date=datetime(2026, 1, 1, tzinfo=UTC),
        username=username,
        broadcast=True,
    )


def make_message(message_id=42, text="  خبر فارسی\nبا حفظ نیم‌فاصله  ", **kwargs):
    return types.Message(
        id=message_id,
        peer_id=types.PeerChannel(1001),
        date=datetime(2026, 1, 2, tzinfo=UTC),
        message=text,
        **kwargs,
    )


class FakeClient:
    """Inject scripted history pages and failures without network access."""

    def __init__(self, pages=None, entity=None):
        self.start = AsyncMock()
        self.disconnect = AsyncMock()
        self.get_entity = AsyncMock(return_value=entity or make_channel())
        self.pages = list(pages or [[]])
        self.calls = []

    def iter_messages(self, entity, **kwargs):
        self.calls.append(kwargs)
        page = self.pages.pop(0)

        async def generate():
            for message in page:
                if isinstance(message, Exception):
                    raise message
                yield message

        return generate()


@pytest.mark.parametrize("text", ["", " ", "\n\t"])
def test_empty_messages_are_ignored(text):
    assert message_to_news(make_message(text=text), make_channel()) is None


def test_unsupported_messages_are_ignored():
    empty = types.MessageEmpty(id=3, peer_id=types.PeerChannel(1001))
    assert message_to_news(empty, make_channel()) is None
    service = types.MessageService(
        id=4,
        peer_id=types.PeerChannel(1001),
        date=datetime.now(UTC),
        action=types.MessageActionChannelCreate(title="New channel"),
    )
    assert message_to_news(service, make_channel()) is None


def test_persian_conversion_public_url_and_media_caption():
    message = make_message(media=types.MessageMediaPhoto())
    item = message_to_news(message, make_channel())
    assert item.text == message.message
    assert item.channel_id == "1001"
    assert item.channel_name == "اخبار فارسی"
    assert item.message_id == "42"
    assert item.url == "https://t.me/persian_news/42"
    assert item.published_at.tzinfo == UTC
    assert message_to_news(message, make_channel(None)).url is None


def test_naive_or_missing_timestamp_is_rejected():
    message = make_message()
    message.date = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        message_to_news(message, make_channel())
    message.date = None
    with pytest.raises(ValueError, match="timestamp"):
        message_to_news(message, make_channel())


@pytest.mark.parametrize(
    "value,expected",
    [
        ("@persian_news", "persian_news"),
        ("https://t.me/persian_news/", "persian_news"),
        ("-10012345", -10012345),
    ],
)
def test_channel_reference_formats(value, expected):
    assert channel_reference(value) == expected


async def test_collect_counts_and_disconnects(settings):
    client = FakeClient(
        [
            [
                make_message(),
                make_message(41, ""),
                types.MessageEmpty(id=40, peer_id=types.PeerChannel(1001)),
            ]
        ]
    )
    batch = await TelegramCollector(settings, client=client).collect("@persian_news", 3)
    assert batch.total_fetched == 3
    assert len(batch.items) == 1
    assert batch.skipped == 2
    assert not batch.errors
    assert batch.channel_url == "https://t.me/persian_news"
    client.start.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert client.calls[0]["limit"] == 3


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "bad channel!",
        "https://example.com/news",
        "https://t.me/news/123",
        "https://t.me/+invite",
    ],
)
async def test_invalid_channel_never_connects(settings, reference):
    client = FakeClient()
    batch = await TelegramCollector(settings, client=client).collect(reference, 30)
    assert batch.errors
    assert batch.total_fetched == 0
    client.start.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("private detail"),
        errors.ChannelPrivateError(request=None),
        errors.UsernameNotOccupiedError(request=None),
    ],
)
async def test_unavailable_channel_is_reported_and_disconnects(settings, error):
    client = FakeClient()
    client.get_entity.side_effect = error
    batch = await TelegramCollector(settings, client=client).collect("missing_news", 30)
    assert batch.errors
    assert "private detail" not in str(batch.errors)
    client.disconnect.assert_awaited_once()


async def test_user_target_is_rejected(settings):
    client = FakeClient(entity=types.User(id=123))
    batch = await TelegramCollector(settings, client=client).collect("some_user", 30)
    assert "must be a Telegram channel" in batch.errors[0]
    assert not client.calls


async def test_connection_failure_does_not_disclose_credentials(settings, caplog):
    client = FakeClient()
    client.start.side_effect = OSError("secret code 123456 and API hash " + "a" * 32)
    batch = await TelegramCollector(settings, client=client).collect("persian_news", 30)
    assert "connection" in batch.errors[0]
    assert "123456" not in str(batch.errors) + caplog.text
    assert "a" * 32 not in str(batch.errors) + caplog.text
    client.disconnect.assert_awaited_once()


async def test_entity_flood_wait_retries_after_required_delay(settings):
    client = FakeClient()
    client.get_entity.side_effect = [
        errors.FloodWaitError(None, capture=3),
        make_channel(),
    ]
    sleep = AsyncMock()
    batch = await TelegramCollector(settings, client=client, sleep=sleep).collect(
        "persian_news", 5
    )
    sleep.assert_awaited_once_with(3)
    assert not batch.errors


async def test_history_flood_wait_resumes_without_refetching(settings):
    client = FakeClient(
        [
            [make_message(50), errors.FloodWaitError(None, capture=2)],
            [make_message(49)],
        ]
    )
    sleep = AsyncMock()
    batch = await TelegramCollector(settings, client=client, sleep=sleep).collect(
        "persian_news", 2
    )
    sleep.assert_awaited_once_with(2)
    assert [item.message_id for item in batch.items] == ["50", "49"]
    assert client.calls[1]["offset_id"] == 50
    assert client.calls[1]["limit"] == 1
    assert not batch.errors


async def test_long_flood_wait_reports_partial_batch_without_retry(settings):
    client = FakeClient([[make_message(), errors.FloodWaitError(None, capture=120)]])
    sleep = AsyncMock()
    batch = await TelegramCollector(settings, client=client, sleep=sleep).collect(
        "persian_news", 30
    )
    assert len(batch.items) == 1
    assert batch.total_fetched == 1
    assert "120 seconds" in batch.errors[0]
    sleep.assert_not_awaited()


async def test_repeated_flood_wait_is_bounded(settings):
    flood = errors.FloodWaitError(None, capture=1)
    client = FakeClient([[flood], [flood], [flood]])
    sleep = AsyncMock()
    batch = await TelegramCollector(settings, client=client, sleep=sleep).collect(
        "persian_news", 30
    )
    assert sleep.await_count == 2
    assert batch.errors


async def test_invalid_record_counts_as_skipped_with_error(settings):
    message = make_message()
    message.date = None
    client = FakeClient([[message]])
    batch = await TelegramCollector(settings, client=client).collect("persian_news", 1)
    assert batch.total_fetched == batch.skipped == 1
    assert batch.items == []
    assert "Message 42" in batch.errors[0]


async def test_history_and_disconnect_failures_keep_partial_results(settings):
    client = FakeClient([[make_message(), OSError("unreachable")]])
    client.disconnect.side_effect = OSError("unreachable")
    batch = await TelegramCollector(settings, client=client).collect("persian_news", 5)
    assert len(batch.items) == 1
    assert len(batch.errors) == 2


async def test_nonpositive_limit_is_rejected(settings):
    client = FakeClient()
    with pytest.raises(ValueError, match="positive"):
        await TelegramCollector(settings, client=client).collect("persian_news", 0)
    client.start.assert_not_awaited()


async def test_session_storage_failure_is_reported(settings):
    import sqlite3

    client = FakeClient()
    client.start.side_effect = sqlite3.OperationalError("database is locked")
    batch = await TelegramCollector(settings, client=client).collect("persian_news", 1)
    assert "session storage failed" in batch.errors[0]
    client.disconnect.assert_awaited_once()


async def test_interactive_callbacks_are_hidden_and_greeting_uses_stderr(
    settings, monkeypatch, capsys
):
    from news_similarity.collectors import telegram

    prompts = []

    def hidden_input(prompt):
        prompts.append(prompt)
        return "sensitive-input"

    async def start(**callbacks):
        for callback in callbacks.values():
            assert callback() == "sensitive-input"
        print("Signed in successfully")

    monkeypatch.setattr(telegram, "getpass", hidden_input)
    client = FakeClient()
    client.start.side_effect = start
    batch = await TelegramCollector(settings, client=client).collect("persian_news", 1)
    assert not batch.errors
    assert len(prompts) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "Signed in successfully" in output.err
    assert "sensitive-input" not in output.out + output.err


async def test_collector_service_repository_integration(settings, repository):
    from news_similarity.services.collection import CollectionService

    messages = [make_message(42), make_message(41, ""), make_message(40, "خبر دوم")]
    client = FakeClient([messages, messages])
    service = CollectionService(repository, TelegramCollector(settings, client=client))
    first = await service.collect("persian_news", 3)
    second = await service.collect("https://t.me/persian_news", 3)
    assert (first.total_fetched, first.valid_news_items, first.skipped) == (3, 2, 1)
    assert (first.newly_inserted, first.duplicates) == (2, 0)
    assert (second.newly_inserted, second.duplicates) == (0, 2)
    assert not first.errors + second.errors
    assert repository.count_news() == 2
    assert repository.recent_news()[0].text == "خبر دوم"


@pytest.mark.parametrize(
    "error_type",
    [
        errors.AuthKeyUnregisteredError,
        errors.SessionRevokedError,
        errors.AuthKeyDuplicatedError,
    ],
)
async def test_invalid_or_expired_session_is_reported(settings, error_type, caplog):
    client = FakeClient()
    client.start.side_effect = error_type(request=None)
    batch = await TelegramCollector(settings, client=client).collect("persian_news", 30)
    assert len(batch.errors) == 1
    assert "authentication failed" in batch.errors[0]
    assert batch.total_fetched == 0
    assert batch.channel_id is None
    client.start.assert_awaited_once()
    client.get_entity.assert_not_awaited()
    client.disconnect.assert_awaited_once()
    assert "request=" not in caplog.text


async def test_authentication_flood_wait_stops_without_retry(settings):
    client = FakeClient()
    client.start.side_effect = errors.FloodWaitError(None, capture=90)
    sleep = AsyncMock()
    batch = await TelegramCollector(settings, client=client, sleep=sleep).collect(
        "persian_news", 30
    )
    assert "90 seconds" in batch.errors[0]
    client.start.assert_awaited_once()
    client.get_entity.assert_not_awaited()
    sleep.assert_not_awaited()
    client.disconnect.assert_awaited_once()


async def test_generic_api_error_hides_payload_and_saves_partial_batch(
    settings, repository, caplog
):
    from news_similarity.services.collection import CollectionService

    client = FakeClient(
        [[make_message(), errors.RPCError(None, "SENSITIVE API PAYLOAD", code=500)]]
    )
    summary = await CollectionService(
        repository, TelegramCollector(settings, client=client)
    ).collect("persian_news", 30)
    assert summary.newly_inserted == 1
    assert summary.total_fetched == 1
    assert len(summary.errors) == 1
    assert "RPCError" in summary.errors[0]
    assert "SENSITIVE" not in str(summary.errors) + caplog.text
    assert repository.count_news() == 1


async def test_new_posts_between_runs_use_stable_ids(settings, repository):
    from news_similarity.services.collection import CollectionService

    first_messages = [make_message(42), make_message(41)]
    second_messages = [make_message(43), make_message(42)]
    client = FakeClient([first_messages, second_messages])
    service = CollectionService(repository, TelegramCollector(settings, client=client))
    first = await service.collect("persian_news", 2)
    before = {(row.source_id, row.external_id) for row in repository.recent_news(10)}
    assert (first.newly_inserted, first.duplicates) == (2, 0)
    client.get_entity.return_value = make_channel("renamed_news")
    second = await service.collect("renamed_news", 2)
    after = {(row.source_id, row.external_id) for row in repository.recent_news(10)}
    assert (second.newly_inserted, second.duplicates) == (1, 1)
    assert repository.count_news() == 3
    assert len(repository.list_sources()) == 1
    source_id = repository.list_sources()[0].id
    assert after - before == {(source_id, "43")}
    assert before <= after
    assert not first.errors + second.errors
