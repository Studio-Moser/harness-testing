import asyncio
import json
from pathlib import Path

import pytest

from harness_testing.Codex_Agent import HarnessCodex
from harness_testing.Trajectory_Events import result_success


def test_codex_inventory_is_recorded_after_effective_config_upload(tmp_path: Path):
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
    )
    calls: list[tuple[str, object]] = []

    async def fake_upload(environment, **kwargs):
        calls.append(("upload", kwargs))

    async def fake_exec(environment, *, command, env=None, **kwargs):
        calls.append(("exec", {"command": command, "env": env}))

    agent._upload_config_text = fake_upload
    agent.exec_as_agent = fake_exec

    asyncio.run(
        agent._upload_effective_config(
            object(),
            {"model_reasoning_effort": "high"},
            "/tmp/codex-home/config.toml",
        )
    )

    assert [name for name, _ in calls] == ["upload", "exec"]
    inventory = calls[1][1]
    assert inventory["env"] == {"CODEX_HOME": "/tmp/codex-home"}
    assert "codex plugin list --json" in inventory["command"]
    assert "/logs/agent/plugin-inventory.json" in inventory["command"]


def test_codex_inventory_failure_propagates_from_effective_config_upload(
    tmp_path: Path,
):
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
    )

    async def fake_upload(environment, **kwargs):
        return None

    async def failing_exec(environment, *, command, **kwargs):
        raise RuntimeError("inventory command exited 1")

    agent._upload_config_text = fake_upload
    agent.exec_as_agent = failing_exec

    with pytest.raises(RuntimeError, match="inventory command exited 1"):
        asyncio.run(
            agent._upload_effective_config(
                object(),
                {"model_reasoning_effort": "high"},
                "/tmp/codex-home/config.toml",
            )
        )


def test_codex_adapter_accepts_only_a_canonical_skill_invocation(tmp_path: Path):
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
        skill_invocation="harness:execute",
    )

    assert agent._skill_invocation == "harness:execute"
    with pytest.raises(ValueError, match="skill name"):
        HarnessCodex(
            logs_dir=tmp_path,
            model_name="openai/gpt-5.6-terra",
            version="0.150.1",
            skill_invocation="$harness:execute",
        )


def test_codex_adapter_prefixes_explicit_skill_before_base_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    instructions: list[str] = []

    async def fake_run(self, instruction, environment, context):
        del self, environment, context
        instructions.append(instruction)

    monkeypatch.setattr("harness_testing.Codex_Agent.Codex.run", fake_run)
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
        skill_invocation="harness:execute",
    )

    asyncio.run(agent.run("Original task\n", object(), object()))

    assert instructions == ["$harness:execute Original task\n"]


def _write_session(session_dir: Path) -> None:
    events = [
        {
            "timestamp": "2026-08-29T04:43:29Z",
            "type": "session_meta",
            "payload": {"id": "session-1", "cli_version": "0.150.1"},
        },
        {
            "timestamp": "2026-08-29T04:43:30Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-terra"},
        },
        {
            "timestamp": "2026-08-29T04:43:31Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "call-outer",
                "name": "exec",
                "input": "const edit = await tools.apply_patch(...);",
                "status": "completed",
            },
        },
        {
            "timestamp": "2026-08-29T04:43:32Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "FileChange",
                    "id": "native-edit",
                    "changes": {
                        "/app/src/App.tsx": {
                            "type": "update",
                            "unified_diff": "@@ -1 +1 @@\n-old\n+new\n",
                            "move_path": None,
                        }
                    },
                    "status": "completed",
                    "stdout": "Success. Updated /app/src/App.tsx\n",
                    "stderr": "",
                },
            },
        },
        {
            "timestamp": "2026-08-29T04:43:33Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "CommandExecution",
                    "id": "native-command",
                    "command": ["/bin/bash", "-lc", "npm run gate"],
                    "cwd": "file:///app",
                    "status": "completed",
                    "exit_code": 7,
                    "duration": {"secs": 1, "nanos": 250_000_000},
                    "formatted_output": "gate failed\n",
                },
            },
        },
        {
            "timestamp": "2026-08-29T04:43:34Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-outer",
                "output": "Script completed\n",
            },
        },
    ]
    session_dir.mkdir(parents=True)
    (session_dir / "rollout-2026-08-29T04-43-29-session-1.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )


def test_codex_adapter_exposes_native_code_mode_actions_and_exit_status(
    tmp_path: Path,
):
    session_dir = tmp_path / "sessions" / "2026" / "08" / "29"
    _write_session(session_dir)
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    step = next(step for step in trajectory.steps if step.tool_calls)
    assert [call.function_name for call in step.tool_calls] == [
        "exec",
        "apply_patch",
        "shell",
    ]
    assert step.tool_calls[1].arguments["patch"].startswith(
        "*** Update File: /app/src/App.tsx\n"
    )
    assert step.tool_calls[2].arguments == {
        "cmd": "npm run gate",
        "workdir": "/app",
    }
    results = {
        result.source_call_id: result for result in step.observation.results
    }
    assert result_success(results["native-command"]) is False
    assert results["native-command"].extra == {
        "codex_native": {
            "duration_seconds": 1.25,
            "exit_code": 7,
            "status": "completed",
        }
    }
