from pathlib import Path
import os
import subprocess
from rewardkit import criterion
from harness_testing.Workflow_Criteria import protected_files_intact, python_script_after_last_mutation, no_testing_churn
MANIFEST=Path(__file__).with_name('Protected_Files.json')
@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    if not protected_files_intact(workspace,MANIFEST): return False
    result=subprocess.run(['python',str(workspace/'Visual_Check.py')],cwd=workspace,env={**os.environ,'VISUAL_OUTPUT_DIRECTORY':'/logs/verifier/visual'},capture_output=True,timeout=90,check=False)
    return result.returncode==0 and protected_files_intact(workspace,MANIFEST)
@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    return python_script_after_last_mutation('Visual_Check.py')
@criterion(shared=True)
def testing_efficiency(workspace: Path) -> bool:
    del workspace
    return no_testing_churn()
