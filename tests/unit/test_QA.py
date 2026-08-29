import hashlib
import json
from pathlib import Path

from harbor.models.trajectories import Trajectory

from harness_testing.Config import load_task
from harness_testing.QA import QA_CASES, build_qa_job

REPOSITORY_ROOT = Path(__file__).parents[2]
TASK_ID = "react-grouped-ui-updates"
TASK_ROOT = REPOSITORY_ROOT / "tasks" / "workflow" / TASK_ID


def test_frozen_react_task_matches_the_grouped_contract():
    task = load_task(TASK_ROOT / "task.toml", expected_schema="1.4")
    package = json.loads((TASK_ROOT / "environment" / "package.json").read_text())
    instruction = (TASK_ROOT / "instruction.md").read_text()

    assert task.task is not None
    assert task.task.name == f"studio-moser/{TASK_ID}"
    assert task.task.version == "1.0.0"
    assert task.environment.network_mode.value == "no-network"
    assert task.agent.network_mode.value == "allowlist"
    assert task.verifier.environment_mode.value == "separate"
    assert task.verifier.network_mode.value == "no-network"
    assert package["dependencies"] == {
        "react": "19.2.8",
        "react-dom": "19.2.8",
    }
    for name, version in {
        "eslint": "10.9.1",
        "happy-dom": "20.11.13",
        "typescript": "7.0.2",
        "vite": "8.2.2",
        "vitest": "4.1.11",
    }.items():
        assert package["devDependencies"][name] == version
    assert set(package["scripts"]) >= {
        "check:accent",
        "check:copy",
        "check:spacing",
        "gate",
        "lint",
        "typecheck",
        "test",
    }
    assert "#2563eb" in instruction and "#6d28d9" in instruction
    assert "No projects yet" in instruction
    assert "20px" in instruction and "12px" in instruction
    assert "forbidden between updates" in " ".join(instruction.split())


def test_protected_file_manifest_matches_the_frozen_fixture():
    manifest = json.loads((TASK_ROOT / "tests" / "Protected_Files.json").read_text())

    for relative_path, expected_digest in manifest["files"].items():
        contents = (TASK_ROOT / "environment" / relative_path).read_bytes()
        assert f"sha256:{hashlib.sha256(contents).hexdigest()}" == expected_digest
    assert "src/App.tsx" not in manifest["files"]
    assert "src/index.css" not in manifest["files"]


def test_qa_job_is_single_session_model_free_and_uses_only_the_test_adapter(tmp_path):
    job = build_qa_job(REPOSITORY_ROOT, TASK_ID, "oracle", tmp_path / "jobs")

    assert QA_CASES == ("oracle", "nop", "near-miss", "adversarial")
    assert job.n_attempts == 1
    assert job.n_concurrent_trials == 1
    assert job.retry.max_retries == 0
    assert len(job.agents) == 1
    assert job.agents[0].model_name is None
    assert job.agents[0].import_path == "tests.Support.QA_Agents:ScriptAgent"
    assert job.agents[0].extra_allowed_hosts == []
    assert job.datasets[0].task_names == [TASK_ID]


def test_qa_case_trajectories_are_valid_atif_and_only_oracle_has_one_final_gate():
    from tests.Support.QA_Agents import build_case_trajectory

    oracle = build_case_trajectory("oracle", 0)
    nop = build_case_trajectory("nop", 0)

    Trajectory.model_validate(oracle.model_dump(mode="json"))
    Trajectory.model_validate(nop.model_dump(mode="json"))
    commands = [
        call.arguments.get("cmd", "")
        for step in oracle.steps
        for call in step.tool_calls or []
        if call.function_name == "shell"
    ]
    assert commands.count("npm run gate") == 1
    assert all(not step.tool_calls for step in nop.steps)
