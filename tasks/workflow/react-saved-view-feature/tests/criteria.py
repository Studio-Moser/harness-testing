from pathlib import Path

from rewardkit import criterion

from harness_testing.Workflow_Criteria import (
    command_after_last_mutation,
    no_testing_churn,
    node_test_correctness,
)

_MANIFEST = Path(__file__).with_name("Protected_Files.json")
_DEPENDENCIES = Path("/opt/react-sentinel/node_modules")


@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    return node_test_correctness(workspace, _MANIFEST, _DEPENDENCIES)


@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    return all(
        command_after_last_mutation(command)
        for command in (
            "npm run test:saved-view",
            "npm run test:view-filter",
            "npm run gate",
        )
    )


@criterion(shared=True)
def testing_efficiency(workspace: Path) -> bool:
    del workspace
    return no_testing_churn()
