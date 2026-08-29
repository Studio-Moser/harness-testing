from pathlib import Path

from rewardkit import criterion

from harness_testing.Workflow_Criteria import (
    cargo_test_correctness,
    command_after_last_mutation,
    command_succeeded,
    no_testing_churn,
)

_MANIFEST = Path(__file__).with_name("Protected_Files.json")


@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    return cargo_test_correctness(workspace, _MANIFEST)


@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    focused = (
        "cargo test -p event_model",
        "cargo test -p summary",
        "cargo test -p summary_cli",
    )
    return all(command_succeeded(command) for command in focused) and (
        command_after_last_mutation("cargo test --workspace")
    )


@criterion(shared=True)
def testing_efficiency(workspace: Path) -> bool:
    del workspace
    return no_testing_churn()
