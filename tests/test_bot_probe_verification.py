"""Synthetic regressions only: all HTTP responses and wall clocks are mocked."""

import copy
import io
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from news_similarity.integrations import bot_probe

NOW = datetime(2026, 10, 29, 12, 0, 0, 750000, tzinfo=UTC)
START_SECOND = int(NOW.timestamp())
TOKEN = "123456789:" + "a" * 35  # Fictional; no requests leave these tests.


def channel_post(update_id, published, *, edited=False):
    message = {
        "message_id": update_id,
        "chat": {"id": -100123, "type": "channel"},
        "date": published,
        "text": "خبر آزمایشی مصنوعی؛ متن فارسی حفظ می‌شود.",
    }
    if edited:
        message["edit_date"] = START_SECOND
    return {
        "update_id": update_id,
        "edited_channel_post" if edited else "channel_post": message,
    }


def run_probe(monkeypatch, pending, *, limit=20, injected=False):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return NOW

    monkeypatch.setattr(bot_probe, "datetime", FixedDateTime)
    calls = []

    def response(method, parameters):
        calls.append((method, parameters))
        return {
            "getMe": {"id": 123, "is_bot": True},
            "getWebhookInfo": {"url": ""},
            "getChat": {"id": -100123, "type": "channel"},
            "getChatMember": {"status": "member", "user": {"id": 123}},
            "getUpdates": pending[: parameters.get("limit", 20)],
        }[method]

    def open_response(request, timeout):
        assert timeout > 0
        method = request.full_url.rsplit("/", 1)[-1]
        result = response(method, json.loads(request.data))
        return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())

    opener = Mock()
    opener.open.side_effect = open_response
    monkeypatch.setattr(bot_probe, "build_opener", lambda *args: opener)
    client = None
    if injected:
        client = Mock()
        client.requests = 0
        client.call.side_effect = lambda method, params, timeout: response(
            method, params
        )
    report = bot_probe.live_probe(
        bot_probe.ProbeConfig("telegram", TOKEN, frozenset({"-100123"}), limit=limit),
        exclusive_test_bot=True,
        client=client,
        clock=lambda: 0,
    )
    return report, calls


def test_five_queued_posts_reproduce_report_and_repeat_without_acknowledgement(
    monkeypatch,
):
    pending = [
        channel_post(value, START_SECOND - 60) for value in range(20604482, 20604487)
    ]
    before = copy.deepcopy(pending)
    for _ in range(2):
        report, calls = run_probe(monkeypatch, pending)
        # Exercises the real-client code path with a mocked HTTP opener, not live proof.
        assert report["authentication_verified"] is True
        assert report["evidence_origin"] == "live_http"
        assert len(report["records"]) == 5
        assert report["status"] == "DOCUMENTED_ONLY" and not report["live_verified"]
        assert report["next_offset_candidate"] == 20604487
        assert (
            report["requested_offset"] is None and not report["acknowledged_by_probe"]
        )
        assert report["verification"]["rejection_counts"] == {
            "published_before_probe": 5
        }
        assert not report["verification"]["eligible_update_ids"]
        assert report["verification"]["probe_started_at"] == NOW.isoformat()
        assert report["polling"]["updates_returned"] == 5
        assert not report["polling"]["batch_at_limit"]
        assert "single returned batch" in report["reason"]
        polls = [params for method, params in calls if method == "getUpdates"]
        assert polls == [{"limit": 20, "timeout": 15}]
        assert not {"setWebhook", "deleteWebhook"} & {method for method, _ in calls}
    assert pending == before


def test_backlog_limit_hides_fresh_post_but_larger_batch_can_inspect_it(monkeypatch):
    pending = [channel_post(value, START_SECOND - 60) for value in range(1, 6)]
    pending.append(channel_post(6, START_SECOND))
    report, _ = run_probe(monkeypatch, pending, limit=5)
    assert not report["live_verified"] and len(report["records"]) == 5
    assert report["polling"]["batch_at_limit"]
    assert report["polling"]["more_pending_updates"] == "unknown"
    assert report["next_offset_candidate"] == 6
    report, _ = run_probe(monkeypatch, pending, limit=100)
    assert report["live_verified"] and report["status"] == "VERIFIED"
    assert report["verification"]["eligible_update_ids"] == [6]
    assert not report["acknowledged_by_probe"] and report["requested_offset"] is None


def test_more_than_100_queued_posts_remain_inaccessible_without_queue_advancement(
    monkeypatch,
):
    pending = [channel_post(value, START_SECOND - 60) for value in range(1, 101)]
    pending.append(channel_post(101, START_SECOND))
    report, calls = run_probe(monkeypatch, pending, limit=100)
    assert not report["live_verified"] and report["polling"]["batch_at_limit"]
    assert 101 not in [record["update_id"] for record in report["records"]]
    assert len([method for method, _ in calls if method == "getUpdates"]) == 1


@pytest.mark.parametrize(
    "seconds,eligible,reason",
    [
        (-1, False, "published_before_probe"),
        (0, True, None),  # Telegram dates have second precision; preserve rounding.
        (5, True, None),
        (6, False, "published_after_clock_tolerance"),
    ],
)
def test_publication_time_boundaries_and_clock_skew(
    monkeypatch, seconds, eligible, reason
):
    report, _ = run_probe(monkeypatch, [channel_post(1, START_SECOND + seconds)])
    check = report["verification"]["records"][0]
    assert check["eligible_by_content"] is eligible
    assert check["rejection_reasons"] == ([] if reason is None else [reason])
    assert report["live_verified"] is eligible


def test_large_update_id_does_not_make_an_old_publication_fresh(monkeypatch):
    report, _ = run_probe(monkeypatch, [channel_post(999999999, START_SECOND - 1)])
    assert report["next_offset_candidate"] == 1000000000
    assert not report["live_verified"]
    assert report["verification"]["rejection_counts"] == {"published_before_probe": 1}


def test_recent_edit_of_old_post_is_not_a_new_channel_post(monkeypatch):
    report, _ = run_probe(
        monkeypatch, [channel_post(1, START_SECOND - 60, edited=True)]
    )
    assert not report["live_verified"]
    assert report["verification"]["records"][0]["rejection_reasons"] == [
        "edited_update",
        "published_before_probe",
    ]
    assert (
        report["records"][0]["edited_at"]
        != report["records"][0]["news"]["published_at"]
    )


def test_fresh_content_from_injected_client_still_cannot_claim_live_verification(
    monkeypatch,
):
    report, _ = run_probe(monkeypatch, [channel_post(1, START_SECOND)], injected=True)
    assert report["verification"]["eligible_update_ids"] == [1]
    assert report["status"] == "DOCUMENTED_ONLY" and not report["live_verified"]
    assert not report["authentication_verified"] and report["network_requests"] == 0


def test_empty_queue_is_one_poll_and_does_not_claim_a_full_duration_watch(monkeypatch):
    report, calls = run_probe(monkeypatch, [])
    assert report["polling"]["request_count"] == 1
    assert report["polling"]["updates_returned"] == 0
    assert not report["verification"]["eligible_update_ids"]
    assert not report["live_verified"]
    assert len([method for method, _ in calls if method == "getUpdates"]) == 1
