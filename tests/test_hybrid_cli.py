import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from news_similarity import cli
from news_similarity.hybrid import HybridModelError
from news_similarity.semantic import SemanticModelError


def test_compare_cli_returns_hybrid_json_without_config_or_storage(
    monkeypatch, tmp_path, capsys
):
    from news_similarity import hybrid_evaluation

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "invalid")
    monkeypatch.setattr(
        cli.Settings, "load", lambda *args: pytest.fail("No config access")
    )
    matcher = Mock()
    matcher.compare.return_value = SimpleNamespace(
        to_dict=lambda: {
            "decision": "uncertain",
            "combined_ranking_score": 0.7,
            "score_interpretation": "not a probability",
        }
    )
    loader = Mock(return_value=matcher)
    monkeypatch.setattr(hybrid_evaluation, "load_hybrid_matcher", loader)
    assert cli.main(["compare-hybrid", "--text-a", "خبر الف", "--text-b", "خبر ب"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "uncertain"
    matcher.compare.assert_called_once_with("خبر الف", "خبر ب")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "error",
    [
        SemanticModelError("weights unavailable"),
        HybridModelError("inference unavailable"),
    ],
)
def test_hybrid_model_errors_do_not_print_fake_scores(monkeypatch, capsys, error):
    from news_similarity import hybrid_evaluation

    monkeypatch.setattr(
        hybrid_evaluation, "load_hybrid_matcher", Mock(side_effect=error)
    )
    assert cli.main(["compare-hybrid", "--text-a", "الف", "--text-b", "ب"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "unavailable" in output.err


def test_missing_freeze_is_actionable_and_does_not_train(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["compare-hybrid", "--text-a", "خبر", "--text-b", "متن"]) == 2
    assert "evaluate-hybrid first" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_evaluate_cli_reports_diagnostic_status_and_arguments(monkeypatch, capsys):
    from news_similarity import hybrid_evaluation

    runner = Mock(
        return_value={
            "status": "diagnostic_only",
            "configuration": {"semantic_weight": 0.5},
            "independent_evaluation": "unavailable",
            "evaluations": {},
        }
    )
    monkeypatch.setattr(hybrid_evaluation, "evaluate_hybrid", runner)
    assert (
        cli.main(["evaluate-hybrid", "--folds", "2", "--seed", "7", "--freeze-only"])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "diagnostic_only"
    assert runner.call_args.kwargs["folds"] == 2
    assert runner.call_args.kwargs["seed"] == 7
    assert runner.call_args.kwargs["freeze_only"] is True


def test_new_cli_arguments_are_validated_and_old_commands_remain():
    for arguments in (
        ["compare-hybrid", "--text-a", "الف"],
        ["evaluate-hybrid", "--folds", "0"],
        ["evaluate-hybrid", "--batch-size", "0"],
    ):
        with pytest.raises(SystemExit) as error:
            cli.parser().parse_args(arguments)
        assert error.value.code == 2
