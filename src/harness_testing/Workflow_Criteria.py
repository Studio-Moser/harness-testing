"""Shared ATIF workflow predicates for locally authored benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
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
    r"""^(?:python(?:3)?|node)\s+(?:-c|-e)\b.*"""
    r"""(?:write_text|write_bytes|writeFile|writeFileSync|appendFile|appendFileSync|"""
    r"""unlink|unlinkSync|remove|rename|renameSync|mkdir|mkdirSync|rmdir|replace|"""
    r"""open\s*\([^)]*,\s*['"][wax+])""",
)
_RELEVANT_PATH_PATTERNS = (
    r"(^|/)(?:src|app|lib|tests|crates|packages)(?:/|$)",
    r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
)


def _trajectory_path() -> Path:
    return Path(os.environ.get("HARNESS_TEST_TRAJECTORY", "/logs/agent/trajectory.json"))


def verification_config_path(path: Path) -> bool:
    """Runner/build inputs cannot be introduced by a benchmark submission."""
    return bool(
        re.fullmatch(
            r".*\.(?:config|workspace)\.[^.]+|tsconfig.*\.json|package(?:-lock)?\.json|"
            r"Cargo\.(?:toml|lock)|build\.rs|rust-toolchain(?:\.toml)?|"
            r"yarn\.lock|pnpm-(?:lock\.yaml|workspace\.yaml)|bun\.lockb?|"
            r"deno\.jsonc?|test\.sh|\..*",
            path.name,
        )
        or {".cargo", ".git", ".github", "node_modules"} & set(path.parts)
    )


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
    # New source/tests are legitimate; new loader/build configuration is not.
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace)
        if relative.parts[0] in {".git", "target", "node_modules"}:
            continue
        if path.is_symlink():
            return False
        if (
            path.is_file()
            and relative.as_posix() not in entries
            and verification_config_path(relative)
        ):
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
    *,
    test_files: Sequence[str] | None = None,
    expect_assertion_failure: bool = False,
) -> bool:
    """Run a frozen Node behavior suite without installing into the workspace."""

    if not protected_files_intact(workspace, manifest_path):
        return False
    node_modules = workspace / "node_modules"
    if not dependencies.is_dir() or node_modules.exists() or node_modules.is_symlink():
        return False
    manifest = json.loads(manifest_path.read_text())
    required = (
        list(test_files)
        if test_files is not None
        else [
            name for name in manifest["files"] if re.search(r"\.(?:test|spec)\.[cm]?[jt]sx?$", name)
        ]
    )
    if not required:
        return False
    cleanup_failed = False
    passed = False
    node_modules.symlink_to(dependencies, target_is_directory=True)
    try:
        with tempfile.TemporaryDirectory(prefix="harness-node-verifier-") as temporary:
            report_path = Path(temporary) / "result.json"
            config = workspace / "vite.config.ts"
            if "vite.config.ts" not in manifest["files"]:
                config = Path(temporary) / "vitest.config.mjs"
                config.write_text("export default {};\n")
            result = subprocess.run(
                [
                    "node",
                    str(dependencies / "vitest/vitest.mjs"),
                    "run",
                    *required,
                    "--config",
                    str(config),
                    "--reporter=json",
                    "--outputFile",
                    str(report_path),
                ],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode in {0, 1} and report_path.is_file():
                report = json.loads(report_path.read_text())
                suites = {Path(row["name"]).resolve(): row for row in report.get("testResults", [])}
                valid_inventory = all(
                    (suite := suites.get((workspace / name).resolve())) is not None
                    and suite.get("assertionResults")
                    and all(
                        test.get("status") in {"passed", "failed"}
                        for test in suite["assertionResults"]
                    )
                    for name in required
                )
                failed = any(
                    test.get("status") == "failed"
                    for name in required
                    for test in suites.get((workspace / name).resolve(), {}).get(
                        "assertionResults", []
                    )
                )
                passed = valid_inventory and (
                    result.returncode == 1 and report.get("success") is False and failed
                    if expect_assertion_failure
                    else result.returncode == 0
                    and report.get("success") is True
                    and not failed
                    and all(
                        suites[(workspace / name).resolve()].get("status") == "passed"
                        for name in required
                    )
                )
            if not passed:
                print(result.stdout)
                print(result.stderr)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(error)
        return False
    finally:
        try:
            node_modules.unlink()
        except OSError:
            cleanup_failed = True
    return bool(passed) and not cleanup_failed and protected_files_intact(workspace, manifest_path)


def regression_tests_effective(workspace: Path, manifest_path: Path, dependencies: Path) -> bool:
    """Agent-added tests must pass the fix and fail the original implementation."""
    try:
        manifest = json.loads(manifest_path.read_text())
        regression = json.loads(manifest_path.with_name("Regression.json").read_text())
        added = [
            p.relative_to(workspace).as_posix()
            for p in workspace.rglob("*")
            if p.is_file()
            and re.search(r"\.(?:test|spec)\.[cm]?[jt]sx?$", p.name)
            and p.relative_to(workspace).as_posix() not in manifest["files"]
        ]
        if not added or not node_test_correctness(
            workspace, manifest_path, dependencies, test_files=added
        ):
            return False
        with tempfile.TemporaryDirectory(prefix="harness-regression-") as temporary:
            baseline = Path(temporary) / "workspace"
            shutil.copytree(
                workspace, baseline, ignore=shutil.ignore_patterns(".git", "node_modules", "target")
            )
            path = Path(regression["path"])
            if path.is_absolute() or ".." in path.parts:
                return False
            (baseline / path).write_text(regression["original"])
            return node_test_correctness(
                baseline,
                manifest_path,
                dependencies,
                test_files=added,
                expect_assertion_failure=True,
            )
    except (OSError, ValueError, KeyError, TypeError):
        return False


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
    manifest = json.loads(manifest_path.read_text())
    required = {
        name
        for path in manifest["files"]
        if path.endswith(".rs")
        for name in re.findall(r"#\[test\]\s*fn\s+(\w+)", (workspace / path).read_text())
    }
    if not required:
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
    observed = set(re.findall(r"^test (?:\w+::)*(\w+) \.\.\. ok$", result.stdout, re.MULTILINE))
    return (
        result.returncode == 0
        and required <= observed
        and protected_files_intact(workspace, manifest_path)
    )


def _tool_paths(call: dict[str, Any]) -> tuple[str, ...]:
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return ()
    paths = [
        value for key in ("file_path", "path") if isinstance((value := arguments.get(key)), str)
    ]
    patch = arguments.get("patch") or arguments.get("input")
    if isinstance(patch, str):
        paths.extend(patch_paths(patch))
    return tuple(paths)


def _normalize(command: str) -> str:
    return normalize_command(command, _IGNORED_FLAGS, _REMOVABLE_PREFIXES)


@dataclass(frozen=True)
class _WorkflowEvent:
    kind: str
    command: str | None
    success: bool | None
    call: int
    position: int
    started: datetime | None
    completed: datetime | None
    interval: bool


def _before(left: _WorkflowEvent, right: _WorkflowEvent) -> bool:
    if left.call == right.call or not (left.interval or right.interval):
        return left.position < right.position
    return (
        left.completed is not None and right.started is not None and left.completed < right.started
    )


def _events() -> list[_WorkflowEvent]:
    try:
        trajectory = json.loads(_trajectory_path().read_text())
    except (OSError, json.JSONDecodeError):
        return []
    events: list[_WorkflowEvent] = []

    def emit(event: tuple[str, str | None, bool | None]) -> None:
        events.append(
            _WorkflowEvent(*event, call_position, len(events), started, completed, interval)
        )

    for step in trajectory.get("steps", []):
        extra = step.get("extra") or {}
        interval = "command_completed_at" in extra
        start = step.get("timestamp")
        end = extra.get("command_completed_at", start)
        try:
            started = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
            completed = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None
        except (ValueError, AttributeError):
            started = completed = None
        observation = step.get("observation") or {}
        results = {
            result.get("source_call_id"): result
            for result in observation.get("results", [])
            if result.get("source_call_id") is not None
        }
        for call in step.get("tool_calls") or []:
            call_position = len(events)
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
                    emit(("mutation", None, None))
                elif success is not False and not paths:
                    emit(("unknown_mutation", None, None))
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
                    emit(("mutation", None, None))
                elif mutation in {"relevant", "unknown"} and component_success is not False:
                    emit(("unknown_mutation", None, None))
                emit(("command", _normalize(component.command), component_success))
            emit(("duplicate", _normalize(command), success))
    return events


def command_after_last_mutation(command: str) -> bool:
    """Return true when the required command succeeds after all relevant edits."""

    events = _events()
    mutations = [event for event in events if event.kind in {"mutation", "unknown_mutation"}]
    required = _normalize(command)
    return any(
        event.kind == "command"
        and event.command == required
        and event.success is True
        and all(_before(mutation, event) for mutation in mutations)
        for event in events
    )


def command_succeeded(command: str) -> bool:
    """Return true when the required command succeeds anywhere in the trajectory."""

    required = _normalize(command)
    return any(
        event.kind == "command" and event.command == required and event.success is True
        for event in _events()
    )


def python_script_after_last_mutation(script: str) -> bool:
    """Recognize equivalent Python invocations of a required workspace check."""
    events = _events()
    mutations = [event for event in events if event.kind in {"mutation", "unknown_mutation"}]
    for event in events:
        if event.kind != "command" or event.success is not True or not event.command:
            continue
        try:
            arguments = shlex.split(event.command)
        except ValueError:
            continue
        if (
            len(arguments) == 2
            and re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(arguments[0]).name)
            and arguments[1] in {script, f"./{script}", f"/app/{script}"}
            and all(_before(mutation, event) for mutation in mutations)
        ):
            return True
    return False


def verification_after_last_mutation() -> bool:
    """Accept equivalent successful test runners instead of a hidden filename."""
    events = _events()
    mutations = [event for event in events if event.kind in {"mutation", "unknown_mutation"}]
    return any(
        event.kind == "command"
        and event.success is True
        and event.command is not None
        and re.match(
            r"^(?:(?:npm|pnpm|yarn) (?:run )?test(?:\s|$)|npx vitest run(?:\s|$)|"
            r"cargo test(?:\s|$)|node --test(?:\s|$))",
            event.command,
        )
        and all(_before(mutation, event) for mutation in mutations)
        for event in events
    )


def cargo_packages_succeeded(packages: Sequence[str]) -> bool:
    """Return true when successful focused Cargo tests cover every package."""

    required = set(packages)
    selected: set[str] = set()
    for event in _events():
        if event.kind != "command" or event.command is None or event.success is not True:
            continue
        try:
            arguments = shlex.split(event.command)
        except ValueError:
            continue
        if arguments[:2] != ["cargo", "test"]:
            continue
        for index, argument in enumerate(arguments[:-1]):
            if argument in {"-p", "--package"}:
                selected.add(arguments[index + 1])
    return bool(required) and required <= selected


def no_comprehensive_commands() -> bool:
    """Return false for any observed comprehensive command."""

    return not any(
        event.kind == "command" and event.command in _COMPREHENSIVE_COMMANDS for event in _events()
    )


def no_testing_churn() -> bool:
    """Reject premature comprehensive checks and duplicate successful commands."""

    events = _events()
    mutations = [event for event in events if event.kind in {"mutation", "unknown_mutation"}]
    if any(event.kind == "unknown_mutation" for event in mutations):
        return False
    previous: dict[str, _WorkflowEvent] = {}
    for event in events:
        if event.success is not True or event.command is None:
            continue
        if event.kind == "command" and event.command in _COMPREHENSIVE_COMMANDS:
            if not all(_before(mutation, event) for mutation in mutations):
                return False
        elif event.kind == "duplicate":
            earlier = previous.get(event.command)
            if earlier is not None and not any(
                _before(earlier, mutation) and _before(mutation, event) for mutation in mutations
            ):
                return False
            previous[event.command] = event
    return True
