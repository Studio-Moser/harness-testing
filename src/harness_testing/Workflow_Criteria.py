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
    _content_text,
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
# House conventions: {type}/{kebab-case-desc} branches and Conventional Commit subjects.
_BRANCH_NAME = re.compile(
    r"(?:feat|fix|style|chore|docs|refactor|test|perf|hotfix|release|feature|bugfix)"
    r"/[a-z0-9]+(?:[-.][a-z0-9]+)*"
)
_COMMIT_SUBJECT = re.compile(
    r"(?:feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\([^()\s]+\))?!?: \S.*"
)
_COMMIT_CONFIRMATION = re.compile(r"^\[(\S+)(?: \(root-commit\))? [0-9a-f]{7,40}\] ", re.MULTILINE)
_HEREDOC_MESSAGE = re.compile(
    r'"\$\(\s*cat\s*<<-?\s*([\'"]?)(\w+)\1[ \t]*\n(.*?)\n[ \t]*\2\s*\)"', re.DOTALL
)
_HEREDOC_STDIN_MESSAGE = re.compile(
    r"""(?:-F|--file)[ =]?-(?=\s)([^\n]*?)<<-?[ \t]*(['"]?)(\w+)\2([^\n]*)\n"""
    r"""(.*?)\n[ \t]*\3[ \t]*$""",
    re.DOTALL | re.MULTILINE,
)
_HEREDOC = re.compile(
    r"""<<-?[ \t]*(['"]?)(\w+)\1([^\n]*)\n(?:.*?\n)??[ \t]*\2[ \t]*$""",
    re.DOTALL | re.MULTILINE,
)
# Names fixed by tooling or ecosystem convention; everything else follows the house rule.
_TOOLING_FILE_NAMES = frozenset(
    {
        "README.md", "AGENTS.md", "CLAUDE.md", "SKILL.md", "CHANGELOG.md", "LICENSE",
        "Makefile", "Dockerfile", "package.json", "package-lock.json", "yarn.lock",
        "pnpm-lock.yaml", "tsconfig.json", "Cargo.toml", "Cargo.lock", "index.html",
        "index.css", "index.js", "index.ts", "index.tsx", "main.rs", "lib.rs", "mod.rs",
    }
)
_ARM_INJECTED_FILE_NAMES = {"AGENTS.md", "CLAUDE.md"}
_TITLE_MINOR_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "with",
}
_NOTES_SUFFIXES = {".md", ".markdown", ".txt"}
# Git subcommands that cannot move a branch or create a commit.
_GIT_HISTORY_NEUTRAL = {
    "add", "apply", "blame", "cat-file", "check-ignore", "clean", "config", "describe", "diff",
    "fetch", "grep", "help", "log", "ls-files", "ls-tree", "merge-base", "mv", "push", "reflog",
    "remote", "restore", "rev-list", "rev-parse", "rm", "shortlog", "show", "show-ref", "status",
    "tag", "version",
}
_GIT_WORKTREE_CHANGING = {"apply", "mv", "rm"}
_GIT_UNREADABLE_MESSAGE = {
    "-F", "--file", "-C", "-c", "--reuse-message", "--reedit-message", "--fixup", "--squash",
    "-t", "--template",
}
_SHELL_WRAPPERS = {"bash", "sh", "zsh", "env", "sudo", "time", "xargs", "eval", "exec", "nohup"}


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


def _strip_heredocs(command: str) -> str:
    """Inline heredoc commit messages and drop other heredoc bodies before splitting."""
    command = _HEREDOC_MESSAGE.sub(lambda match: shlex.quote(match[3]), command)
    command = _HEREDOC_STDIN_MESSAGE.sub(
        lambda match: f"-m {shlex.quote(match[5])}{match[1]}{match[4]}", command
    )
    return _HEREDOC.sub(lambda match: match[3], command).replace("\\\n", " ")


def _proven_successes(
    components: Sequence[ShellComponent], overall: bool | None
) -> list[bool | None]:
    """Extend component outcomes with the trailing `&&` chain a zero exit proves."""
    statuses = list(component_successes(components, overall))
    index = len(components) - 1
    if overall is True and index >= 0 and components[index].operator_before != "||":
        statuses[index] = True
        while (
            index > 0
            and components[index].operator_before == "&&"
            and components[index - 1].operator_before != "||"
        ):
            index -= 1
            statuses[index] = True
    return statuses


def _inside_workspace(path: str) -> bool:
    return not path.startswith("/") or path.startswith("/app")


def _git_segments(component: str) -> tuple[list[list[str]], bool] | None:
    """Argument lists of each Git invocation and whether their output and status are visible."""
    lexer = shlex.shlex(component, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None if re.search(r"\bgit\b", component) else ([], False)
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"|", "|&"}:
            segments.append([])
        else:
            segments[-1].append(token)
    found: list[list[str]] = []
    visible = len(segments) == 1
    for segment in segments:
        while segment and (segment[0] == "(" or re.match(r"[A-Za-z_]\w*=", segment[0])):
            segment = segment[1:]
        for index, token in enumerate(segment):
            if not token.strip("();<>&"):
                segment, visible = segment[:index], visible and token == ")"
                break
        if not segment:
            continue
        if segment[0] in _SHELL_WRAPPERS and re.search(r"\bgit\b", " ".join(segment)):
            return None
        if segment[0] == "git":
            found.append(segment[1:])
    return found, visible


def _git_action(arguments: list[str]) -> tuple:
    """Classify one Git invocation by its effect on branches and commits."""
    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        option = arguments[index]
        if option == "-C" and not _inside_workspace("".join(arguments[index + 1 : index + 2])):
            return ("none",)  # another repository cannot move this one
        if option in {"-c", "-C"}:
            index += 2
        elif option == "--no-pager":
            index += 1
        else:
            return ("unknown",)
    if index >= len(arguments):
        return ("none",)
    subcommand, rest = arguments[index], arguments[index + 1 :]
    before_paths = rest[: rest.index("--")] if "--" in rest else rest
    positional = [value for value in before_paths if not value.startswith("-")]

    def after(pattern: str) -> str | None:
        for position, value in enumerate(before_paths[:-1]):
            if re.fullmatch(pattern, value):
                return before_paths[position + 1]
        return None

    if subcommand in {"checkout", "switch"}:
        create = (
            r"-[A-Za-z]*[bB]|--orphan"
            if subcommand == "checkout"
            else r"-[A-Za-z]*[cC]|--create|--force-create|--orphan"
        )
        if name := after(create):
            return ("create", name)
        if "-" in before_paths or "--detach" in before_paths:
            return ("unknown",)
        if not positional or "--" in rest:
            return ("none",)  # restores paths; HEAD stays where it is
        return ("switch", positional[0], subcommand == "switch")
    if subcommand == "branch":
        if any(re.fullmatch(r"-[mM]|--move", value) for value in before_paths):
            if len(positional) not in {1, 2}:
                return ("unknown",)
            return ("rename", positional[0] if len(positional) == 2 else None, positional[-1])
        if any(re.fullmatch(r"-[dD]|--delete", value) for value in before_paths):
            return ("delete", *positional)
        if "--show-current" in before_paths or not positional:
            return ("none",)
        if any(re.fullmatch(r"-[cC]|--copy", value) for value in before_paths):
            return ("add", positional[-1])
        return ("add", positional[0])
    if subcommand == "commit":
        if "--dry-run" in rest:
            return ("none",)
        message = after(r"-[A-Za-z]*m|--message")
        for value in rest:
            if message is None and value.startswith("--message="):
                message = value.removeprefix("--message=")
        subject = message.strip().splitlines()[0].strip() if message and message.strip() else None
        unreadable = subject is None and bool(_GIT_UNREADABLE_MESSAGE & set(rest))
        quiet = any(re.fullmatch(r"-[A-Za-z]*q[A-Za-z]*|--quiet", value) for value in rest)
        return ("commit", subject, "--amend" in rest, unreadable, quiet)
    if subcommand == "reset":
        return ("none",) if all(value == "HEAD" for value in positional) else ("unknown",)
    if subcommand == "stash":
        return ("unknown",) if rest[:1] == ["branch"] else ("none",)
    if subcommand == "worktree":
        return ("none",) if rest[:1] in (["list"], ["prune"]) else ("unknown",)
    if subcommand in _GIT_WORKTREE_CHANGING:
        return ("change",)
    return ("none",) if subcommand in _GIT_HISTORY_NEUTRAL else ("unknown",)


@dataclass(frozen=True)
class _GitHistory:
    commits: tuple[tuple[str, str | None], ...]
    branch: str
    settled: bool


def _git_history() -> _GitHistory | None:
    """Replay the trajectory's Git commands; None when the outcome cannot be determined."""
    try:
        trajectory = json.loads(_trajectory_path().read_text())
    except (OSError, json.JSONDecodeError):
        return None
    branch, branches = "main", {"main"}
    commits: list[tuple[str, str | None]] = []
    settled = True
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
            result = results.get(call_id)
            success = result_success(
                result,
                step_extra=step.get("extra"),
                call_id=call_id if isinstance(call_id, str) else None,
            )
            if name in _MUTATION_TOOLS:
                paths = _tool_paths(call)
                if success is not False and (not paths or any(map(_inside_workspace, paths))):
                    settled = False
                continue
            command = arguments.get("command") or arguments.get("cmd")
            if name not in _SHELL_TOOLS or not isinstance(command, str):
                continue
            # Git prints "[branch hash] subject" for a commit that landed.
            output = _content_text(result)
            confirmed = set(_COMMIT_CONFIRMATION.findall(output))
            components = split_shell(_strip_heredocs(command))
            statuses = _proven_successes(components, success)
            for component, outcome in zip(components, statuses, strict=True):
                parsed = _git_segments(component.command)
                if parsed is None:
                    return None
                segments, visible = parsed
                if not segments:
                    mutation, paths = shell_mutation(
                        component.command, _SHELL_MUTATION_PATTERNS, _RELEVANT_PATH_PATTERNS
                    )
                    if (
                        mutation != "none"
                        and outcome is not False
                        and (not paths or any(map(_inside_workspace, paths)))
                    ):
                        settled = False
                    continue
                if not visible:
                    outcome = None  # a pipeline reports only its last command
                for action in map(_git_action, segments):
                    kind = action[0]
                    if kind == "none" or outcome is False:
                        continue
                    if kind == "unknown":
                        return None
                    if kind == "change":
                        settled = False
                    elif kind == "create":
                        if outcome is None and action[1] in branches:
                            return None
                        branch = action[1]
                        branches.add(branch)
                    elif kind == "switch":
                        if action[1] in branches:
                            branch = action[1]
                        elif action[2] or re.fullmatch(
                            r"(?:HEAD|@|[0-9a-f]{7,40})(?:[~^]\d*)*|.*[~^].*", action[1]
                        ):
                            return None
                    elif kind == "rename":
                        old = action[1] or branch
                        branches.discard(old)
                        branches.add(action[2])
                        if old == branch:
                            branch = action[2]
                    elif kind == "delete":
                        branches -= set(action[1:])
                    elif kind == "add":
                        branches.add(action[1])
                    elif kind == "commit":
                        _, subject, amend, unreadable, quiet = action
                        if confirmed - {branch}:
                            return None
                        logged = subject is not None and re.search(
                            rf"^[0-9a-f]{{7,40}} (?:\([^)\n]*\) )?{re.escape(subject)}$",
                            output,
                            re.MULTILINE,
                        )
                        if outcome is None and branch not in confirmed and not logged:
                            if quiet or not visible or not output.strip():
                                return None
                            continue  # Git would have printed the commit it made
                        if not amend:
                            commits.append((branch, subject))
                        elif not commits:
                            return None
                        elif subject is not None or unreadable:
                            commits[-1] = (commits[-1][0], subject)
                        settled = True
    return _GitHistory(tuple(commits), branch, settled)


def _created_files(
    workspace: Path, manifest_path: Path, baseline: Sequence[str]
) -> list[Path] | None:
    """Workspace files absent from the frozen fixture, outside tool-owned directories."""
    try:
        manifest = json.loads(manifest_path.read_text())
        known = {*manifest["files"], *manifest["mutable_files"], *baseline}
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    created = []
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if (
            path.is_file()
            and relative.as_posix() not in known
            and not {"node_modules", "target", "dist"} & set(relative.parts)
            and not any(part.startswith(".") for part in relative.parts[:-1])
        ):
            created.append(relative)
    return created


def _house_file_name(name: str) -> bool:
    """Title Case words joined by spaces or underscores; dashes only separate segments.

    A word is capitalized or an acronym, so `ToggleDone` reads as two unseparated words.
    """
    if name in _TOOLING_FILE_NAMES or name.startswith("."):
        return True
    stem = name.split(".", 1)[0]
    if not any(character.islower() for character in stem):
        return False
    return all(
        re.fullmatch(r"v?\d+(?:_\d+)*", segment)
        or all(
            re.fullmatch(r"[A-Z0-9][a-z0-9]*|[A-Z0-9]+", word)
            or (index and word in _TITLE_MINOR_WORDS)
            for index, word in enumerate(re.split(r"[ _]", segment))
        )
        for segment in stem.split("-")
    )


def notes_document_added(
    workspace: Path, manifest_path: Path, baseline: Sequence[str] = ()
) -> bool:
    """Return true when the submission adds a nonempty text document of any name."""
    try:
        return any(
            path.suffix.lower() in _NOTES_SUFFIXES
            and path.name not in _ARM_INJECTED_FILE_NAMES
            and (workspace / path).read_text().strip()
            for path in _created_files(workspace, manifest_path, baseline) or []
        )
    except (OSError, UnicodeDecodeError):
        return False


def house_conventions(workspace: Path, manifest_path: Path, baseline: Sequence[str] = ()) -> bool:
    """Committed branch work, Conventional Commit subjects and house file names.

    The verifier sees the trajectory and the workspace, never `.git`, so Git state is
    replayed from the recorded commands. Anything that cannot be determined fails.
    """
    history = _git_history()
    created = _created_files(workspace, manifest_path, baseline)
    if history is None or created is None:
        print("conventions: Git history or created files could not be determined")
        return False
    problems = [
        *(
            f"branch {name!r} is not {{type}}/{{kebab-case-desc}}"
            for name in dict.fromkeys([*(name for name, _ in history.commits), history.branch])
            if not _BRANCH_NAME.fullmatch(name)
        ),
        *(
            f"commit subject {subject!r} is not a Conventional Commit"
            for _, subject in history.commits
            if subject is None or not _COMMIT_SUBJECT.fullmatch(subject)
        ),
        *(
            f"created file {path.as_posix()!r} does not follow the house naming rule"
            for path in created
            if not _house_file_name(path.name)
        ),
    ]
    if not history.commits:
        problems.append("no commit landed")
    elif not history.settled:
        problems.append("the workspace changed after the last commit")
    for problem in problems:
        print(f"conventions: {problem}")
    return not problems
