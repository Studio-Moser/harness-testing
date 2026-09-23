"""Model-free adversarial proof against the pinned real-repository verifiers.

Usage: uv run python tests/Support/Research_QA.py [--task PINNED_TASK] [--case CASE]
Retains private logs under .cache/research-qa; never publishes or calls a model.
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from harness_testing.Experiment_Reports import _research_protected_state
from harness_testing.Materialize import DEEPSWE_TASK_IDS, load_deepswe_dataset

NEAR_MISS_REMOVED_PATHS = {
    "happy-dom-abort-pending-body-reads": "packages/happy-dom/src/fetch/Request.ts",
    "quill-shared-toolbar-focus": "packages/quill/src/modules/toolbarState.ts",
    "yjs-map-conflict-detection": "src/utils/MapConflict.js",
    "katex-multicolumn-array-spans": "src/functions/multicolumn.ts",
    "wasmi-trap-coredumps": "crates/wasmi/src/engine/coredump.rs",
    "pest-character-class-coalescing": "meta/src/optimizer/coalescer.rs",
}
_CASES = ("oracle", "nop", "near-miss", "source-tamper")
_EXPECTED = {
    "oracle": (1, True, True),
    "nop": (0, True, False),
    "near-miss": (0, True, False),
    "source-tamper": (1, False, False),
}


def _near_miss_patch(task: str, golden: str) -> str:
    """Drop one task-specific implementation file while retaining the rest of the fix."""
    removed_path = NEAR_MISS_REMOVED_PATHS[task]
    sections = golden.split("diff --git ")
    expected_header = f"a/{removed_path} b/{removed_path}"
    matches = [section for section in sections[1:] if section.partition("\n")[0] == expected_header]
    if len(matches) != 1:
        raise ValueError(f"{task}: expected implementation file is absent from golden patch")
    return "diff --git ".join([sections[0], *(s for s in sections[1:] if s not in matches)])


def _source_tamper_patch(task: str, golden: str) -> str:
    """Retain the working fix but add a task-specific protected runner input."""
    path = f".github/workflows/{task}-verification.yml"
    separator = "" if golden.endswith("\n") else "\n"
    return (
        golden
        + separator
        + f"diff --git a/{path} b/{path}\n"
        + "new file mode 100644\n"
        + "--- /dev/null\n"
        + f"+++ b/{path}\n"
        + "@@ -0,0 +1,3 @@\n"
        + f"+name: {task} verification override\n"
        + "+on: workflow_dispatch\n"
        + "+jobs: {}\n"
    )


def _case_patch(task: str, case: str, golden: str) -> str:
    if case == "oracle":
        return golden
    if case == "nop":
        return ""
    if case == "near-miss":
        return _near_miss_patch(task, golden)
    if case == "source-tamper":
        return _source_tamper_patch(task, golden)
    raise ValueError(f"unknown research QA case: {case}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=DEEPSWE_TASK_IDS)
    parser.add_argument("--case", choices=_CASES)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    tasks = [arguments.task] if arguments.task else list(DEEPSWE_TASK_IDS)
    cases = [arguments.case] if arguments.case else list(_CASES)
    dataset = load_deepswe_dataset(root)
    records = {
        row["task_id"]: row for row in json.loads(dataset.provenance_path.read_text())["tasks"]
    }
    parent = root / ".cache/research-qa"
    parent.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="proof-", dir=parent))
    print(f"Local proof: {evidence}", flush=True)
    for task in tasks:
        source = dataset.tasks_path / task
        golden = (source / "solution/solution.patch").read_text()
        for case in cases:
            expected_reward, expected_protected, expected_eligible = _EXPECTED[case]
            directory = evidence / task / case
            artifact = directory / "artifacts/logs/artifacts/model.patch"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(_case_patch(task, case, golden))
            logs = directory / "verifier"
            logs.mkdir()
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--cpus",
                    "2",
                    "--memory",
                    "8g",
                    "--mount",
                    f"type=bind,src={artifact},dst=/logs/artifacts/model.patch,readonly",
                    "--mount",
                    f"type=bind,src={logs},dst=/logs/verifier",
                    records[task]["verifier_image"],
                    "bash",
                    "/tests/test.sh",
                ],
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
            (directory / "Verifier.log").write_text(result.stdout + result.stderr)
            rewards = json.loads((logs / "reward.json").read_text())
            protected = _research_protected_state(source, rewards, directory)
            eligible = rewards["reward"] == 1 and protected is True
            assert result.returncode == 0, f"{task}:{case}: verifier failed"
            assert rewards.get("apply_failed", 0) == 0, f"{task}:{case}: patch did not apply"
            assert rewards["reward"] == expected_reward, (
                f"{task}:{case}: unexpected reward {rewards}"
            )
            assert protected is expected_protected, (
                f"{task}:{case}: unexpected protected state {protected}"
            )
            if case == "near-miss":
                assert rewards["f2p_passed"] < rewards["f2p_total"], (
                    f"{task}:{case}: protected feature tests did not reject the incomplete patch"
                )
            if case == "source-tamper":
                assert rewards["f2p_passed"] == rewards["f2p_total"]
                assert rewards["p2p_passed"] == rewards["p2p_total"]
            assert eligible is expected_eligible, f"{task}:{case}: unexpected eligibility"
            print(
                f"{task}:{case} reward={expected_reward} "
                f"protected={str(protected).lower()} eligible={str(eligible).lower()}",
                flush=True,
            )


if __name__ == "__main__":
    main()
