import json

import pytest

from news_similarity import cli


def test_feature_cli_has_no_database_model_or_configuration_dependency(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "invalid")

    def forbidden(*args, **kwargs):
        pytest.fail("Feature comparison must not open config or storage.")

    monkeypatch.setattr(cli.Settings, "load", forbidden)
    monkeypatch.setattr(cli, "NewsRepository", forbidden)
    assert (
        cli.main(
            [
                "--env-file",
                "missing.env",
                "compare-features",
                "--text-a",
                "در تهران ۱۲ نفر آمدند.",
                "--text-b",
                "در تهران ۱۳ نفر آمدند.",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert output.err == ""
    assert result["conflicting_features"][0]["confidence"] == "possible_conflict"
    assert result["news_a"]["original_text"] == "در تهران ۱۲ نفر آمدند."
    assert result["event_identity"] == "undetermined"
    assert not {"score", "prediction", "percentage"}.intersection(result)
    assert not list(tmp_path.iterdir())


def test_cli_empty_strings_return_unknown_evidence(capsys):
    assert cli.main(["compare-features", "--text-a", "", "--text-b", ""]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["conflicting_features"]
    assert len(result["missing_or_unknown_features"]) == 7


def test_cli_retains_all_previous_commands():
    commands = cli.parser()._subparsers._group_actions[0].choices
    assert set(commands) == {
        "init-db",
        "collect-telegram",
        "collect-telegram-bot",
        "collect-bale",
        "collection-status",
        "list-news",
        "stats",
        "preprocess",
        "dataset-stats",
        "evaluate-tfidf",
        "compare",
        "evaluate-semantic",
        "compare-semantic",
        "compare-features",
        "compare-hybrid",
        "evaluate-hybrid",
    }


def test_cli_requires_both_text_arguments():
    with pytest.raises(SystemExit) as error:
        cli.parser().parse_args(["compare-features", "--text-a", "متن"])
    assert error.value.code == 2
