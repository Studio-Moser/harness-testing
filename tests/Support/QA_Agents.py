"""Model-free Harbor agent used only to QA benchmark tasks deterministically."""

from __future__ import annotations

from pathlib import Path
from typing import Any, override

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Trajectory
from harbor.utils.trajectory_utils import format_trajectory_json

_PATCHES = {
    "oracle": """*** Begin Patch
*** Update File: /app/src/App.tsx
*** Update File: /app/src/index.css
*** End Patch""",
    "near-miss": """*** Begin Patch
*** Update File: /app/src/index.css
*** End Patch""",
    "adversarial": """*** Begin Patch
*** Update File: /app/src/App.tsx
*** Update File: /app/src/index.css
*** Update File: /app/src/App.test.tsx
*** End Patch""",
}

_COMMANDS = {
    "oracle": (
        "npm run check:accent",
        "npm run check:copy",
        "npm run check:spacing",
        "npm run gate",
    ),
    "nop": (),
    "near-miss": ("npm run check:accent",),
    "adversarial": ("npm run gate",),
}


def build_case_trajectory(case: str, script_exit_code: int) -> Trajectory:
    if case not in _COMMANDS:
        raise ValueError(f"unknown QA case: {case}")
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    call_index = 0
    if case in _PATCHES:
        call_index += 1
        calls.append(
            {
                "tool_call_id": f"qa-{call_index}",
                "function_name": "apply_patch",
                "arguments": {"patch": _PATCHES[case]},
            }
        )
        results.append(
            {"source_call_id": f"qa-{call_index}", "content": "Done!"}
        )
    for command in _COMMANDS[case]:
        call_index += 1
        exit_code = script_exit_code if command == _COMMANDS[case][-1] else 0
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
                "content": f"exit_code: {exit_code}",
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

    def __init__(self, *args: Any, case: str, script_path: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if case not in _COMMANDS:
            raise ValueError(f"unknown QA case: {case}")
        self._case = case
        self._script_path = Path(script_path)

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
        result = await environment.exec(f"bash {target}", timeout_sec=600)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "script-output.txt").write_text(
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}\n"
        )
        trajectory = build_case_trajectory(self._case, result.return_code)
        (self.logs_dir / "trajectory.json").write_text(
            format_trajectory_json(trajectory.model_dump(mode="json"))
        )
        context.metadata = {"qa_case": self._case}
        if result.return_code != 0:
            raise RuntimeError(
                f"deterministic QA script {self._case} exited {result.return_code}"
            )
