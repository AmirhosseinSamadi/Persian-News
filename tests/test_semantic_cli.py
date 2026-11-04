from unittest.mock import Mock

from news_similarity import cli
from news_similarity.semantic import SemanticModelError


def test_compare_empty_text_requires_no_model_or_database(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "invalid")
    assert cli.main(["compare-semantic", "--text-a", "", "--text-b", "خبر"]) == 2
    assert "nonempty" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_model_unavailable_is_reported_without_fake_scores(monkeypatch, capsys):
    from news_similarity import semantic

    model = Mock()
    model.compare.side_effect = SemanticModelError("Pinned weights unavailable.")
    monkeypatch.setattr(semantic, "SemanticSimilarity", lambda config: model)
    assert cli.main(["compare-semantic", "--text-a", "الف", "--text-b", "ب"]) == 1
    output = capsys.readouterr()
    assert "unavailable" in output.err and output.out == ""
