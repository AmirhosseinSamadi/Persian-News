"""Synthetic queue transactions; no real bot credentials or network access."""

import copy
import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from news_similarity.integrations import bale_queue
from news_similarity.integrations.bot_probe import (
    HttpBotClient,
    ProbeConfig,
    ProbeError,
)

TOKEN = "123456789:" + "a" * 35
CHAT = "5606750428"


def config(**overrides):
    return ProbeConfig(
        **(
            {"platform": "bale", "token": TOKEN, "authorized_ids": frozenset({CHAT})}
            | overrides
        )
    )


def post(identifier=6, **changes):
    message = {
        "chat": {"id": int(CHAT), "type": "channel"},
        "message_id": identifier + 1,
        "date": 1793264400,
        "text": "نمونهٔ مصنوعی؛ دریافت زنده ادعا نمی‌شود.",
    }
    message.update(changes)
    return {"update_id": identifier, "message": message}


class QueueClient:
    def __init__(self, updates=None):
        self.pending = copy.deepcopy(updates if updates is not None else [post()])
        self.bot_id, self.webhook = 123, ""
        self.calls, self.acks = [], []
        self.fail_after_ack = False

    def call(self, method, parameters, timeout):
        self.calls.append((method, parameters))
        assert timeout > 0
        if method == "getMe":
            return {"id": self.bot_id, "is_bot": True}
        if method == "getWebhookInfo":
            return {"url": self.webhook}
        assert method == "getUpdates" and parameters == {"limit": 100, "timeout": 0}
        return copy.deepcopy(self.pending[:100])

    def acknowledge(self, highest_id, timeout):
        assert timeout > 0
        self.acks.append(highest_id)
        self.pending = [u for u in self.pending if u["update_id"] > highest_id]
        if self.fail_after_ack:
            raise ProbeError("Simulated lost response after remote application.")
        return copy.deepcopy(self.pending[:100])


def inspect(tmp_path, client=None):
    client = client or QueueClient()
    path = tmp_path / "inspection.json"
    report = bale_queue.inspect_queue(
        config(), path, exclusive_test_bot=True, client=client
    )
    return path, report, client


def acknowledge(path, client, highest=6, **overrides):
    review = path.with_name(path.name + ".review.json")
    # Existing success scenarios now explicitly review their synthetic safe records.
    payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
    rows = bale_queue._summary(payload["updates"], config().authorized_ids)
    ids = [row["update_id"] for row in rows]
    if type(highest) is int and highest in ids and not review.exists():
        prefix_rows = rows[: ids.index(highest) + 1]
        if not any(row["blockers"] for row in prefix_rows):
            bale_queue.review_queue(
                config(),
                path,
                review,
                highest,
                [row["update_id"] for row in prefix_rows],
                exclusive_test_bot=True,
            )
    options = {
        "exclusive_test_bot": True,
        "confirm_irreversible": True,
        "client": client,
        "review_file": review if review.exists() else None,
    }
    return bale_queue.acknowledge_queue(
        config(), path, highest, **(options | overrides)
    )


def test_inspection_is_read_only_preserves_raw_payload_and_large_channel_id(tmp_path):
    path, report, client = inspect(tmp_path)
    row = report["updates"][0]
    assert {key: value for key, value in row.items() if key != "diagnostics"} == {
        "update_id": 6,
        "event_type": "message",
        "chat_type": "channel",
        "blockers": [],
    }
    assert "chat_id" not in row
    assert row["diagnostics"]["issues"] == []
    assert report["acknowledgeable_through"] == 6 and not report["queue_empty"]
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["payload"]["updates"] == client.pending
    assert TOKEN not in path.read_text(encoding="utf-8")
    assert not client.acks and not report["acknowledged"]
    assert not report["production_database_written"]


@pytest.mark.parametrize("highest", [0, 1, 2])
def test_explicit_partial_prefix_and_zero_id_never_acknowledge_later_updates(
    tmp_path, highest
):
    path, _, client = inspect(tmp_path, QueueClient([post(i) for i in range(3)]))
    report = acknowledge(path, client, highest)
    assert client.acks == [highest]
    assert report["requested_offset"] == highest + 1
    assert [u["update_id"] for u in client.pending] == list(range(highest + 1, 3))
    assert report["queue_empty"] is (highest == 2)
    assert path.with_name(path.name + ".ack-attempt.json").is_file()
    assert path.with_name(path.name + ".ack-result.json").is_file()


@pytest.mark.parametrize("highest", [-1, True, 5, 7, 999999])
def test_uninspected_boundary_or_offset_instead_of_highest_id_is_blocked(
    tmp_path, highest
):
    path, _, client = inspect(tmp_path)
    client.calls.clear()
    with pytest.raises((ValueError, ProbeError)):
        acknowledge(path, client, highest)
    assert not client.calls and not client.acks


@pytest.mark.parametrize("confirmation", [False, None, "yes"])
def test_missing_explicit_confirmation_makes_no_requests(tmp_path, confirmation):
    path, _, client = inspect(tmp_path)
    client.calls.clear()
    with pytest.raises(ProbeError, match="confirm-irreversible"):
        acknowledge(path, client, confirm_irreversible=confirmation)
    assert not client.calls and not client.acks


def test_exclusive_bot_assertion_webhook_and_wrong_bot_are_checked(tmp_path):
    path, _, client = inspect(tmp_path)
    with pytest.raises(ProbeError, match="exclusive"):
        acknowledge(path, client, exclusive_test_bot=False)
    client.webhook = "https://example.org/private-hook"
    with pytest.raises(ProbeError, match="webhook"):
        acknowledge(path, client)
    client.webhook, client.bot_id = "", 999
    with pytest.raises(ProbeError, match="different bot"):
        acknowledge(path, client)
    assert not client.acks


def test_receipt_cannot_be_reused_after_one_attempt(tmp_path):
    path, _, client = inspect(tmp_path)
    acknowledge(path, client)
    client.calls.clear()
    with pytest.raises(ProbeError, match="attempt"):
        acknowledge(path, client)
    assert client.acks == [6] and not client.calls


def test_changed_receipt_token_or_scope_blocks_before_network(tmp_path):
    path, _, client = inspect(tmp_path)
    client.calls.clear()
    for altered in (
        config(token="123456789:" + "b" * 35),
        config(authorized_ids=frozenset({"345"})),
    ):
        with pytest.raises(ProbeError):
            bale_queue.acknowledge_queue(
                altered,
                path,
                6,
                client=client,
                exclusive_test_bot=True,
                confirm_irreversible=True,
            )
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["payload"]["updates"][0]["update_id"] = 900
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ProbeError, match="integrity"):
        acknowledge(path, client, 900)
    assert not client.calls and not client.acks


def test_receipt_expiry_is_fail_closed(tmp_path, monkeypatch):
    path, _, client = inspect(tmp_path)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(minutes=16)

    monkeypatch.setattr(bale_queue, "datetime", Later)
    with pytest.raises(ProbeError, match="expired"):
        acknowledge(path, client)
    assert not client.acks


@pytest.mark.parametrize(
    "unexpected",
    [
        {"update_id": 5, "callback_query": {"data": "private"}},
        {"update_id": 5, "unknown_future_event": {}},
        {"update_id": "bad", "message": {}},
        post(5, chat={"id": 999, "type": "private"}),
    ],
)
def test_unexpected_updates_in_inspected_prefix_are_never_silently_skipped(
    tmp_path, unexpected
):
    path, report, client = inspect(tmp_path, QueueClient([unexpected, post()]))
    assert report["acknowledgeable_through"] is None
    with pytest.raises(ProbeError, match="Unexpected"):
        acknowledge(path, client)
    assert not client.acks


@pytest.mark.parametrize(
    "change", ["edited_payload", "new_earlier_update", "removed", "bad_id"]
)
def test_queue_changes_after_inspection_block_acknowledgement(tmp_path, change):
    path, _, client = inspect(tmp_path)
    if change == "edited_payload":
        client.pending[0]["message"]["text"] = "تغییر مصنوعی"
    elif change == "new_earlier_update":
        client.pending.insert(0, post(5))
    elif change == "removed":
        client.pending.clear()
    else:
        client.pending.append({"update_id": None})
    with pytest.raises(ProbeError):
        acknowledge(path, client)
    assert not client.acks


def test_unexamined_later_event_is_preserved_and_never_acknowledged(tmp_path):
    path, _, client = inspect(tmp_path)
    later = {"update_id": 7, "unknown_future_event": {"private": "preserve me"}}
    client.pending.append(later)
    report = acknowledge(path, client)
    assert client.acks == [6] and client.pending == [later]
    assert report["returned_unacknowledged_updates"][0]["event_type"] == "unsupported"
    saved = json.loads(path.with_name(path.name + ".ack-result.json").read_text())
    assert saved["updates"] == [later]


def test_lost_response_is_unknown_and_never_automatically_retried(tmp_path):
    path, _, client = inspect(tmp_path)
    client.fail_after_ack = True
    with pytest.raises(bale_queue.AcknowledgementUncertain, match="UNKNOWN"):
        acknowledge(path, client)
    assert client.pending == [] and client.acks == [6]
    with pytest.raises(ProbeError, match="attempt"):
        acknowledge(path, client)
    assert client.acks == [6]


def test_journal_failure_prevents_acknowledgement(tmp_path, monkeypatch):
    path, _, client = inspect(tmp_path)
    original = bale_queue._write_new

    def fail_intent(destination, document):
        if str(destination).endswith(".ack-attempt.json"):
            raise OSError("Simulated storage failure")
        original(destination, document)

    monkeypatch.setattr(bale_queue, "_write_new", fail_intent)
    with pytest.raises(OSError):
        acknowledge(path, client)
    assert not client.acks


@pytest.mark.parametrize("platform", ["bale", "telegram"])
def test_normal_probe_client_still_forbids_offsets_for_both_platforms(platform):
    client = HttpBotClient(config(platform=platform))
    client._opener = Mock()
    with pytest.raises(ProbeError, match="offsets"):
        client.call("getUpdates", {"offset": 7}, 1)
    client._opener.open.assert_not_called()


def test_bale_only_transport_sends_exact_offset_and_refuses_telegram():
    with pytest.raises(ProbeError, match="restricted to Bale"):
        bale_queue.BaleQueueClient(config(platform="telegram"))
    client = bale_queue.BaleQueueClient(config())
    client._opener = Mock()
    client._opener.open.return_value = io.BytesIO(b'{"ok":true,"result":[]}')
    assert client.acknowledge(6, 1) == []
    request = client._opener.open.call_args.args[0]
    assert request.full_url == f"https://tapi.bale.ai/bot{TOKEN}/getUpdates"
    assert json.loads(request.data) == {"offset": 7, "limit": 100, "timeout": 0}
    assert "api.telegram.org" not in request.full_url


def test_cli_warning_missing_confirmation_and_inspection_do_not_acknowledge(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("BALE_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BALE_BOT_CHAT_IDS", CHAT)
    client = QueueClient()
    monkeypatch.setattr(bale_queue, "BaleQueueClient", lambda cfg: client)
    path = tmp_path / "receipt.json"
    args = [
        "--receipt",
        str(path),
        "--exclusive-test-bot",
        "--env-file",
        str(tmp_path / "absent"),
    ]
    assert bale_queue.main(["inspect", *args]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["updates"][0]["update_id"] == 6
    client.calls.clear()
    assert bale_queue.main(["acknowledge", *args, "--ack-through", "6"]) == 2
    output = capsys.readouterr()
    assert "IRREVERSIBLE" in output.err and "confirm-irreversible" in output.out
    assert not client.acks and not client.calls
    assert TOKEN not in output.out + output.err


def test_empty_queue_is_read_only_and_receipts_cannot_be_overwritten(tmp_path):
    path, report, client = inspect(tmp_path, QueueClient([]))
    assert report["queue_empty"] and report["updates"] == []
    with pytest.raises(ProbeError, match="not inspected"):
        acknowledge(path, client)
    with pytest.raises(ProbeError, match="already exists"):
        bale_queue.inspect_queue(config(), path, exclusive_test_bot=True, client=client)
    assert not client.acks


def test_acknowledgement_workflow_rejects_telegram_before_any_requests(tmp_path):
    client = QueueClient()
    with pytest.raises(ProbeError, match="Bale"):
        bale_queue.acknowledge_queue(
            config(platform="telegram"),
            tmp_path / "missing.json",
            6,
            confirm_irreversible=True,
            exclusive_test_bot=True,
            client=client,
        )
    assert not client.calls and not client.acks


def test_invalid_acknowledgement_response_is_uncertain_and_not_retried(tmp_path):
    path, _, client = inspect(tmp_path)
    client.acknowledge = Mock(return_value=[post(6)])
    with pytest.raises(bale_queue.AcknowledgementUncertain):
        acknowledge(path, client)
    assert path.with_name(path.name + ".ack-result.json").is_file()
    with pytest.raises(ProbeError, match="attempt"):
        acknowledge(path, client)
    client.acknowledge.assert_called_once()


def test_result_write_failure_is_unknown_not_a_claim_of_no_acknowledgement(
    tmp_path, monkeypatch
):
    path, _, client = inspect(tmp_path)
    original = bale_queue._write_new

    def fail_result(destination, document):
        if str(destination).endswith(".ack-result.json"):
            raise OSError("Simulated disk failure after remote acknowledgement")
        original(destination, document)

    monkeypatch.setattr(bale_queue, "_write_new", fail_result)
    with pytest.raises(bale_queue.AcknowledgementUncertain):
        acknowledge(path, client)
    assert client.acks == [6] and client.pending == []
    assert path.with_name(path.name + ".ack-attempt.json").is_file()


def test_non_contiguous_ids_block_acknowledging_unseen_gap(tmp_path):
    path, report, client = inspect(tmp_path, QueueClient([post(4), post(6)]))
    assert report["acknowledgeable_through"] == 4
    with pytest.raises(ProbeError, match="Unexpected"):
        acknowledge(path, client, 6)
    assert not client.acks


def test_cli_unknown_outcome_has_distinct_exit_code_and_no_secret(
    tmp_path, monkeypatch, capsys
):
    path, _, client = inspect(tmp_path)
    client.fail_after_ack = True
    monkeypatch.setenv("BALE_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BALE_BOT_CHAT_IDS", CHAT)
    monkeypatch.setattr(bale_queue, "BaleQueueClient", lambda cfg: client)
    review = tmp_path / "review.json"
    bale_queue.review_queue(config(), path, review, 6, [6], exclusive_test_bot=True)
    code = bale_queue.main(
        [
            "acknowledge",
            "--receipt",
            str(path),
            "--ack-through",
            "6",
            "--review-file",
            str(review),
            "--confirm-irreversible",
            "--exclusive-test-bot",
            "--env-file",
            str(tmp_path / "absent"),
        ]
    )
    output = capsys.readouterr()
    assert code == 3 and json.loads(output.out)["status"] == "UNKNOWN"
    assert TOKEN not in output.out + output.err
    assert client.acks == [6]
