"""Deterministic correctness, workflow, and efficiency criteria for the sentinel."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from rewardkit import criterion

_COMPREHENSIVE_COMMANDS = {
    "npm run gate",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
}
_MUTATION_TOOLS = {"Edit", "Write", "apply_patch"}
_SHELL_TOOLS = {"Bash", "shell"}
_RELEVANT_PATH = re.compile(
    r"(?:^|/)(?:src|app|lib|tests|crates|packages)/|"
    r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
    re.IGNORECASE,
)


def _trajectory_path() -> Path:
    return Path(
        os.environ.get(
            "HARNESS_TEST_TRAJECTORY",
            "/logs/agent/trajectory.json",
        )
    )


def _protected_files_intact(workspace: Path) -> bool:
    manifest_path = Path(__file__).with_name("Protected_Files.json")
    try:
        manifest = json.loads(manifest_path.read_text())
        entries = manifest["files"]
    except (OSError, KeyError, json.JSONDecodeError):
        return False
    if not isinstance(entries, dict):
        return False
    for relative_path, expected in entries.items():
        path = workspace / relative_path
        if not path.is_file() or path.is_symlink():
            return False
        actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if actual != expected:
            return False
    return True


def _result_success(result: dict[str, Any] | None) -> bool | None:
    if result is None:
        return None
    extra = result.get("extra")
    if isinstance(extra, dict) and isinstance(extra.get("exit_code"), int):
        return extra["exit_code"] == 0
    content = result.get("content")
    text = content if isinstance(content, str) else json.dumps(content)
    match = re.search(
        r"(?:exit[_ ]code|process exited with code)\s*[:=]?\s*(-?\d+)",
        text,
        re.IGNORECASE,
    )
    return int(match[1]) == 0 if match else None


def _normalize(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return " ".join(command.split())
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    tokens = [
        token
        for token in tokens
        if token not in {"-q", "--quiet", "--silent", "--no-color", "--color"}
    ]
    return " ".join(tokens)


def _tool_paths(call: dict[str, Any]) -> tuple[str, ...]:
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return ()
    paths = [
        value
        for key in ("file_path", "path")
        if isinstance((value := arguments.get(key)), str)
    ]
    patch = arguments.get("patch") or arguments.get("input")
    if isinstance(patch, str):
        paths.extend(
            re.findall(
                r"^(?:\*\*\* (?:Add|Update|Delete) File:|\+\+\+ b/)\s*(.+)$",
                patch,
                re.MULTILINE,
            )
        )
    return tuple(paths)


def _is_relevant_mutation(call: dict[str, Any]) -> bool:
    name = call.get("function_name")
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return False
    if name in _MUTATION_TOOLS:
        return any(_RELEVANT_PATH.search(path.removeprefix("/app/")) for path in _tool_paths(call))
    if name not in _SHELL_TOOLS:
        return False
    command = arguments.get("command") or arguments.get("cmd")
    return bool(
        isinstance(command, str)
        and re.search(r"(?:^|\s)(?:sed\s+-i|perl\s+-pi|touch|mv|cp|rm)\s", command)
        and _RELEVANT_PATH.search(command)
    )


def _events() -> list[tuple[str, str | None, bool | None]]:
    try:
        trajectory = json.loads(_trajectory_path().read_text())
    except (OSError, json.JSONDecodeError):
        return []
    events: list[tuple[str, str | None, bool | None]] = []
    for step in trajectory.get("steps", []):
        observation = step.get("observation") or {}
        results = {
            result.get("source_call_id"): result
            for result in observation.get("results", [])
            if result.get("source_call_id") is not None
        }
        for call in step.get("tool_calls") or []:
            if _is_relevant_mutation(call):
                events.append(("mutation", None, None))
            name = call.get("function_name")
            arguments = call.get("arguments")
            if name not in _SHELL_TOOLS or not isinstance(arguments, dict):
                continue
            command = arguments.get("command") or arguments.get("cmd")
            if not isinstance(command, str):
                continue
            events.append(
                (
                    "command",
                    _normalize(command),
                    _result_success(results.get(call.get("tool_call_id"))),
                )
            )
    return events


@criterion(shared=True)
def sentinel_correctness(workspace: Path) -> bool:
    """The requested final behavior passes and protected fixture inputs are intact."""

    if not _protected_files_intact(workspace):
        return False
    result = subprocess.run(
        ["npm", "test", "--", "--reporter=dot"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    return result.returncode == 0


@criterion(shared=True)
def final_gate_workflow(workspace: Path) -> bool:
    """A successful npm run gate is present after the final relevant source edit."""

    del workspace
    events = _events()
    gate_indexes = [
        index
        for index, (kind, command, success) in enumerate(events)
        if kind == "command" and command == "npm run gate" and success is True
    ]
    if not gate_indexes:
        return False
    return not any(
        kind == "mutation" for kind, _, _ in events[gate_indexes[-1] + 1 :]
    )


@criterion(shared=True)
def no_testing_churn(workspace: Path) -> bool:
    """No successful comprehensive run precedes an edit and no success is duplicated."""

    del workspace
    successful_since_mutation: set[str] = set()
    pending_comprehensive = False
    for kind, command, success in _events():
        if kind == "mutation":
            if pending_comprehensive:
                return False
            pending_comprehensive = False
            successful_since_mutation.clear()
            continue
        if success is not True or command is None:
            continue
        if command in successful_since_mutation:
            return False
        successful_since_mutation.add(command)
        if command in _COMPREHENSIVE_COMMANDS:
            pending_comprehensive = True
    return True
