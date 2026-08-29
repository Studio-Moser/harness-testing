"""Deterministic correctness, workflow, and efficiency criteria for the sentinel."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from rewardkit import criterion

from harness_testing.Trajectory_Events import (
    ShellComponent,
    component_successes,
    normalize_command,
    patch_paths,
    result_success,
    shell_mutation,
    split_shell,
)

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
    r"(?:^|/)(?:src|app|lib|tests|crates|packages)(?:/|$)|"
    r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
    re.IGNORECASE,
)
_IGNORED_FLAGS = {"-q", "--quiet", "--silent", "--no-color", "--color"}
_REMOVABLE_PREFIXES = (("uv", "run"),)
_SHELL_MUTATION_PATTERNS = (
    r"(^|\s)(?:sed\s+-i|perl\s+-pi|touch|mkdir|mv|cp|rm)\s",
    r"(?:>|>>|\btee\b)\s*\S+",
)
_RELEVANT_PATH_PATTERNS = (
    r"(^|/)(?:src|app|lib|tests|crates|packages)(?:/|$)",
    r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
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
        mutable_entries = manifest["mutable_files"]
    except (OSError, KeyError, json.JSONDecodeError):
        return False
    if not isinstance(entries, dict) or not isinstance(mutable_entries, dict):
        return False
    for relative_path, expected in entries.items():
        path = workspace / relative_path
        if not path.is_file() or path.is_symlink():
            return False
        actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if actual != expected:
            return False
    for relative_path, rule in mutable_entries.items():
        path = workspace / relative_path
        if not path.is_file() or path.is_symlink() or not isinstance(rule, dict):
            return False
        baseline = rule.get("baseline_sha256")
        replacements = rule.get("replacements")
        if not isinstance(baseline, str) or not isinstance(replacements, list):
            return False
        try:
            restored = path.read_text()
        except (OSError, UnicodeDecodeError):
            return False
        for replacement in replacements:
            if not isinstance(replacement, dict):
                return False
            before = replacement.get("before")
            after = replacement.get("after")
            count = replacement.get("count")
            if (
                not isinstance(before, str)
                or not isinstance(after, str)
                or not isinstance(count, int)
                or count < 1
                or restored.count(after) != count
            ):
                return False
            restored = restored.replace(after, before)
        actual = f"sha256:{hashlib.sha256(restored.encode()).hexdigest()}"
        if actual != baseline:
            return False
    return True


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
        paths.extend(patch_paths(patch))
    return tuple(paths)


def _normalize(command: str) -> str:
    return normalize_command(command, _IGNORED_FLAGS, _REMOVABLE_PREFIXES)


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
            name = call.get("function_name")
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                continue
            call_id = call.get("tool_call_id")
            success = result_success(
                results.get(call_id),
                step_extra=step.get("extra"),
                call_id=call_id if isinstance(call_id, str) else None,
            )
            if name in _MUTATION_TOOLS:
                paths = _tool_paths(call)
                if success is not False and any(
                    _RELEVANT_PATH.search(path.removeprefix("/app/")) for path in paths
                ):
                    events.append(("mutation", None, None))
                elif success is not False and not paths:
                    events.append(("unknown_mutation", None, None))
                continue
            if name not in _SHELL_TOOLS:
                continue
            command = arguments.get("command") or arguments.get("cmd")
            if not isinstance(command, str):
                continue
            components = split_shell(command) or (ShellComponent(command, None),)
            statuses = component_successes(components, success)
            for component, component_success in zip(components, statuses, strict=True):
                mutation, _ = shell_mutation(
                    component.command,
                    _SHELL_MUTATION_PATTERNS,
                    _RELEVANT_PATH_PATTERNS,
                )
                if mutation == "relevant" and component_success is True:
                    events.append(("mutation", None, None))
                elif mutation in {"relevant", "unknown"} and component_success is not False:
                    events.append(("unknown_mutation", None, None))
                events.append(
                    ("command", _normalize(component.command), component_success)
                )
            events.append(("duplicate", _normalize(command), success))
    return events


def _final_gate_workflow() -> bool:
    events = _events()
    gate_indexes = [
        index
        for index, (kind, command, success) in enumerate(events)
        if kind == "command" and command == "npm run gate" and success is True
    ]
    if not gate_indexes:
        return False
    return not any(
        kind in {"mutation", "unknown_mutation"}
        for kind, _, _ in events[gate_indexes[-1] + 1 :]
    )


def _no_testing_churn() -> bool:
    successful_since_mutation: set[str] = set()
    pending_comprehensive = False
    for kind, command, success in _events():
        if kind == "unknown_mutation":
            return False
        if kind == "mutation":
            if pending_comprehensive:
                return False
            pending_comprehensive = False
            successful_since_mutation.clear()
            continue
        if success is not True or command is None:
            continue
        if kind == "duplicate":
            if command in successful_since_mutation:
                return False
            successful_since_mutation.add(command)
        elif kind == "command" and command in _COMPREHENSIVE_COMMANDS:
            pending_comprehensive = True
    return True


def _sentinel_correctness(workspace: Path) -> bool:
    if not _protected_files_intact(workspace):
        return False
    checks = (
        ("src/index.css", "--accent", "#6d28d9"),
        ("src/App.tsx", "No projects yet"),
        ("src/index.css", "--card-gap", "12px"),
    )
    for arguments in checks:
        result = subprocess.run(
            ["node", "scripts/Check_Token.mjs", *arguments],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return False
    return True


@criterion(shared=True)
def sentinel_correctness(workspace: Path) -> bool:
    """The requested final behavior passes and protected fixture inputs are intact."""

    return _sentinel_correctness(workspace)


@criterion(shared=True)
def final_gate_workflow(workspace: Path) -> bool:
    """A successful npm run gate is present after the final relevant source edit."""

    del workspace
    return _final_gate_workflow()


@criterion(shared=True)
def no_testing_churn(workspace: Path) -> bool:
    """No successful comprehensive run precedes an edit and no success is duplicated."""

    del workspace
    return _no_testing_churn()
