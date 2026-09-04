"""Model-free Harbor agent used only to QA benchmark tasks deterministically."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, override

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Trajectory
from harbor.utils.trajectory_utils import format_trajectory_json


def build_case_trajectory(
    case: str,
    script_exit_code: int,
    *,
    commands: Sequence[str],
    mutation_paths: Sequence[str],
) -> Trajectory:
    if not case:
        raise ValueError(f"unknown QA case: {case}")
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    call_index = 0
    if mutation_paths:
        call_index += 1
        patch = "\n".join(
            (
                "*** Begin Patch",
                *(f"*** Update File: /app/{path}" for path in mutation_paths),
                "*** End Patch",
            )
        )
        calls.append(
            {
                "tool_call_id": f"qa-{call_index}",
                "function_name": "apply_patch",
                "arguments": {"patch": patch},
            }
        )
        results.append(
            {"source_call_id": f"qa-{call_index}", "content": "Done!"}
        )
    for command in commands:
        call_index += 1
        exit_code = script_exit_code if command == commands[-1] else 0
        calls.append(
            {
                "tool_call_id": f"qa-{call_index}",
                "function_name": "shell",
                "arguments": {"cmd": command},
            }
        )
        results.append(
            {
                "source_call_id": f"qa-{call_index}",
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
        )
    agent_step: dict[str, Any] = {
        "step_id": 2,
        "source": "agent",
        "message": f"Executed deterministic QA case {case}.",
        "llm_call_count": 0,
    }
    if calls:
        agent_step["tool_calls"] = calls
        agent_step["observation"] = {"results": results}
    return Trajectory.model_validate(
        {
            "schema_version": "ATIF-v1.7",
            "session_id": f"qa-{case}",
            "agent": {
                "name": "harness-qa-script",
                "version": "1.0.0",
            },
            "steps": [
                {
                    "step_id": 1,
                    "source": "user",
                    "message": "Run the deterministic benchmark QA case.",
                },
                agent_step,
            ],
            "final_metrics": {
                "total_prompt_tokens": None,
                "total_completion_tokens": None,
                "total_cached_tokens": None,
                "total_cost_usd": None,
                "total_steps": 2,
            },
        }
    )


class ScriptAgent(BaseAgent):
    SUPPORTS_ATIF = True

    def __init__(
        self,
        *args: Any,
        case: str,
        script_path: str,
        oracle_script_path: str | None = None,
        commands: list[str],
        mutation_paths: list[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if not case:
            raise ValueError(f"unknown QA case: {case}")
        if not all(isinstance(command, str) for command in commands):
            raise ValueError("QA commands must be strings")
        if not all(isinstance(path, str) for path in mutation_paths):
            raise ValueError("QA mutation paths must be strings")
        self._case = case
        self._script_path = Path(script_path)
        self._oracle_script_path = (
            Path(oracle_script_path) if oracle_script_path is not None else None
        )
        self._commands = tuple(commands)
        self._mutation_paths = tuple(mutation_paths)

    @staticmethod
    @override
    def name() -> str:
        return "harness-qa-script"

    @override
    def version(self) -> str:
        return "1.0.0"

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        return

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del instruction
        target = "/tmp/harness-qa-case.sh"
        await environment.upload_file(self._script_path, target)
        await environment.exec(f"chmod +x {target}", user="root")
        if self._oracle_script_path is not None:
            oracle_target = "/tmp/harness-qa-oracle.sh"
            await environment.upload_file(self._oracle_script_path, oracle_target)
            await environment.exec(f"chmod +x {oracle_target}", user="root")
        result = await environment.exec(f"bash {target}", timeout_sec=600)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "script-output.txt").write_text(
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}\n"
        )
        trajectory = build_case_trajectory(
            self._case,
            result.return_code,
            commands=self._commands,
            mutation_paths=self._mutation_paths,
        )
        (self.logs_dir / "trajectory.json").write_text(
            format_trajectory_json(trajectory.model_dump(mode="json"))
        )
        context.metadata = {"qa_case": self._case}
        if result.return_code != 0:
            raise RuntimeError(
                f"deterministic QA script {self._case} exited {result.return_code}"
            )
