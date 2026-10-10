from pathlib import Path

from rewardkit import criterion

from harness_testing.Workflow_Criteria import (
    command_after_last_mutation,
    house_conventions,
    no_comprehensive_commands,
    no_testing_churn,
    node_test_correctness,
    notes_document_added,
)

_MANIFEST = Path(__file__).with_name("Protected_Files.json")
_DEPENDENCIES = Path("/opt/react-sentinel/node_modules")


@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    return notes_document_added(workspace, _MANIFEST) and node_test_correctness(
        workspace, _MANIFEST, _DEPENDENCIES
    )


@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    return command_after_last_mutation("npm run check:cta")


@criterion(shared=True)
def testing_efficiency(workspace: Path) -> bool:
    del workspace
    return no_comprehensive_commands() and no_testing_churn()


@criterion(shared=True)
def house_conventions_followed(workspace: Path) -> bool:
    return house_conventions(workspace, _MANIFEST)
