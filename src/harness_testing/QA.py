"""Run model-free Harbor task QA cases and enforce their expected rewards."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml
from harbor.models.job.config import JobConfig
from rewardkit import discover

from harness_testing.Materialize import build_images, image_is_current

QA_CASES = ("oracle", "nop", "near-miss", "adversarial", "source-tamper")
_PREMATURE_SENTINEL_TASK = "react-grouped-ui-updates"
_EXPECTED_SCORES = {
    "oracle": {"reward": 1.0, "workflow": 1.0, "efficiency": 1.0},
    "nop": {"reward": 0.0, "workflow": 0.0, "efficiency": 1.0},
    "near-miss": {"reward": 0.0, "workflow": 0.0, "efficiency": 1.0},
    "adversarial": {"reward": 0.0, "workflow": 1.0, "efficiency": 1.0},
    "source-tamper": {"reward": 0.0, "workflow": 1.0, "efficiency": 1.0},
}
_CASE_SCRIPTS = {
    "nop": "Nop.sh",
    "near-miss": "Near_Miss.sh",
    "adversarial": "Adversarial.sh",
    "source-tamper": "Source_Tamper.sh",
}


def _task_root(root: Path, task_id: str) -> Path:
    task_root = root / "tasks" / "workflow" / task_id
    if not (task_root / "task.toml").is_file():
        raise ValueError(f"unknown workflow task: {task_id}")
    return task_root


def _case_script(root: Path, task_id: str, case: str) -> Path:
    if case == "oracle":
        script = _task_root(root, task_id) / "solution" / "solve.sh"
    else:
        filename = _CASE_SCRIPTS.get(case)
        if filename is None:
            raise ValueError(f"unknown QA case: {case}")
        script = root / "tests" / "Support" / "QA_Cases" / filename
    if not script.is_file():
        raise ValueError(f"QA script is missing: {script}")
    return script.resolve()


def build_qa_job(root: Path, task_id: str, case: str, jobs_dir: Path) -> JobConfig:
    root = root.resolve()
    _task_root(root, task_id)
    script = _case_script(root, task_id, case)
    return JobConfig.model_validate(
        {
            "job_name": f"qa-{task_id}-{case}",
            "jobs_dir": str(jobs_dir.resolve()),
            "n_attempts": 1,
            "n_concurrent_trials": 1,
            "quiet": True,
            "retry": {"max_retries": 0},
            "environment": {
                "type": "docker",
                "force_build": False,
                "delete": True,
            },
            "agents": [
                {
                    "import_path": "tests.Support.QA_Agents:ScriptAgent",
                    "model_name": None,
                    "extra_allowed_hosts": [],
                    "kwargs": {"case": case, "script_path": str(script)},
                }
            ],
            "datasets": [
                {
                    "path": str((root / "tasks" / "workflow").resolve()),
                    "task_names": [task_id],
                }
            ],
        }
    )


def _ensure_base_images(root: Path) -> None:
    selected: list[str] = []
    for image in ("node", "verifier"):
        if not image_is_current(root, image):
            selected.append(image)
    if selected:
        build_images(root, selected)


def _score_document(jobs_dir: Path) -> tuple[dict[str, float], Path]:
    reward_paths = sorted(jobs_dir.rglob("reward.json"))
    if len(reward_paths) != 1:
        exception_paths = sorted(jobs_dir.rglob("exception.txt"))
        details = (
            f"\n{exception_paths[-1].read_text()}" if exception_paths else ""
        )
        raise RuntimeError(
            f"expected one Harbor reward.json, found {len(reward_paths)} in {jobs_dir}"
            f"{details}"
        )
    raw = json.loads(reward_paths[0].read_text())
    scores = {
        name: float(raw[name]) for name in ("reward", "workflow", "efficiency")
    }
    return scores, reward_paths[0]


def _assert_scores(case: str, scores: dict[str, float]) -> None:
    expected = _EXPECTED_SCORES[case]
    if scores != expected:
        raise RuntimeError(f"QA case {case} returned {scores}; expected {expected}")


def _assert_premature_trajectory(
    root: Path, jobs_dir: Path, oracle_scores: dict[str, float]
) -> None:
    if oracle_scores["reward"] != 1.0:
        raise RuntimeError("premature-trajectory audit requires a correct oracle workspace")
    workspaces = sorted(
        path
        for path in jobs_dir.rglob("workspace")
        if path.is_dir() and path.parent.name == "artifacts"
    )
    if len(workspaces) != 1:
        raise RuntimeError(
            f"expected one transferred oracle workspace, found {len(workspaces)}"
        )
    variable = "HARNESS_TEST_TRAJECTORY"
    previous = os.environ.get(variable)
    os.environ[variable] = str(
        root / "tests" / "Fixtures" / "ATIF" / "Grouped_Premature.json"
    )
    try:
        rewards = discover(
            root
            / "tasks"
            / "workflow"
            / _PREMATURE_SENTINEL_TASK
            / "tests",
            workspace=workspaces[0],
        )
        efficiency = next(reward for reward in rewards if reward.name == "efficiency")
        efficiency.run()
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
    if efficiency.score != 0.0:
        raise RuntimeError(
            "premature trajectory must preserve proven correctness and fail efficiency; "
            f"received efficiency={efficiency.score}"
        )


def run_task_qa(root: Path, task_id: str, case: str) -> dict[str, float]:
    root = root.resolve()
    if case not in QA_CASES:
        raise ValueError(f"unknown QA case: {case}")
    _ensure_base_images(root)
    with tempfile.TemporaryDirectory(prefix="harness-task-qa-") as temporary:
        temporary_root = Path(temporary)
        jobs_dir = temporary_root / "jobs"
        job = build_qa_job(root, task_id, case, jobs_dir)
        config_path = temporary_root / "Job.yaml"
        config_path.write_text(
            yaml.safe_dump(job.model_dump(mode="json", exclude_none=True), sort_keys=False)
        )
        environment = os.environ.copy()
        current_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{root}{os.pathsep}{current_pythonpath}" if current_pythonpath else str(root)
        )
        subprocess.run(
            ["harbor", "run", "--config", str(config_path), "--yes"],
            cwd=root,
            env=environment,
            check=True,
        )
        scores, _ = _score_document(jobs_dir)
        _assert_scores(case, scores)
        if case == "oracle" and task_id == _PREMATURE_SENTINEL_TASK:
            _assert_premature_trajectory(root, jobs_dir, scores)
        return scores
