"""Synthetic review transactions. No approval or acknowledgement of live updates."""

import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from news_similarity.integrations import bale_queue
from news_similarity.integrations.bale_diagnostics import classify_membership
from news_similarity.integrations.bot_parsing import parse_updates
from news_similarity.integrations.bot_probe import ProbeConfig, ProbeError

TOKEN = "123456789:" + "a" * 35
SECRET = "PRIVATE_VALUE_NEVER_DISPLAY"
CONFIG = ProbeConfig("bale", TOKEN, frozenset({"1001"}))


def message(identifier, *, chat=1001, kind="channel", service=False):
    body = {
        "chat": {"id": chat, "type": kind},
        "date": 1793264400,
        "message_id": 0 if service else identifier + 10,
    }
    if service:
        body["new_chat_members"] = [{"id": 9, "is_bot": False, "first_name": SECRET}]
    else:
        body["text"] = SECRET
    return {"update_id": identifier, "message": body}


class FakeQueue:
    def __init__(self, updates):
        self.pending = copy.deepcopy(updates)
        self.calls, self.acks = [], []

    def call(self, method, parameters, timeout):
        self.calls.append((method, parameters))
        if method == "getMe":
            return {"id": 123, "is_bot": True}
        if method == "getWebhookInfo":
            return {"url": ""}
        assert method == "getUpdates" and parameters == {"limit": 100, "timeout": 0}
        return copy.deepcopy(self.pending[:100])

    def acknowledge(self, highest_id, timeout):
        self.acks.append(highest_id)
        self.pending = [u for u in self.pending if u["update_id"] > highest_id]
        return copy.deepcopy(self.pending[:100])


def setup(tmp_path, updates):
    path, review = tmp_path / "inspection.json", tmp_path / "review.json"
    client = FakeQueue(updates)
    bale_queue.inspect_queue(CONFIG, path, exclusive_test_bot=True, client=client)
    client.calls.clear()
    return path, review, client


def approve(path, review, highest, ids):
    return bale_queue.review_queue(
        CONFIG, path, review, highest, ids, exclusive_test_bot=True
    )


def acknowledge(path, review, client, highest):
    return bale_queue.acknowledge_queue(
        CONFIG,
        path,
        highest,
        review_file=review,
        confirm_irreversible=True,
        exclusive_test_bot=True,
        client=client,
    )


@pytest.mark.parametrize(
    "kind,classification",
    [
        ("group", "membership_group"),
        ("channel", "membership_channel_review"),
    ],
)
def test_valid_zero_id_service_requires_review_and_never_becomes_news(
    kind, classification
):
    update = message(1, kind=kind, service=True)
    assert classify_membership(update["message"], "message") == classification
    row = bale_queue._summary([update], CONFIG.authorized_ids)[0]
    assert "unsupported_or_malformed_update" not in row["blockers"]
    assert "service_review_required" in row["blockers"]
    assert not parse_updates("bale", [update], CONFIG.authorized_ids).records


@pytest.mark.parametrize(
    "change",
    [
        "ordinary_zero",
        "empty_members",
        "bad_member",
        "missing_name",
        "mixed_text",
        "mixed_service",
        "private_membership",
        "negative_id",
        "bool_id",
    ],
)
def test_zero_id_or_service_tag_alone_cannot_bypass_structural_validation(change):
    update = message(1, service=True)
    body = update["message"]
    if change == "ordinary_zero":
        del body["new_chat_members"]
        body["text"] = SECRET
    elif change == "empty_members":
        body["new_chat_members"] = []
    elif change == "bad_member":
        body["new_chat_members"] = [SECRET]
    elif change == "missing_name":
        del body["new_chat_members"][0]["first_name"]
    elif change == "mixed_text":
        body["text"] = SECRET
    elif change == "mixed_service":
        body["left_chat_member"] = {"id": 9}
    elif change == "private_membership":
        body["chat"]["type"] = "private"
    elif change == "negative_id":
        body["message_id"] = -1
    else:
        body["message_id"] = True
    row = bale_queue._summary([update], CONFIG.authorized_ids)[0]
    assert "unsupported_or_malformed_update" in row["blockers"]
    assert not parse_updates("bale", [update], CONFIG.authorized_ids).records


def test_six_update_review_is_per_record_ack_only_and_keeps_future_updates(tmp_path):
    pending = [
        message(1, chat=2001, kind="private"),
        message(2, chat=2002, kind="group", service=True),
        message(3, chat=2002, kind="group"),
        message(4, chat=2002, kind="group"),
        message(5, service=True),
        message(6),
    ]
    path, review, client = setup(tmp_path, pending)
    before = path.read_bytes()
    report = approve(path, review, 6, [1, 2, 3, 4, 5, 6])
    assert report["acknowledgement_only"] and not report["acknowledged"]
    assert not client.calls and not client.acks and path.read_bytes() == before
    assert CONFIG.authorized_ids == frozenset({"1001"})
    client.pending.append(message(7))
    result = acknowledge(path, review, client, 6)
    assert result["requested_offset"] == 7 and client.acks == [6]
    assert [u["update_id"] for u in client.pending] == [7]
    assert result["returned_unacknowledged_updates"][0]["update_id"] == 7
    attempt = json.loads(path.with_name(path.name + ".ack-attempt.json").read_text())
    assert attempt["approved_update_ids"] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize("ids", [[], [1], [2], [1, 1, 2], [1, 2, 3], [2, 1], [True, 2]])
def test_missing_duplicate_outside_or_reordered_approvals_are_rejected(tmp_path, ids):
    path, review, client = setup(tmp_path, [message(1), message(2)])
    with pytest.raises(ProbeError):
        approve(path, review, 2, ids)
    assert not review.exists() and not client.calls and not client.acks


def test_authorized_news_still_needs_individual_approval_and_irreversible_confirmation(
    tmp_path,
):
    path, review, client = setup(tmp_path, [message(1)])
    with pytest.raises(ProbeError, match="review-file"):
        acknowledge(path, None, client, 1)
    approve(path, review, 1, [1])
    with pytest.raises(ProbeError, match="confirm-irreversible"):
        bale_queue.acknowledge_queue(
            CONFIG, path, 1, review_file=review, exclusive_test_bot=True, client=client
        )
    assert not client.calls and not client.acks


@pytest.mark.parametrize("boundary", [0, 2])
def test_uninspected_boundary_cannot_be_reviewed(tmp_path, boundary):
    path, review, client = setup(tmp_path, [message(1)])
    with pytest.raises(ProbeError, match="not inspected"):
        approve(path, review, boundary, [1])
    assert not review.exists() and not client.acks


def test_partial_prefix_review_cannot_acknowledge_later_boundary(tmp_path):
    path, review, client = setup(tmp_path, [message(1), message(2)])
    approve(path, review, 1, [1])
    with pytest.raises(ProbeError, match="exact inspection"):
        acknowledge(path, review, client, 2)
    assert not client.calls and not client.acks


@pytest.mark.parametrize(
    "change", ["changed_body", "missing", "earlier_event", "malformed_id"]
)
def test_approved_prefix_is_rechecked_before_remote_ack(tmp_path, change):
    path, review, client = setup(tmp_path, [message(1), message(2)])
    approve(path, review, 2, [1, 2])
    if change == "changed_body":
        client.pending[1]["message"]["text"] = "changed"
    elif change == "missing":
        client.pending.pop(0)
    elif change == "earlier_event":
        client.pending.insert(0, message(0))
    else:
        client.pending.append({"update_id": None})
    with pytest.raises(ProbeError):
        acknowledge(path, review, client, 2)
    assert not client.acks
    assert not path.with_name(path.name + ".ack-attempt.json").exists()


def test_tampered_or_different_receipt_review_cannot_be_used(tmp_path):
    path, review, client = setup(tmp_path, [message(1)])
    approve(path, review, 1, [1])
    original = review.read_bytes()
    document = json.loads(original)
    document["payload"]["approved_update_ids"] = [1, 1]
    review.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProbeError, match="integrity"):
        acknowledge(path, review, client, 1)
    review.write_bytes(original)
    other_path = tmp_path / "another-inspection.json"
    bale_queue.inspect_queue(CONFIG, other_path, client=client, exclusive_test_bot=True)
    client.calls.clear()
    with pytest.raises(ProbeError, match="exact inspection"):
        acknowledge(other_path, review, client, 1)
    assert not client.calls and not client.acks


def test_expired_inspection_invalidates_even_existing_review(tmp_path, monkeypatch):
    path, review, client = setup(tmp_path, [message(1)])
    approve(path, review, 1, [1])

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(minutes=16)

    monkeypatch.setattr(bale_queue, "datetime", Later)
    with pytest.raises(ProbeError, match="expired"):
        acknowledge(path, review, client, 1)
    assert not client.calls and not client.acks


def test_unsupported_event_and_gaps_cannot_be_overridden_by_approval(tmp_path):
    updates = [{"update_id": 1, "callback_query": {}}, message(3)]
    path, review, client = setup(tmp_path, updates)
    with pytest.raises(ProbeError, match="Unexpected"):
        approve(path, review, 3, [1, 3])
    assert not review.exists() and not client.acks


def test_review_cli_is_local_redacted_and_separate_from_acknowledgement(
    tmp_path, monkeypatch, capsys
):
    path, review, client = setup(tmp_path, [message(1, chat=2001, kind="private")])
    monkeypatch.setenv("BALE_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BALE_BOT_CHAT_IDS", "1001")
    factory = Mock(side_effect=AssertionError("Review cannot contact an API"))
    monkeypatch.setattr(bale_queue, "BaleQueueClient", factory)
    assert (
        bale_queue.main(
            [
                "review",
                "--receipt",
                str(path),
                "--review-file",
                str(review),
                "--ack-through",
                "1",
                "--approve-update",
                "1",
                "--exclusive-test-bot",
                "--env-file",
                str(tmp_path / "absent"),
            ]
        )
        == 0
    )
    result = capsys.readouterr()
    assert json.loads(result.out)["status"] == "REVIEWED"
    assert (
        TOKEN not in result.out
        and SECRET not in result.out
        and "2001" not in result.out
    )
    factory.assert_not_called()
    assert not client.acks
