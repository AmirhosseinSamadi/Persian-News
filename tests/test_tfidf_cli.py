import json

import pytest

from news_similarity import cli
from news_similarity.tfidf import TfidfSimilarity


def test_compare_requires_saved_model_and_never_silently_trains(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["compare", "--text-a", "خبر", "--text-b", "خبر"]) == 2
    assert "Run evaluate-tfidf" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["word", "character"])
def test_evaluate_and_compare_cli_without_credentials(
    monkeypatch, tmp_path, capsys, kind
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "invalid")
    monkeypatch.setenv("TELEGRAM_API_ID", "invalid")
    assert (
        cli.main(["evaluate-tfidf", "--model", kind, "--report-path", "docs/report.md"])
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["models"][kind]["test"]["count"] == 24
    assert (tmp_path / "docs/report.md").is_file()
    artifact = tmp_path / f"artifacts/tfidf/{kind}.model.json"
    before = artifact.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("Compare must not train.")

    monkeypatch.setattr(TfidfSimilarity, "fit_development", forbidden)
    assert (
        cli.main(["compare", "--model", kind, "--text-a", "کاشان", "--text-b", "کاشان"])
        == 0
    )
    comparison = json.loads(capsys.readouterr().out)
    assert 0 <= comparison["score"] <= 1
    assert comparison["fitted_on"] == "development"
    assert "not a calibrated probability" in comparison["score_interpretation"]
    assert artifact.read_bytes() == before
    assert not (tmp_path / "data").exists()


def test_cli_rejects_mismatched_model_kind(tmp_path, capsys):
    from news_similarity.evaluation import load_dataset

    data = load_dataset()
    model = TfidfSimilarity().fit_development(
        [pair for pair in data.pairs if pair.split == "development"],
        dataset_name=data.name,
        dataset_sha256=data.sha256,
    )
    path = tmp_path / "word.json"
    model.save(path)
    assert (
        cli.main(
            [
                "compare",
                "--model",
                "character",
                "--model-path",
                str(path),
                "--text-a",
                "خبر",
                "--text-b",
                "خبر",
            ]
        )
        == 2
    )
    assert "does not match" in capsys.readouterr().err
