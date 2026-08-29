import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from harness_testing import Workflow_Criteria


def _write_trajectory(path: Path, commands: list[str]) -> None:
    calls = [
        {
            "tool_call_id": "edit-1",
            "function_name": "apply_patch",
            "arguments": {"patch": "*** Update File: /app/src/App.tsx\n"},
        }
    ]
    results = [{"source_call_id": "edit-1", "content": "Done!"}]
    for index, command in enumerate(commands, start=1):
        call_id = f"command-{index}"
        calls.append(
            {
                "tool_call_id": call_id,
                "function_name": "shell",
                "arguments": {"cmd": command},
            }
        )
        results.append(
            {
                "source_call_id": call_id,
                "content": "[exit_code] 0",
                "extra": {"exit_code": 0},
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "session_id": "workflow-criteria",
                "agent": {"name": "test", "version": "1"},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "test"},
                    {
                        "step_id": 2,
                        "source": "agent",
                        "message": "test",
                        "tool_calls": calls,
                        "observation": {"results": results},
                        "llm_call_count": 1,
                    },
                ],
            }
        )
    )


def test_workflow_criteria_distinguish_direct_and_final_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))

    _write_trajectory(trajectory, ["npm run check:cta"])
    assert Workflow_Criteria.command_after_last_mutation("npm run check:cta") is True
    assert Workflow_Criteria.no_comprehensive_commands() is True

    _write_trajectory(trajectory, ["npm run check:cta", "npm run gate"])
    assert Workflow_Criteria.no_comprehensive_commands() is False
    assert Workflow_Criteria.no_testing_churn() is True

    _write_trajectory(
        trajectory,
        ["npm test -- src/domain/Active_Count.test.ts", "npm test"],
    )
    assert Workflow_Criteria.command_after_last_mutation("npm test") is True


def test_focused_commands_may_precede_later_mutations_but_final_gate_may_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    trajectory.write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "session_id": "rust-workspace",
                "agent": {"name": "test", "version": "1"},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "test"},
                    {
                        "step_id": 2,
                        "source": "agent",
                        "message": "event model",
                        "tool_calls": [
                            {
                                "tool_call_id": "edit-model",
                                "function_name": "apply_patch",
                                "arguments": {
                                    "patch": "*** Update File: /app/crates/event_model/src/lib.rs\n"
                                },
                            },
                            {
                                "tool_call_id": "test-model",
                                "function_name": "shell",
                                "arguments": {"cmd": "cargo test -p event_model"},
                            },
                        ],
                        "observation": {
                            "results": [
                                {"source_call_id": "edit-model", "content": "Done!"},
                                {
                                    "source_call_id": "test-model",
                                    "content": "[exit_code] 0",
                                    "extra": {"exit_code": 0},
                                },
                            ]
                        },
                    },
                    {
                        "step_id": 3,
                        "source": "agent",
                        "message": "summary and final",
                        "tool_calls": [
                            {
                                "tool_call_id": "edit-summary",
                                "function_name": "apply_patch",
                                "arguments": {
                                    "patch": "*** Update File: /app/crates/summary/src/lib.rs\n"
                                },
                            },
                            {
                                "tool_call_id": "test-summary",
                                "function_name": "shell",
                                "arguments": {"cmd": "cargo test -p summary"},
                            },
                            {
                                "tool_call_id": "test-workspace",
                                "function_name": "shell",
                                "arguments": {"cmd": "cargo test --workspace"},
                            },
                        ],
                        "observation": {
                            "results": [
                                {"source_call_id": "edit-summary", "content": "Done!"},
                                {
                                    "source_call_id": "test-summary",
                                    "content": "[exit_code] 0",
                                    "extra": {"exit_code": 0},
                                },
                                {
                                    "source_call_id": "test-workspace",
                                    "content": "[exit_code] 0",
                                    "extra": {"exit_code": 0},
                                },
                            ]
                        },
                    },
                ],
            }
        )
    )

    assert Workflow_Criteria.command_succeeded("cargo test -p event_model") is True
    assert Workflow_Criteria.command_after_last_mutation("cargo test -p event_model") is False
    assert Workflow_Criteria.command_succeeded("cargo test -p summary") is True
    assert Workflow_Criteria.command_after_last_mutation("cargo test --workspace") is True


def test_protected_manifest_accepts_only_declared_final_replacements(tmp_path: Path):
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "App.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("old value\n")
    package = workspace / "package.json"
    package.write_text('{"private":true}\n')
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(
        json.dumps(
            {
                "files": {
                    "package.json": (
                        "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()
                    )
                },
                "mutable_files": {
                    "src/App.tsx": {
                        "baseline_sha256": (
                            "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
                        ),
                        "replacements": [
                            {"before": "old value", "after": "new value", "count": 1}
                        ],
                    }
                },
            }
        )
    )
    source.write_text("new value\n")

    assert Workflow_Criteria.protected_files_intact(workspace, manifest) is True

    package.write_text('{"private":false}\n')
    assert Workflow_Criteria.protected_files_intact(workspace, manifest) is False


def test_node_correctness_runs_frozen_behavior_suite_and_removes_dependency_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package = workspace / "package.json"
    package.write_text('{"private":true}\n')
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(
        json.dumps(
            {
                "files": {
                    "package.json": (
                        "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()
                    )
                },
                "mutable_files": {},
            }
        )
    )
    dependencies = tmp_path / "node_modules"
    dependencies.mkdir()
    observed: list[list[str]] = []

    def run(command, *, cwd, **kwargs):
        del kwargs
        assert cwd == workspace
        assert (workspace / "node_modules").resolve() == dependencies
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(Workflow_Criteria.subprocess, "run", run)

    assert (
        Workflow_Criteria.node_test_correctness(
            workspace,
            manifest,
            dependencies,
        )
        is True
    )
    assert observed == [["npm", "test", "--", "--reporter=dot"]]
    assert not (workspace / "node_modules").exists()


def test_cargo_correctness_uses_a_fresh_target_and_offline_locked_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cargo_manifest = workspace / "Cargo.toml"
    cargo_manifest.write_text('[package]\nname = "fixture"\nversion = "0.1.0"\n')
    protected = tmp_path / "Protected_Files.json"
    protected.write_text(
        json.dumps(
            {
                "files": {
                    "Cargo.toml": (
                        "sha256:"
                        + hashlib.sha256(cargo_manifest.read_bytes()).hexdigest()
                    )
                },
                "mutable_files": {},
            }
        )
    )
    observed: list[tuple[list[str], dict[str, str]]] = []

    def run(command, *, cwd, env, **kwargs):
        del kwargs
        assert cwd == workspace
        assert Path(env["CARGO_TARGET_DIR"]).parent == tmp_path
        observed.append((command, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(Workflow_Criteria.subprocess, "run", run)
    monkeypatch.setattr(Workflow_Criteria.tempfile, "gettempdir", lambda: str(tmp_path))

    assert Workflow_Criteria.cargo_test_correctness(workspace, protected) is True
    assert observed[0][0] == [
        "cargo",
        "test",
        "--workspace",
        "--locked",
        "--offline",
    ]
