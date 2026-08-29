"""Harbor Codex adapter that preserves native code-mode tool executions in ATIF."""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Any, override
from urllib.parse import unquote, urlparse

from harbor.agents.installed.codex import Codex
from harbor.models.trajectories import Observation, ObservationResult, ToolCall, Trajectory


def _raw_events(session_dir: Path) -> list[dict[str, Any]]:
    session_files = list(session_dir.glob("*.jsonl"))
    if not session_files:
        return []
    events: list[dict[str, Any]] = []
    for line in max(session_files).read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


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
            actions[next(iter(pending_exec_calls))].append(item)
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
    if not isinstance(seconds, int) or not isinstance(nanoseconds, int):
        return None
    return seconds + nanoseconds / 1_000_000_000


def _output(item: dict[str, Any]) -> str | None:
    formatted = item.get("formatted_output")
    if isinstance(formatted, str):
        return formatted
    parts = [
        value
        for key in ("stdout", "stderr")
        if isinstance((value := item.get(key)), str) and value
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

    @override
    def _convert_events_to_trajectory(self, session_dir: Path) -> Trajectory | None:
        trajectory = super()._convert_events_to_trajectory(session_dir)
        if trajectory is None:
            return None
        actions_by_call = _native_actions(_raw_events(session_dir))
        for step in trajectory.steps:
            if not step.tool_calls:
                continue
            original_calls = list(step.tool_calls)
            results = list(step.observation.results) if step.observation else []
            expanded_calls: list[ToolCall] = []
            for outer_call in original_calls:
                expanded_calls.append(outer_call)
                for index, item in enumerate(
                    actions_by_call.get(outer_call.tool_call_id, []), start=1
                ):
                    native = _native_call(outer_call.tool_call_id, item, index)
                    if native is not None:
                        call, result = native
                        expanded_calls.append(call)
                        results.append(result)
            step.tool_calls = expanded_calls
            if results:
                step.observation = Observation(results=results)
        return Trajectory.model_validate(trajectory.model_dump())
