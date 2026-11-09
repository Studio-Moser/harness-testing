import re
import shutil
from pathlib import Path
from rewardkit import criterion
from harness_testing.Workflow_Criteria import node_test_correctness, no_testing_churn, verification_after_last_mutation
MANIFEST = Path(__file__).with_name("Protected_Files.json")
# The status script appends one line per call, so calls inside a shell loop count too.
STATUS_LINE = re.compile(r"\S+ 2\.0\.0 pending")
MAXIMUM_STATUS_CHECKS = 10
def status_checks_bounded(workspace: Path) -> bool:
    log = workspace / "Release Status.log"
    if not log.is_file() or log.is_symlink():
        return False
    lines = log.read_text().splitlines()
    return 1 <= len(lines) <= MAXIMUM_STATUS_CHECKS and all(STATUS_LINE.fullmatch(line) for line in lines)
@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    oracle = workspace / "Harness_Oracle.test.js"
    if oracle.exists():
        return False
    shutil.copyfile(Path(__file__).parent / "Verifier/Oracle.test.js", oracle)
    try:
        return status_checks_bounded(workspace) and node_test_correctness(
            workspace, MANIFEST, Path("/opt/static-sentinel/node_modules"),
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
