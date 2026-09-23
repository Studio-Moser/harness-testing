import pytest


def test_version_reports_repository_schema(capsys):
    from harness_testing.CLI import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "harness-test 0.3.0\n"


def test_task_qa_dispatches_one_named_deterministic_case(monkeypatch, capsys):
    from harness_testing.CLI import main

    calls = []

    def fake_run(root, task_id, case):
        calls.append((root, task_id, case))
        return {"reward": 1.0, "workflow": 1.0, "efficiency": 1.0}

    monkeypatch.setattr("harness_testing.QA.run_task_qa", fake_run)

    assert (
        main(
            [
                "task",
                "qa",
                "--task",
                "react-grouped-ui-updates",
                "--case",
                "oracle",
            ]
        )
        == 0
    )
    assert calls[0][1:] == ("react-grouped-ui-updates", "oracle")
    assert capsys.readouterr().out == "reward=1 workflow=1 efficiency=1\n"


def test_task_qa_batches_one_pack_and_all_cases(monkeypatch, capsys):
    from harness_testing.CLI import main

    calls = []

    def fake_run(root, task_id, case):
        calls.append((root, task_id, case))
        return {"reward": 1.0, "workflow": 0.0, "efficiency": 1.0}

    monkeypatch.setattr("harness_testing.QA.run_task_qa", fake_run)
    monkeypatch.setattr(
        "harness_testing.QA.task_ids_for_pack",
        lambda root, pack: ("first-task", "second-task"),
    )
    monkeypatch.setattr("harness_testing.QA.QA_CASES", ("oracle", "nop"))

    assert main(["task", "qa", "--pack", "workflow", "--all-cases"]) == 0
    assert [(task, case) for _, task, case in calls] == [
        ("first-task", "oracle"),
        ("first-task", "nop"),
        ("second-task", "oracle"),
        ("second-task", "nop"),
    ]
    assert capsys.readouterr().out.splitlines() == [
        "first-task:oracle reward=1 workflow=0 efficiency=1",
        "first-task:nop reward=1 workflow=0 efficiency=1",
        "second-task:oracle reward=1 workflow=0 efficiency=1",
        "second-task:nop reward=1 workflow=0 efficiency=1",
    ]


def test_claude_auth_stores_token_with_redacted_success_message(monkeypatch, capsys):
    from harness_testing.CLI import main

    monkeypatch.setattr("harness_testing.Credentials.store_claude_subscription_token", lambda: None)

    assert main(["auth", "claude"]) == 0
    captured = capsys.readouterr()
    assert captured.out == (
        "Enter the Claude subscription token in the Keychain prompt.\n"
        "Claude subscription token stored in Keychain.\n"
    )
    assert captured.err == ""


def test_claude_auth_returns_redacted_failure_without_storage_output(monkeypatch, capsys):
    from harness_testing.CLI import main

    def failing_storage():
        raise ValueError("unexpected detail")

    monkeypatch.setattr(
        "harness_testing.Credentials.store_claude_subscription_token", failing_storage
    )

    assert main(["auth", "claude"]) == 1
    captured = capsys.readouterr()
    assert "unexpected detail" not in captured.out + captured.err
    assert captured.out == "Enter the Claude subscription token in the Keychain prompt.\n"
    assert captured.err == "Claude subscription token could not be stored.\n"


@pytest.mark.parametrize(
    ("subcommand", "arguments", "target"),
    [
        ("prepare", ["--report", "Report.json", "--protocol", "Protocol.json"], "prepare_grading"),
        ("record", ["--plan", "Plan.json", "--results", "Results.json"], "record_grading"),
    ],
)
def test_collaboration_commands_dispatch_without_starting_models(
    monkeypatch, capsys, subcommand, arguments, target
):
    from harness_testing.CLI import main

    calls = []
    monkeypatch.setattr(
        f"harness_testing.Collaboration_Grading.{target}",
        lambda *args: calls.append(args) or {"status": "accepted"},
    )
    monkeypatch.setattr("harness_testing.Run_Reports.refresh_local_dashboard", lambda root: None)
    assert main(["collaboration", subcommand, *arguments]) == 0
    assert calls
    assert '"status": "accepted"' in capsys.readouterr().out
