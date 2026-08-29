"""Shared ATIF workflow predicates for locally authored benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
    "cargo test --workspace",
}
_MUTATION_TOOLS = {"Edit", "Write", "apply_patch"}
_SHELL_TOOLS = {"Bash", "shell"}
_RELEVANT_PATH = re.compile(
    r"(?:^|/)(?:src|app|lib|tests|crates|packages)(?:/|$)|"
    r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
    re.IGNORECASE,
)
_IGNORED_FLAGS = {
    "-q",
    "--quiet",
    "--silent",
    "--no-color",
    "--color",
    "--locked",
    "--offline",
}
_REMOVABLE_PREFIXES = (("uv", "run"),)
_SHELL_MUTATION_PATTERNS = (
    r"(^|\s)(?:sed\s+-i|perl\s+-pi|touch|mkdir|mv|cp|rm)\s",
    r"(?:>|>>|\btee\b)\s*\S+",
    r'''^(?:python(?:3)?|node)\s+(?:-c|-e)\b.*'''
    r'''(?:write_text|write_bytes|writeFile|writeFileSync|appendFile|appendFileSync|'''
    r'''unlink|unlinkSync|remove|rename|renameSync|mkdir|mkdirSync|rmdir|replace|'''
    r'''open\s*\([^)]*,\s*['"][wax+])''',
)
_RELEVANT_PATH_PATTERNS = (
    r"(^|/)(?:src|app|lib|tests|crates|packages)(?:/|$)",
    r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
)


def _trajectory_path() -> Path:
    return Path(os.environ.get("HARNESS_TEST_TRAJECTORY", "/logs/agent/trajectory.json"))


def protected_files_intact(workspace: Path, manifest_path: Path) -> bool:
    """Validate immutable files and exact declared final-state substitutions."""

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


def node_test_correctness(
    workspace: Path,
    manifest_path: Path,
    dependencies: Path,
    command: Sequence[str] = ("npm", "test", "--", "--reporter=dot"),
) -> bool:
    """Run a frozen Node behavior suite without installing into the workspace."""

    if not protected_files_intact(workspace, manifest_path):
        return False
    node_modules = workspace / "node_modules"
    if not dependencies.is_dir() or node_modules.exists() or node_modules.is_symlink():
        return False
    cleanup_failed = False
    node_modules.symlink_to(dependencies, target_is_directory=True)
    try:
        result = subprocess.run(
            list(command),
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(error)
        return False
    finally:
        try:
            node_modules.unlink()
        except OSError:
            cleanup_failed = True
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    return result.returncode == 0 and not cleanup_failed


def cargo_test_correctness(
    workspace: Path,
    manifest_path: Path,
    command: Sequence[str] = (
        "cargo",
        "test",
        "--workspace",
        "--locked",
        "--offline",
    ),
) -> bool:
    """Run frozen Cargo behavior tests in a fresh build directory."""

    if not protected_files_intact(workspace, manifest_path):
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="harness-cargo-target-") as target:
            environment = os.environ.copy()
            environment["CARGO_TARGET_DIR"] = target
            result = subprocess.run(
                list(command),
                cwd=workspace,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(error)
        return False
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    return result.returncode == 0


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
                events.append(("command", _normalize(component.command), component_success))
            events.append(("duplicate", _normalize(command), success))
    return events


def command_after_last_mutation(command: str) -> bool:
    """Return true when the required command succeeds after all relevant edits."""

    events = _events()
    last_mutation = max(
        (
            index
            for index, (kind, _, _) in enumerate(events)
            if kind in {"mutation", "unknown_mutation"}
        ),
        default=-1,
    )
    required = _normalize(command)
    return any(
        index > last_mutation
        and kind == "command"
        and observed == required
        and success is True
        for index, (kind, observed, success) in enumerate(events)
    )


def command_succeeded(command: str) -> bool:
    """Return true when the required command succeeds anywhere in the trajectory."""

    required = _normalize(command)
    return any(
        kind == "command" and observed == required and success is True
        for kind, observed, success in _events()
    )


def no_comprehensive_commands() -> bool:
    """Return false for any successful comprehensive command."""

    return not any(
        kind == "command" and command in _COMPREHENSIVE_COMMANDS and success is True
        for kind, command, success in _events()
    )


def no_testing_churn() -> bool:
    """Reject premature comprehensive checks and duplicate successful commands."""

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
