import shutil
from pathlib import Path
from rewardkit import criterion
from harness_testing.Workflow_Criteria import node_test_correctness, no_testing_churn, verification_after_last_mutation
MANIFEST = Path(__file__).with_name("Protected_Files.json")
@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    oracle = workspace / "Harness_Oracle.test.js"
    if oracle.exists():
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
