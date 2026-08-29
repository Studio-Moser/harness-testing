import hashlib
import json
from pathlib import Path

import pytest
from harbor.models.trajectories import Trajectory

from harness_testing import QA
from harness_testing.Config import load_task
from harness_testing.QA import QA_CASES, build_qa_job, task_ids_for_pack

REPOSITORY_ROOT = Path(__file__).parents[2]
TASK_ID = "react-grouped-ui-updates"
TASK_ROOT = REPOSITORY_ROOT / "tasks" / "workflow" / TASK_ID


def test_pack_task_ids_are_sorted_and_frozen_to_declared_tasks():
    workflow = task_ids_for_pack(REPOSITORY_ROOT, "workflow")
    contract = task_ids_for_pack(REPOSITORY_ROOT, "contract")

    assert workflow == tuple(sorted(workflow))
    assert contract == tuple(sorted(contract))
    assert TASK_ID in workflow
    assert "pm-cross-vendor-implementation" in contract


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
    workspace_artifact = next(
        artifact
        for artifact in task.artifacts
        if not isinstance(artifact, str) and artifact.source == "/app"
    )
    assert workspace_artifact.exclude == [".git", "node_modules", "target"]
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


def test_verifier_installs_a_frozen_subset_for_the_real_behavior_test():
    environment_package = json.loads(
        (TASK_ROOT / "environment" / "package.json").read_text()
    )
    verifier_package = json.loads(
        (TASK_ROOT / "tests" / "Verifier" / "package.json").read_text()
    )
    available = {
        **environment_package["dependencies"],
        **environment_package["devDependencies"],
    }
    expected_names = {
        "@vitejs/plugin-react",
        "happy-dom",
        "react",
        "react-dom",
        "vite",
        "vitest",
    }

    assert verifier_package["dependencies"] == {
        name: available[name] for name in sorted(expected_names)
    }
    dockerfile = (TASK_ROOT / "tests" / "Dockerfile").read_text()
    assert "npm ci --ignore-scripts --no-audit --no-fund" in dockerfile
    assert "/opt/react-sentinel" in dockerfile


def test_protected_file_manifest_matches_the_frozen_fixture():
    manifest = json.loads((TASK_ROOT / "tests" / "Protected_Files.json").read_text())

    for relative_path, expected_digest in manifest["files"].items():
        contents = (TASK_ROOT / "environment" / relative_path).read_bytes()
        assert f"sha256:{hashlib.sha256(contents).hexdigest()}" == expected_digest
    assert "src/App.tsx" not in manifest["files"]
    assert "src/index.css" not in manifest["files"]
    assert set(manifest["mutable_files"]) == {"src/App.tsx", "src/index.css"}
    for relative_path, rule in manifest["mutable_files"].items():
        contents = (TASK_ROOT / "environment" / relative_path).read_bytes()
        assert f"sha256:{hashlib.sha256(contents).hexdigest()}" == rule[
            "baseline_sha256"
        ]


def test_qa_job_is_single_session_model_free_and_uses_only_the_test_adapter(tmp_path):
    job = build_qa_job(REPOSITORY_ROOT, TASK_ID, "oracle", tmp_path / "jobs")

    assert QA_CASES == (
        "oracle",
        "nop",
        "near-miss",
        "adversarial",
        "source-tamper",
    )
    assert job.n_attempts == 1
    assert job.n_concurrent_trials == 1
    assert job.retry.max_retries == 0
    assert len(job.agents) == 1
    assert job.agents[0].model_name is None
    assert job.agents[0].import_path == "tests.Support.QA_Agents:ScriptAgent"
    assert job.agents[0].extra_allowed_hosts == []
    assert job.agents[0].kwargs["commands"] == [
        "npm run check:accent",
        "npm run check:copy",
        "npm run check:spacing",
        "npm run gate",
    ]
    assert job.agents[0].kwargs["mutation_paths"] == [
        "src/App.tsx",
        "src/index.css",
    ]
    assert job.datasets[0].task_names == [TASK_ID]


def test_qa_job_loads_task_specific_polish_evidence(tmp_path):
    job = build_qa_job(
        REPOSITORY_ROOT,
        "react-accent-polish",
        "oracle",
        tmp_path / "jobs",
    )

    assert job.agents[0].kwargs["commands"] == ["npm run check:cta"]
    assert job.agents[0].kwargs["mutation_paths"] == ["src/index.css"]
    assert job.agents[0].kwargs["oracle_script_path"] is None


def test_contract_tamper_case_uploads_the_oracle_before_tampering(tmp_path):
    job = build_qa_job(
        REPOSITORY_ROOT,
        "pm-cross-vendor-implementation",
        "source-tamper",
        tmp_path / "jobs",
    )

    assert job.agents[0].kwargs["oracle_script_path"].endswith("solution/solve.sh")


def test_qa_discovers_contract_tasks_and_uses_the_contract_dataset(tmp_path):
    task_root = tmp_path / "tasks" / "contract" / "contract-sample"
    task_root.mkdir(parents=True)
    (task_root / "task.toml").write_text("schema_version = \"1.4\"\n")
    tests_root = task_root / "tests"
    tests_root.mkdir()
    (tests_root / "QA.json").write_text(
        json.dumps(
            {
                "cases": {
                    "oracle": {
                        "commands": [],
                        "mutation_paths": ["Harness_Result.json"],
                        "expected": {"reward": 1, "workflow": 1, "efficiency": 1},
                        "script": "solution/solve.sh",
                    }
                }
            }
        )
    )
    solution = task_root / "solution"
    solution.mkdir()
    (solution / "solve.sh").write_text("#!/bin/sh\n")

    job = build_qa_job(tmp_path, "contract-sample", "oracle", tmp_path / "jobs")

    assert job.datasets[0].path == (tmp_path / "tasks" / "contract").resolve()
    assert job.datasets[0].task_names == ["contract-sample"]


@pytest.mark.parametrize(
    ("task_id", "expected"),
    [
        ("static-pricing-copy-polish", ("node", "verifier")),
        ("rust-quoted-value-parser", ("rust", "verifier")),
    ],
)
def test_qa_refreshes_only_the_task_runtime_and_verifier_images(
    task_id: str,
    expected: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
):
    checked: list[str] = []

    def image_is_current(root: Path, image: str) -> bool:
        assert root == REPOSITORY_ROOT
        checked.append(image)
        return True

    monkeypatch.setattr(QA, "image_is_current", image_is_current)

    QA._ensure_base_images(REPOSITORY_ROOT, task_id)

    assert tuple(checked) == expected


def test_qa_case_trajectories_are_valid_atif_and_only_oracle_has_one_final_gate():
    from tests.Support.QA_Agents import build_case_trajectory

    oracle = build_case_trajectory(
        "oracle",
        0,
        commands=("npm run check:accent", "npm run gate"),
        mutation_paths=("src/index.css",),
    )
    nop = build_case_trajectory("nop", 0, commands=(), mutation_paths=())

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
