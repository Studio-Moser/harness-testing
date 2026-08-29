import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
TASK_ROOT = REPOSITORY_ROOT / "tasks" / "workflow" / "react-grouped-ui-updates"


@pytest.fixture(scope="module")
def criteria() -> ModuleType:
    path = TASK_ROOT / "tests" / "criteria.py"
    spec = importlib.util.spec_from_file_location("sentinel_criteria", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_trajectory(
    path: Path,
    command: str,
    *,
    exit_code: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "session_id": "criterion-unit",
                "agent": {"name": "claude-code", "version": "2.1.236"},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "test"},
                    {
                        "step_id": 2,
                        "source": "agent",
                        "message": "test",
                        "tool_calls": [
                            {
                                "tool_call_id": "call-1",
                                "function_name": "Bash",
                                "arguments": {"command": command},
                            }
                        ],
                        "observation": {
                            "results": [
                                {
                                    "source_call_id": "call-1",
                                    "content": (
                                        "[stdout]\ncompleted"
                                        if exit_code == 0
                                        else f"[exit_code] {exit_code}"
                                    ),
                                    "extra": {
                                        "tool_result_metadata": {
                                            "tool_use_result": {"exitCode": exit_code}
                                        }
                                    },
                                }
                            ]
                        },
                        "llm_call_count": 1,
                    },
                ],
            }
        )
    )


def test_compound_prefixed_gate_uses_real_claude_status(
    criteria: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    trajectory = tmp_path / "trajectory.json"
    _write_trajectory(trajectory, "cd /app && npm run gate", exit_code=0)
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))

    assert criteria._final_gate_workflow() is True
    assert criteria._no_testing_churn() is True


def test_compound_gate_then_redirection_is_rejected(
    criteria: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    trajectory = tmp_path / "trajectory.json"
    _write_trajectory(
        trajectory,
        "npm run gate && printf x >> src/App.tsx",
        exit_code=0,
    )
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))

    assert criteria._final_gate_workflow() is False
    assert criteria._no_testing_churn() is False


def test_mutable_files_allow_only_the_three_declared_substitutions(
    criteria: ModuleType, tmp_path: Path
):
    workspace = tmp_path / "workspace"
    shutil.copytree(TASK_ROOT / "environment", workspace)
    app = workspace / "src" / "App.tsx"
    css = workspace / "src" / "index.css"
    app.write_text(app.read_text().replace("No projects found", "No projects yet"))
    css.write_text(
        css.read_text()
        .replace("--accent: #2563eb", "--accent: #6d28d9")
        .replace("--card-gap: 20px", "--card-gap: 12px")
    )

    assert criteria._protected_files_intact(workspace) is True
    assert not (workspace / "node_modules").exists()
    assert criteria._sentinel_correctness(workspace) is True

    app.write_text(
        "import './App.css'\n\n"
        "export default function App() { return <h2>No projects yet</h2> }\n"
    )

    assert criteria._protected_files_intact(workspace) is False
    assert criteria._sentinel_correctness(workspace) is False
