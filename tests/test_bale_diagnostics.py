"""Synthetic structures only; never copy personal values from live receipts."""

import copy
import json
from unittest.mock import Mock

import pytest

from news_similarity.integrations import bale_queue
from news_similarity.integrations.bale_diagnostics import diagnose_update
from news_similarity.integrations.bot_probe import ProbeConfig, ProbeError

TOKEN = "123456789:" + "a" * 35
SECRET = "PRIVATE_CONTENT_MUST_NOT_APPEAR"
CHAT = "5606750428"


def service(chat_type="channel", identifier=5):
    return {
        "update_id": identifier,
        "message": {
            "message_id": 0,
            "date": 1793264400,
            "chat": {"id": int(CHAT), "type": chat_type, "title": SECRET},
            "new_chat_members": [
                {
                    "id": 987654321,
                    "first_name": SECRET,
                    "username": SECRET,
                    "is_bot": False,
                }
            ],
            "from": {"id": 99887766, "first_name": SECRET},
        },
    }


def receipt(tmp_path, updates):
    path = tmp_path / "saved.json"
    path.write_text(
        json.dumps(
            {
                "payload": {
                    "platform": "bale",
                    "authorized_ids": [CHAT],
                    "updates": updates,
                },
                "signature": "never-authenticated-in-diagnostic-mode",
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "chat_type,support",
    [
        ("group", "documented_group_membership"),
        ("channel", "observed_scope_not_documented"),
    ],
)
def test_zero_id_membership_variant_is_explained_but_remains_blocked(
    chat_type, support
):
    update = service(chat_type)
    result = diagnose_update(update)
    assert result["variant"] == "service_candidate"
    assert result["service_support"] == support
    assert not any(i["code"] == "zero_not_supported" for i in result["issues"])
    assert not any(i["code"] == "missing_required_field" for i in result["issues"])
    rows = bale_queue._summary([update], frozenset({CHAT}))
    assert "service_review_required" in rows[0]["blockers"]


def test_authorization_blocker_is_not_hidden_by_zero_message_id():
    result = bale_queue._summary([service("group")], frozenset({"1"}))[0]
    assert result["blockers"] == ["chat_not_authorized", "service_review_required"]


@pytest.mark.parametrize("field", ["message_id", "date", "chat"])
def test_missing_fields_report_only_static_paths_and_types(field):
    update = service()
    del update["message"][field]
    result = diagnose_update(update)
    assert {
        "field": "message." + field,
        "code": "missing_required_field",
        "actual_type": "missing",
    } in result["issues"]
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    "value,expected",
    [(None, "null"), (True, "boolean"), ("private value", "string"), ([], "array")],
)
def test_invalid_message_id_types_are_not_coerced_or_echoed(value, expected):
    update = service()
    update["message"]["message_id"] = value
    result = diagnose_update(update)
    assert {
        "field": "message.message_id",
        "code": "expected_integer",
        "actual_type": expected,
    } in result["issues"]
    assert "private value" not in json.dumps(result)


def test_unknown_keys_values_and_nested_personal_data_are_not_echoed(tmp_path):
    update = service()
    update["message"][SECRET + TOKEN] = {"content": SECRET}
    update["message"]["text"] = SECRET + TOKEN
    result = bale_queue.diagnose_receipt(receipt(tmp_path, [update]))
    output = json.dumps(result)
    for forbidden in (
        SECRET,
        TOKEN,
        CHAT,
        "987654321",
        "99887766",
        "never-authenticated-in-diagnostic-mode",
    ):
        assert forbidden not in output
    assert result["updates"][0]["diagnostics"]["unknown_message_field_count"] == 1
    assert result["receipt_signature_verified"] is False
    assert result["network_requests"] == 0 and not result["acknowledged"]


@pytest.mark.parametrize(
    "update",
    [
        None,
        [],
        "private secret",
        {"update_id": SECRET},
        {"update_id": 1, SECRET: {"body": SECRET}},
        {"update_id": 1, "message": SECRET},
    ],
)
def test_unclassifiable_payloads_report_safely_and_keep_blockers(update):
    result = diagnose_update(update)
    assert result["issues"]
    assert SECRET not in json.dumps(result) and "private secret" not in json.dumps(
        result
    )
    assert bale_queue._summary([update], frozenset({CHAT}))[0]["blockers"]


@pytest.mark.parametrize("members", [None, SECRET, [SECRET]])
def test_malformed_membership_array_is_not_declared_valid(members):
    update = service("group")
    update["message"]["new_chat_members"] = members
    result = diagnose_update(update)
    assert any(i["code"] == "expected_array_of_objects" for i in result["issues"])
    assert SECRET not in json.dumps(result)


def test_textless_documented_media_is_diagnosed_without_file_metadata():
    update = service()
    del update["message"]["new_chat_members"]
    update["message"]["message_id"] = 10
    update["message"]["photo"] = [{"file_id": SECRET}]
    result = diagnose_update(update)
    assert result["variant"] == "media" and result["issues"] == []
    assert SECRET not in json.dumps(result)


def test_diagnostic_cli_needs_no_credentials_and_cannot_reach_transport(
    tmp_path, monkeypatch, capsys
):
    path = receipt(tmp_path, [service()])
    before = path.read_bytes()
    factory = Mock(side_effect=AssertionError("No network client is allowed"))
    monkeypatch.setattr(bale_queue, "BaleQueueClient", factory)
    monkeypatch.delenv("BALE_BOT_TOKEN", raising=False)
    assert bale_queue.main(["diagnose", "--receipt", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "DIAGNOSED"
    assert not report["acknowledged"] and report["network_requests"] == 0
    assert path.read_bytes() == before and len(list(tmp_path.iterdir())) == 1
    factory.assert_not_called()


def test_diagnostic_action_cannot_accept_acknowledgement_arguments(tmp_path, capsys):
    path = receipt(tmp_path, [service()])
    assert (
        bale_queue.main(
            [
                "diagnose",
                "--receipt",
                str(path),
                "--ack-through",
                "5",
                "--confirm-irreversible",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_diagnosed_service_does_not_allow_acknowledgement(tmp_path):
    cfg = ProbeConfig("bale", TOKEN, frozenset({CHAT}))
    client = Mock()
    client.call.side_effect = [
        {"id": 123, "is_bot": True},
        {"url": ""},
        [service()],
    ]
    path = tmp_path / "signed.json"
    report = bale_queue.inspect_queue(cfg, path, client=client, exclusive_test_bot=True)
    assert report["acknowledgeable_through"] is None
    assert CHAT not in json.dumps(report)
    client.reset_mock()
    with pytest.raises(ProbeError, match="Unexpected"):
        bale_queue.acknowledge_queue(
            cfg,
            path,
            5,
            client=client,
            exclusive_test_bot=True,
            confirm_irreversible=True,
        )
    client.call.assert_not_called()
    client.acknowledge.assert_not_called()


def test_diagnostics_deterministic_and_original_payload_unchanged():
    update = service()
    original = copy.deepcopy(update)
    assert diagnose_update(update) == diagnose_update(update)
    assert update == original
