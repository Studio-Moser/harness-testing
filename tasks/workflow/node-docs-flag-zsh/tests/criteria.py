import json
import os
import re
import shutil
from pathlib import Path
from rewardkit import criterion
from harness_testing.Trajectory_Events import _content_text
from harness_testing.Workflow_Criteria import node_test_correctness, no_testing_churn, verification_after_last_mutation
MANIFEST = Path(__file__).with_name("Protected_Files.json")
# zsh aborts a command whose unquoted glob matches nothing, such as grep --include=*.md.
# Match zsh's own error ("zsh:1: no matches found: --include=*.md"), not a hook that warns about it.
ABORTED_GLOB = re.compile(r"\bzsh(?::\d+)?: no matches found: ")
def no_aborted_globs() -> bool:
    try:
        trajectory = json.loads(Path(os.environ.get("HARNESS_TEST_TRAJECTORY", "/logs/agent/trajectory.json")).read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return not any(
        ABORTED_GLOB.search(_content_text(result))
        for step in trajectory.get("steps", [])
        for result in (step.get("observation") or {}).get("results", [])
    )
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
    return no_testing_churn() and no_aborted_globs()
