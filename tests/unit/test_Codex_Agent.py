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


def test_codex_native_adapter_reserves_the_provider_recovery_allowance(tmp_path, monkeypatch):
    calls = []

    async def fake_stage(environment, settings):
        del environment
        calls.append(("stage", settings))
        return "python3 /tmp/Harness_Native_Conversation/Native_Conversation.py"

    async def fake_exec(self, environment, command, **kwargs):
        del self, environment
        calls.append(("exec", command, kwargs))

    monkeypatch.setattr("harness_testing.Codex_Agent.stage_controller", fake_stage)
    monkeypatch.setattr("harness_testing.Codex_Agent.Codex.exec_as_agent", fake_exec)
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
        conversation={
            "policy": {"schema_version": "1", "interaction_limit": 1, "facts": {}, "rules": []},
            "timeout_seconds": 4,
            "provider_recovery_seconds": 600,
        },
    )
    agent._conversation_instruction = "Task"

    asyncio.run(agent.exec_as_agent(object(), "codex exec Task"))

    assert calls[0][1]["provider_recovery_seconds"] == 600
    assert calls[1][2]["timeout_sec"] == 614


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
    assert step.tool_calls[1].arguments["patch"].startswith("*** Update File: /app/src/App.tsx\n")
    assert step.tool_calls[2].arguments == {
        "cmd": "npm run gate",
        "workdir": "/app",
    }
    results = {result.source_call_id: result for result in step.observation.results}
    assert result_success(results["native-command"]) is False
    assert results["native-command"].extra == {
        "codex_native": {
            "duration_seconds": 1.25,
            "exit_code": 7,
            "status": "completed",
        }
    }


@pytest.mark.parametrize("setup_failure", [False, True])
def test_codex_native_adapter_preserves_config_and_cleans_even_setup_failure(
    tmp_path, monkeypatch, setup_failure
):
    from types import SimpleNamespace

    class Environment:
        default_user = None

        def __init__(self):
            self.commands = []
            self.config = None

        async def upload_file(self, source, target):
            if target.endswith("Trial_Config.json"):
                self.config = json.loads(Path(source).read_text())

        async def exec(self, command, **kwargs):
            self.commands.append(command)
            return SimpleNamespace(return_code=0, stdout="", stderr="")

    async def fake_run(self, instruction, environment, context):
        if not setup_failure:
            await self.exec_as_agent(environment, "codex exec resume --last --model wrong")
        raise RuntimeError("retained failure")

    monkeypatch.setattr("harness_testing.Codex_Agent.Codex.run", fake_run)
    policy = {"schema_version": "1", "interaction_limit": 3, "facts": {}, "rules": []}
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-terra",
        version="0.150.1",
        reasoning_effort="high",
        conversation={"policy": policy, "timeout_seconds": 4},
    )
    environment = Environment()
    with pytest.raises(RuntimeError, match="retained failure"):
        asyncio.run(agent.run("Ordinary request", environment, object()))
    if not setup_failure:
        assert environment.config["model"] == "gpt-5.6-terra"
        assert environment.config["command"][:3] == ["codex", "app-server", "--stdio"]
        assert "--last" not in environment.config["command"]
    assert "/tmp/codex-home" in environment.commands[-2]
    assert "rm -rf --" in environment.commands[-2]
    assert environment.commands[-1] == "rm -rf -- /tmp/Harness_Native_Conversation"


@pytest.mark.parametrize("mounted, read_only", [(False, False), (True, False), (True, True)])
def test_native_cleanup_preserves_only_the_read_only_plugin_mount(
    tmp_path, monkeypatch, mounted, read_only
):
    import os
    import subprocess
    from types import SimpleNamespace

    home = tmp_path / "codex-home"
    secrets = tmp_path / "codex-secrets"
    logs = tmp_path / "logs"
    cache = home / "plugins/cache"
    cache.mkdir(parents=True)
    (cache / "SKILL.md").write_text("Frozen skill\n")
    (home / "plugins/registry.json").write_text("Writable state\n")
    (home / "sessions").mkdir()
    (home / "sessions/session.jsonl").write_text("Retained transcript\n")
    secrets.mkdir()
    (secrets / "auth.json").write_text("dummy credential\n")
    (home / "auth.json").symlink_to(secrets / "auth.json")
    (home / "config.toml").write_text("Writable config\n")
    commands = tmp_path / "commands"
    commands.mkdir()
    # Only the kernel mount queries are substituted; the adapter's shell cleanup
    # runs against real files. A separate Docker check exercises an actual mount.
    for name, success in (("mountpoint", mounted), ("findmnt", read_only)):
        executable = commands / name
        executable.write_text(f"#!/bin/sh\nexit {0 if success else 1}\n")
        executable.chmod(0o755)

    class Environment:
        async def exec(self, command, **kwargs):
            result = subprocess.run(
                command.replace("/logs/agent", str(logs)).replace(
                    "/tmp/Harness_Native_Conversation", str(tmp_path / "controller")
                ),
                shell=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
            )
            return SimpleNamespace(return_code=result.returncode)

    async def native_completed(*args, **kwargs):
        pass

    monkeypatch.setattr("harness_testing.Codex_Agent.Codex.run", native_completed)
    agent = HarnessCodex(
        logs_dir=logs,
        model_name="openai/gpt-6-astra",
        version="0.153.4",
        conversation={
            "policy": {"schema_version": "1", "interaction_limit": 1, "facts": {}, "rules": []},
            "timeout_seconds": 1,
        },
    )
    agent._REMOTE_CODEX_HOME = home
    agent._REMOTE_CODEX_SECRETS_DIR = secrets
    asyncio.run(agent.run("No model call", Environment(), object()))

    assert not secrets.exists()
    assert not (home / "auth.json").is_symlink()
    assert not (home / "config.toml").exists()
    assert not (home / "plugins/registry.json").exists()
    assert (logs / "sessions/session.jsonl").read_text() == "Retained transcript\n"
    if mounted and read_only:
        assert (cache / "SKILL.md").read_text() == "Frozen skill\n"
        assert list(home.iterdir()) == [home / "plugins"]
        assert list((home / "plugins").iterdir()) == [cache]
    else:
        assert not home.exists()


def test_native_cleanup_still_rejects_credential_removal_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []

    class Environment:
        async def exec(self, command, **kwargs):
            calls.append(command)
            # Credential cleanup fails; the controller can still be removed.
            return SimpleNamespace(return_code=0 if len(calls) == 2 else 1)

    async def native_completed(*args, **kwargs):
        pass

    monkeypatch.setattr("harness_testing.Codex_Agent.Codex.run", native_completed)
    agent = HarnessCodex(
        logs_dir=tmp_path,
        model_name="openai/gpt-6-astra",
        version="0.153.4",
        conversation={
            "policy": {"schema_version": "1", "interaction_limit": 1, "facts": {}, "rules": []},
            "timeout_seconds": 1,
        },
    )
    with pytest.raises(RuntimeError, match="Codex credential cleanup failed"):
        asyncio.run(agent.run("No model call", Environment(), object()))
    assert len(calls) == 2
    assert calls[-1] == "rm -rf -- /tmp/Harness_Native_Conversation"
