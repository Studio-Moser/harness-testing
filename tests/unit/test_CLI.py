import pytest


def test_version_reports_repository_schema(capsys):
    from harness_testing.CLI import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "harness-test 0.1.0\n"


def test_task_qa_dispatches_one_named_deterministic_case(monkeypatch, capsys):
    from harness_testing.CLI import main

    calls = []

    def fake_run(root, task_id, case):
        calls.append((root, task_id, case))
        return {"reward": 1.0, "workflow": 1.0, "efficiency": 1.0}

    monkeypatch.setattr("harness_testing.QA.run_task_qa", fake_run)

    assert main(
        [
            "task",
            "qa",
            "--task",
            "react-grouped-ui-updates",
            "--case",
            "oracle",
        ]
    ) == 0
    assert calls[0][1:] == ("react-grouped-ui-updates", "oracle")
    assert capsys.readouterr().out == "reward=1 workflow=1 efficiency=1\n"
