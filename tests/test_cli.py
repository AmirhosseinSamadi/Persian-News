import json
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from news_similarity import cli
from news_similarity.records import CollectionSummary


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'news.db').as_posix()}")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)


def test_local_commands(cli_env, capsys):
    assert cli.main(["init-db"]) == 0
    assert "Database initialized" in capsys.readouterr().out
    assert cli.main(["list-news", "--limit", "10"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["stats"]) == 0
    assert json.loads(capsys.readouterr().out) == {"total_news": 0, "sources": []}


def test_missing_credentials_fail_without_prompt(cli_env, capsys):
    assert cli.main(["collect-telegram", "--channel", "persian_news"]) == 2
    assert "TELEGRAM_API_ID" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command", [[], ["collect-telegram"], ["list-news", "--limit", "0"]]
)
def test_argument_validation(command):
    with pytest.raises(SystemExit) as error:
        cli.main(command)
    assert error.value.code == 2


@pytest.mark.parametrize("errors,exit_code", [([], 0), (["Connection lost."], 1)])
@pytest.mark.parametrize("limit", [7, 30])
def test_collect_summary_and_exit_code(
    cli_env, monkeypatch, capsys, errors, exit_code, limit
):
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setattr(cli, "TelegramCollector", lambda _: object())
    summary = CollectionSummary("اخبار", 3, 2, 1, 1, 1, errors)
    monkeypatch.setattr(
        cli.CollectionService, "collect", AsyncMock(return_value=summary)
    )
    assert (
        cli.main(
            ["collect-telegram", "--channel", "persian_news", "--limit", str(limit)]
        )
        == exit_code
    )
    assert json.loads(capsys.readouterr().out) == {
        **asdict(summary),
        "requested_limit": limit,
        "error_count": len(errors),
    }


def test_corrupt_session_constructor_reports_storage_failure(
    cli_env, monkeypatch, capsys
):
    import sqlite3

    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)

    def corrupt_session(_settings):
        raise sqlite3.DatabaseError("sensitive session details")

    monkeypatch.setattr(cli, "TelegramCollector", corrupt_session)
    assert cli.main(["collect-telegram", "--channel", "persian_news"]) == 1
    output = capsys.readouterr()
    assert "session storage failed" in output.err
    assert "sensitive" not in output.err + output.out
