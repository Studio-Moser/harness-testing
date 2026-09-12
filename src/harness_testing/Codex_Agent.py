"""Harbor Codex adapter that preserves native code-mode tool executions in ATIF."""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, override
from urllib.parse import unquote, urlparse

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Observation, ObservationResult, ToolCall, Trajectory

from harness_testing.Native_Conversation import (
    remove_controller,
    stage_controller,
    validate_conversation,
)
from harness_testing.Skill_Evaluation import explicit_instruction, validate_skill_name


def _raw_events(session_file: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in session_file.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _session_id(session_file: Path) -> str | None:
    for event in _raw_events(session_file):
        if event.get("type") != "session_meta":
            continue
        payload = event.get("payload")
        value = payload.get("id") if isinstance(payload, dict) else None
        return value if isinstance(value, str) else None
    return None


def _session_parent(session_file: Path) -> str | None:
    for event in _raw_events(session_file):
        if event.get("type") != "session_meta":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None
        direct = payload.get("parent_thread_id")
        if isinstance(direct, str):
            return direct
        source = payload.get("source")
        if not isinstance(source, dict):
            return None
        subagent = source.get("subagent", source.get("subAgent"))
        spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
        parent = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
        return parent if isinstance(parent, str) else None
    return None


def _recorded_root_session(logs_dir: Path) -> str | None:
    path = logs_dir / "Trial_Evidence.json"
    try:
        evidence = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    value = evidence.get("root_session_id") if isinstance(evidence, dict) else None
    return value if isinstance(value, str) and value else None


def _native_actions(events: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    actions: dict[str, list[dict[str, Any]]] = {}
    pending_exec_calls: set[str] = set()
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if event.get("type") == "response_item":
            if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    pending_exec_calls.add(call_id)
                    actions.setdefault(call_id, [])
            elif payload.get("type") == "custom_tool_call_output":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    pending_exec_calls.discard(call_id)
            continue
        if event.get("type") != "event_msg" or payload.get("type") != "item_completed":
            continue
        item = payload.get("item")
        if (
            len(pending_exec_calls) == 1
            and isinstance(item, dict)
            and item.get("type") in {"CommandExecution", "FileChange"}
        ):
            actions[next(iter(pending_exec_calls))].append(
                {**item, "_event_timestamp": event.get("timestamp")}
            )
    return actions


def _command_text(item: dict[str, Any]) -> str | None:
    command = item.get("command")
    if isinstance(command, str):
        return command
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        return None
    if (
        len(command) >= 3
        and Path(command[0]).name in {"bash", "sh", "zsh"}
        and command[1] in {"-c", "-lc"}
    ):
        return command[2]
    return shlex.join(command)


def _workdir(item: dict[str, Any]) -> str | None:
    value = item.get("cwd")
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return unquote(parsed.path) if parsed.scheme == "file" else value


def _duration_seconds(item: dict[str, Any]) -> float | None:
    duration = item.get("duration")
    if not isinstance(duration, dict):
        return None
    seconds = duration.get("secs")
    nanoseconds = duration.get("nanos")
    if (
        type(seconds) is not int
        or seconds < 0
        or type(nanoseconds) is not int
        or not 0 <= nanoseconds < 1_000_000_000
    ):
        return None
    return seconds + nanoseconds / 1_000_000_000


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _output(item: dict[str, Any]) -> str | None:
    formatted = item.get("formatted_output")
    if isinstance(formatted, str):
        return formatted
    parts = [
        value for key in ("stdout", "stderr") if isinstance((value := item.get(key)), str) and value
    ]
    return "".join(parts) or None


def _file_patch(item: dict[str, Any]) -> str | None:
    changes = item.get("changes")
    if not isinstance(changes, dict):
        return None
    sections: list[str] = []
    for path, change in changes.items():
        if not isinstance(path, str) or not isinstance(change, dict):
            continue
        diff = change.get("unified_diff")
        sections.append(f"*** Update File: {path}\n")
        if isinstance(diff, str):
            sections.append(diff if diff.endswith("\n") else f"{diff}\n")
    return "".join(sections) or None


def _native_call(
    outer_call_id: str,
    item: dict[str, Any],
    index: int,
) -> tuple[ToolCall, ObservationResult] | None:
    item_type = item.get("type")
    item_id = item.get("id")
    call_id = item_id if isinstance(item_id, str) else f"{outer_call_id}:native:{index}"
    native_extra: dict[str, Any] = {"status": item.get("status")}
    if item_type == "CommandExecution":
        command = _command_text(item)
        if command is None:
            return None
        arguments: dict[str, Any] = {"cmd": command}
        if (workdir := _workdir(item)) is not None:
            arguments["workdir"] = workdir
        exit_code = item.get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            native_extra["exit_code"] = exit_code
        if (duration := _duration_seconds(item)) is not None:
            native_extra["duration_seconds"] = duration
        function_name = "shell"
    elif item_type == "FileChange":
        patch = _file_patch(item)
        arguments = {"patch": patch} if patch is not None else {}
        function_name = "apply_patch"
    else:
        return None
    return (
        ToolCall(
            tool_call_id=call_id,
            function_name=function_name,
            arguments=arguments,
            extra={
                "codex_native": {
                    "item_type": item_type,
                    "parent_call_id": outer_call_id,
                }
            },
        ),
        ObservationResult(
            source_call_id=call_id,
            content=_output(item),
            extra={"codex_native": native_extra},
        ),
    )


class HarnessCodex(Codex):
    """Codex with a narrow Harbor 0.22.0 code-mode trajectory compatibility fix."""

    def __init__(
        self,
        *args: Any,
        skill_invocation: str | None = None,
        conversation: dict | None = None,
        **kwargs: Any,
    ) -> None:
        self._skill_invocation = (
            validate_skill_name(skill_invocation) if skill_invocation is not None else None
        )
        self._conversation = conversation
        self._conversation_instruction = None
        super().__init__(*args, **kwargs)

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        if self._skill_invocation is not None:
            instruction = explicit_instruction("codex", self._skill_invocation, instruction)
        if self._conversation is None:
            await super().run(instruction, environment, context)
            return
        validate_conversation(self._conversation, "codex")
        if self._resume or self._load:
            raise ValueError(
                "native_resume_requires_explicit_root: use conversation.root_session_id"
            )
        self._conversation_instruction = instruction
        try:
            await super().run(instruction, environment, context)
        finally:
            # Harbor stages config/auth before its try/finally. Cover those
            # failures too, retaining transcripts before removing credentials.
            home = shlex.quote(self._REMOTE_CODEX_HOME.as_posix())
            secrets = shlex.quote(self._REMOTE_CODEX_SECRETS_DIR.as_posix())
            cache = f"{home}/plugins/cache"
            try:
                result = await environment.exec(
                    f"mkdir -p /logs/agent/sessions; "
                    f"if [ -d {home}/sessions ]; then "
                    f"cp -R {home}/sessions/. /logs/agent/sessions/; fi; "
                    f"rm -rf -- {secrets} && "
                    # The frozen cache is a read-only bind mount inside CODEX_HOME.
                    # Keep that mount and its parents; remove all writable state.
                    f"if mountpoint -q {cache} && "
                    f"findmnt -rn --mountpoint {cache} -O ro >/dev/null; then "
                    f"find {home} -mindepth 1 -maxdepth 1 ! -name plugins "
                    f"-exec rm -rf -- {{}} + && "
                    f"find {home}/plugins -mindepth 1 -maxdepth 1 ! -name cache "
                    f"-exec rm -rf -- {{}} +; "
                    f"else rm -rf -- {home}; fi",
                    user="root",
                )
                if result.return_code:
                    raise RuntimeError("Codex credential cleanup failed")
            finally:
                await remove_controller(environment)

    @override
    async def exec_as_agent(self, environment, command, env=None, cwd=None, timeout_sec=None):
        if self._conversation is not None and "codex exec " in command:
            cli = ["codex", "app-server", "--stdio", "--enable", "unified_exec"]
            cli.extend(shlex.split(self.build_cli_flags()))
            config = {
                **self._conversation,
                "provider": "codex",
                "command": cli,
                "model": self.model_name.split("/")[-1],
                "effort": self._resolved_flags.get(
                    "reasoning_effort", self._base_config.get("model_reasoning_effort")
                ),
                "runtime_version": self._version,
                "instruction": self._conversation_instruction,
            }
            command = (
                "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                + await stage_controller(environment, config)
            )
            timeout_sec = (
                self._conversation["timeout_seconds"]
                + self._conversation.get("provider_recovery_seconds", 0)
                + 10
            )
        return await super().exec_as_agent(
            environment, command, env=env, cwd=cwd, timeout_sec=timeout_sec
        )

    @override
    async def _upload_effective_config(
        self,
        environment: BaseEnvironment,
        config: dict[str, Any],
        remote_path: str,
    ) -> None:
        await super()._upload_effective_config(environment, config, remote_path)
        await self.exec_as_agent(
            environment,
            command=(
                "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                "mkdir -p /logs/agent; "
                "codex plugin list --json > /logs/agent/plugin-inventory.json"
            ),
            env={"CODEX_HOME": self._REMOTE_CODEX_HOME.as_posix()},
        )

    def _convert_session_file(self, selected: Path) -> Trajectory | None:
        with TemporaryDirectory() as temporary:
            isolated = Path(temporary)
            (isolated / selected.name).symlink_to(selected)
            trajectory = super()._convert_events_to_trajectory(isolated)
        if trajectory is None:
            return None
        actions_by_call = _native_actions(_raw_events(selected))
        native_steps = []
        for step in trajectory.steps:
            if not step.tool_calls:
                continue
            original_calls = list(step.tool_calls)
            results = list(step.observation.results) if step.observation else []
            for outer_call in original_calls:
                for index, item in enumerate(
                    actions_by_call.get(outer_call.tool_call_id, []), start=1
                ):
                    native = _native_call(outer_call.tool_call_id, item, index)
                    if native is not None:
                        call, result = native
                        timestamp = item.get("_event_timestamp")
                        duration = _duration_seconds(item)
                        native_step = step.model_copy(deep=True)
                        if call.function_name == "shell":
                            if not isinstance(timestamp, str) or duration is None:
                                self.logger.warning(
                                    "A retained Codex command has incomplete timing"
                                )
                                return None
                            completed = _timestamp(timestamp)
                            started = completed - timedelta(seconds=duration)
                            native_step.extra = {
                                **(native_step.extra or {}),
                                "command_completed_at": timestamp,
                            }
                            timestamp = started.isoformat().replace("+00:00", "Z")
                        native_step.timestamp = timestamp if isinstance(timestamp, str) else None
                        native_step.message = ""
                        native_step.reasoning_content = None
                        native_step.tool_calls = [call]
                        native_step.observation = Observation(results=[result])
                        native_step.metrics = None
                        native_step.llm_call_count = None
                        native_steps.append(native_step)
            step.tool_calls = original_calls
            if results:
                step.observation = Observation(results=results)
        trajectory.steps.extend(native_steps)
        if all(step.timestamp is not None for step in trajectory.steps):
            trajectory.steps.sort(key=lambda step: _timestamp(step.timestamp))
            for index, step in enumerate(trajectory.steps, start=1):
                step.step_id = index
        return Trajectory.model_validate(trajectory.model_dump())

    @override
    def _convert_events_to_trajectory(self, session_dir: Path) -> Trajectory | None:
        session_files = list(session_dir.glob("*.jsonl"))
        root_session = _recorded_root_session(self.logs_dir)
        if root_session is not None:
            session_files = list((self.logs_dir / "sessions").rglob("*.jsonl"))
        if not session_files:
            return None
        selected = next(
            (path for path in session_files if _session_id(path) == root_session),
            None,
        )
        if root_session is not None and selected is None:
            self.logger.warning("Recorded Codex root session is missing from retained sessions")
            return None
        if root_session is not None:
            paths = {_session_id(path): path for path in session_files}
            parents = {session: _session_parent(path) for session, path in paths.items()}
            selected_sessions = {root_session}
            while True:
                children = {
                    session for session, parent in parents.items() if parent in selected_sessions
                }
                if children <= selected_sessions:
                    break
                selected_sessions |= children
            evidence = json.loads((self.logs_dir / "Trial_Evidence.json").read_text())
            recorded_sessions = {
                session["session_id"] for session in evidence.get("sessions", [])
            }
            if not recorded_sessions <= selected_sessions:
                self.logger.warning("A recorded Codex session is missing from the retained tree")
                return None
            session_files = [
                paths[session] for session in sorted(selected_sessions) if session in paths
            ]
        selected = selected or max(session_files)
        trajectory = self._convert_session_file(selected)
        if trajectory is None or root_session is None:
            return trajectory
        converted = [trajectory]
        for child in session_files:
            if child == selected:
                continue
            child_trajectory = self._convert_session_file(child)
            if child_trajectory is None:
                self.logger.warning("A retained Codex child session could not be converted")
                return None
            converted.append(child_trajectory)
        if any(step.timestamp is None for item in converted for step in item.steps):
            self.logger.warning("A retained Codex tree step has no timestamp")
            return None
        steps = []
        for item in converted:
            for step in item.steps:
                step.extra = {**(step.extra or {}), "session_id": item.session_id}
                steps.append(step)
        steps.sort(key=lambda step: _timestamp(step.timestamp))
        for index, step in enumerate(steps, start=1):
            step.step_id = index
        trajectory.steps = steps
        trajectory.final_metrics = None
        return Trajectory.model_validate(trajectory.model_dump())
