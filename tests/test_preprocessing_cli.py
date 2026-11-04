import json

from news_similarity import cli


def test_text_commands_need_no_configuration_or_database(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "not even a URL")
    monkeypatch.setenv("TELEGRAM_API_ID", "not an ID")
    assert cli.main(["preprocess", "--text", "علي در كاشان نیست"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["normalized_text"] == "علی در کاشان نیست"
    assert result["original_text"] == "علي در كاشان نیست"
    assert cli.main(["dataset-stats"]) == 0
    assert json.loads(capsys.readouterr().out)["total_pairs"] == 72
    assert list(tmp_path.iterdir()) == []


def test_preprocess_profile_and_overrides(capsys):
    assert (
        cli.main(
            [
                "preprocess",
                "--text",
                "در #خبر @news ۱۲ نیست!",
                "--profile",
                "semantic",
                "--hashtags",
                "strip",
                "--mentions",
                "remove",
                "--remove-stopwords",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["normalized_text"] == "در خبر ۱۲ نیست!"
    assert result["tokens"] == ["خبر", "۱۲", "نیست", "!"]


def test_invalid_custom_dataset_reports_error(tmp_path, capsys):
    path = tmp_path / "dataset.json"
    path.write_text('{"synthetic": false}', encoding="utf-8")
    assert cli.main(["dataset-stats", "--path", str(path)]) == 2
    assert "Input error:" in capsys.readouterr().err
