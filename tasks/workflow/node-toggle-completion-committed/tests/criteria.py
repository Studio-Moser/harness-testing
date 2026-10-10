import shutil
from pathlib import Path
from rewardkit import criterion
from harness_testing.Workflow_Criteria import house_conventions, node_test_correctness, no_testing_churn, notes_document_added, verification_after_last_mutation
MANIFEST = Path(__file__).with_name("Protected_Files.json")
# The stub is the one fixture file the manifest leaves free to change.
BASELINE = ("src/Completion.js",)
@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    oracle = workspace / "Harness_Oracle.test.js"
    if oracle.exists() or not notes_document_added(workspace, MANIFEST, BASELINE):
        return False
    shutil.copyfile(Path(__file__).parent / "Verifier/Oracle.test.js", oracle)
    try:
        return node_test_correctness(workspace, MANIFEST, Path("/opt/static-sentinel/node_modules"),
                                     test_files=["test/Behavior.test.js", oracle.name])
    finally:
        oracle.unlink(missing_ok=True)
@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    return verification_after_last_mutation()
@criterion(shared=True)
def testing_efficiency(workspace: Path) -> bool:
    del workspace
    return no_testing_churn()
@criterion(shared=True)
def house_conventions_followed(workspace: Path) -> bool:
    return house_conventions(workspace, MANIFEST, BASELINE)
