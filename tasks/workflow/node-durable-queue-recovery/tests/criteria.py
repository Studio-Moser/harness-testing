from pathlib import Path

from rewardkit import criterion

from harness_testing.Workflow_Criteria import (
    no_testing_churn,
    node_test_correctness,
    verification_after_last_mutation,
)

MANIFEST = Path(__file__).with_name("Protected_Files.json")


@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    return node_test_correctness(
        workspace, MANIFEST, Path("/opt/static-sentinel/node_modules")
    )


@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    return verification_after_last_mutation()


@criterion(shared=True)
def testing_efficiency(workspace: Path) -> bool:
    del workspace
    return no_testing_churn()
