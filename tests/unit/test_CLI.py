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


def test_run_plan_requires_and_forwards_billing_mode(monkeypatch, capsys):
    from harness_testing.CLI import main

    calls = []

    def fake_plan(root, **arguments):
        calls.append((root, arguments))
        return object()

    monkeypatch.setattr("harness_testing.Runs.plan_run", fake_plan)
    monkeypatch.setattr("harness_testing.Runs.format_plan", lambda manifest: "planned")

    assert main(
        [
            "run",
            "plan",
            "--profile",
            "smoke",
            "--billing-mode",
            "subscription",
            "--cell",
            "codex:A0:baseline",
            "--task",
            "react-grouped-ui-updates",
            "--max-sessions",
            "1",
            "--max-budget-usd",
            "0",
        ]
    ) == 0
    assert calls[0][1]["billing_mode"] == "subscription"
    assert capsys.readouterr().out == "planned\n"

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "run",
                "plan",
                "--profile",
                "smoke",
                "--cell",
                "codex:A0:baseline",
                "--task",
                "react-grouped-ui-updates",
                "--max-sessions",
                "1",
                "--max-budget-usd",
                "0",
            ]
        )
    assert exit_info.value.code == 2
