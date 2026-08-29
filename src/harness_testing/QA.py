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
_EFFICIENCY_AUDITS = {
    "react-grouped-ui-updates": "Grouped_Premature.json",
    "react-accent-polish": "Polish_Unnecessary_Gate.json",
    "static-grouped-page-updates": "Static_Grouped_Premature.json",
}


def task_ids_for_pack(root: Path, pack: str) -> tuple[str, ...]:
    if pack not in {"contract", "workflow"}:
        raise ValueError(f"unknown QA pack: {pack}")
    pack_root = root / "tasks" / pack
    if not pack_root.is_dir():
        raise ValueError(f"QA pack does not exist: {pack}")
    return tuple(
        path.name
        for path in sorted(pack_root.iterdir())
        if path.is_dir() and (path / "task.toml").is_file()
    )


def _task_root(root: Path, task_id: str) -> Path:
    matches = [
        root / "tasks" / pack / task_id
        for pack in ("contract", "workflow")
        if (root / "tasks" / pack / task_id / "task.toml").is_file()
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown or ambiguous benchmark task: {task_id}")
    return matches[0]


def _case_spec(root: Path, task_id: str, case: str) -> dict[str, object]:
    path = _task_root(root, task_id) / "tests" / "QA.json"
    try:
        document = json.loads(path.read_text())
        spec = document["cases"][case]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid QA case {case} for {task_id}: {error}") from error
    if not isinstance(spec, dict):
        raise ValueError(f"invalid QA case {case} for {task_id}: expected an object")
    commands = spec.get("commands")
    mutation_paths = spec.get("mutation_paths")
    expected = spec.get("expected")
    run_oracle_first = spec.get("run_oracle_first", False)
    if (
        not isinstance(commands, list)
        or not all(isinstance(command, str) for command in commands)
        or not isinstance(mutation_paths, list)
        or not all(isinstance(path, str) for path in mutation_paths)
        or not isinstance(expected, dict)
        or not isinstance(run_oracle_first, bool)
        or set(expected) != {"reward", "workflow", "efficiency"}
        or not all(isinstance(score, (int, float)) for score in expected.values())
    ):
        raise ValueError(f"invalid QA evidence for {task_id}:{case}")
    return spec


def _case_script(root: Path, task_id: str, case: str, spec: dict[str, object]) -> Path:
    configured = spec.get("script")
    if not isinstance(configured, str):
        raise ValueError(f"invalid QA script for {task_id}:{case}")
    if configured.startswith("@shared/"):
        filename = configured.removeprefix("@shared/")
        if Path(filename).name != filename:
            raise ValueError(f"unsafe shared QA script for {task_id}:{case}")
        script = root / "tests" / "Support" / "QA_Cases" / filename
    else:
        task_root = _task_root(root, task_id).resolve()
        script = (task_root / configured).resolve()
        if not script.is_relative_to(task_root):
            raise ValueError(f"unsafe task QA script for {task_id}:{case}")
    if not script.is_file():
        raise ValueError(f"QA script is missing: {script}")
    return script.resolve()


def build_qa_job(root: Path, task_id: str, case: str, jobs_dir: Path) -> JobConfig:
    root = root.resolve()
    _task_root(root, task_id)
    spec = _case_spec(root, task_id, case)
    script = _case_script(root, task_id, case, spec)
    oracle_script = (
        (_task_root(root, task_id) / "solution" / "solve.sh").resolve()
        if spec.get("run_oracle_first") is True
        else None
    )
    if oracle_script is not None and not oracle_script.is_file():
        raise ValueError(f"QA oracle script is missing: {oracle_script}")
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
                    "kwargs": {
                        "case": case,
                        "script_path": str(script),
                        "oracle_script_path": (
                            str(oracle_script) if oracle_script is not None else None
                        ),
                        "commands": spec["commands"],
                        "mutation_paths": spec["mutation_paths"],
                    },
                }
            ],
            "datasets": [
                {
                    "path": str(_task_root(root, task_id).parent.resolve()),
                    "task_names": [task_id],
                }
            ],
        }
    )


def _ensure_base_images(root: Path, task_id: str) -> None:
    task_root = _task_root(root, task_id)
    runtime = "rust" if (task_root / "environment" / "Cargo.toml").is_file() else "node"
    selected: list[str] = []
    for image in (runtime, "verifier"):
        if not image_is_current(root, image):
            selected.append(image)
    if selected:
        build_images(root, selected)


def _score_document(jobs_dir: Path) -> tuple[dict[str, float], Path]:
    reward_paths = sorted(jobs_dir.rglob("reward.json"))
    if len(reward_paths) != 1:
        exception_paths = sorted(jobs_dir.rglob("exception.txt"))
        script_outputs = sorted(jobs_dir.rglob("script-output.txt"))
        diagnostics = [
            *(path.read_text() for path in exception_paths[-1:]),
            *(path.read_text() for path in script_outputs[-1:]),
        ]
        details = "".join(f"\n{diagnostic}" for diagnostic in diagnostics)
        raise RuntimeError(
            f"expected one Harbor reward.json, found {len(reward_paths)} in {jobs_dir}"
            f"{details}"
        )
    raw = json.loads(reward_paths[0].read_text())
    scores = {
        name: float(raw[name]) for name in ("reward", "workflow", "efficiency")
    }
    return scores, reward_paths[0]


def _assert_scores(
    task_id: str,
    case: str,
    scores: dict[str, float],
    expected: dict[str, object],
    reward_path: Path,
    jobs_dir: Path,
) -> None:
    if scores != expected:
        diagnostic_names = {"Events.jsonl", "Harness_Result.json", "manifest.json"}
        diagnostics = [
            f"\n--- {path.relative_to(jobs_dir)} ---\n{path.read_text(errors='replace')}"
            for path in sorted(jobs_dir.rglob("*"))
            if path.is_file() and path.name in diagnostic_names
        ]
        raise RuntimeError(
            f"QA case {task_id}:{case} returned {scores}; expected {expected}\n"
            f"{reward_path.read_text()}{''.join(diagnostics)}"
        )


def _assert_efficiency_audit(
    root: Path,
    task_id: str,
    jobs_dir: Path,
    oracle_scores: dict[str, float],
) -> None:
    if oracle_scores["reward"] != 1.0:
        raise RuntimeError("efficiency audit requires a correct oracle workspace")
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
        root / "tests" / "Fixtures" / "ATIF" / _EFFICIENCY_AUDITS[task_id]
    )
    try:
        rewards = discover(
            root
            / "tasks"
            / _task_root(root, task_id).relative_to(root)
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
            "policy trajectory must preserve proven correctness and fail efficiency; "
            f"received efficiency={efficiency.score}"
        )


def run_task_qa(root: Path, task_id: str, case: str) -> dict[str, float]:
    root = root.resolve()
    if case not in QA_CASES:
        raise ValueError(f"unknown QA case: {case}")
    spec = _case_spec(root, task_id, case)
    _ensure_base_images(root, task_id)
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
        scores, reward_path = _score_document(jobs_dir)
        _assert_scores(
            task_id,
            case,
            scores,
            spec["expected"],
            reward_path,
            jobs_dir,
        )
        if case == "oracle" and task_id in _EFFICIENCY_AUDITS:
            _assert_efficiency_audit(root, task_id, jobs_dir, scores)
        return scores
