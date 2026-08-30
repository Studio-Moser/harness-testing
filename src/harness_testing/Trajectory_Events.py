"""Provider-shaped ATIF result and shell-event primitives shared by scorers."""

from __future__ import annotations

import re
import shlex
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_NON_MUTATING_REDIRECTION = re.compile(
    r"(?<!\S)(?:(?:\d+|&)?>>?\s*/dev/null|(?:\d+)?[<>]&\d+)(?=\s|$)"
)


@dataclass(frozen=True)
class ShellComponent:
    command: str
    operator_before: str | None


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _metadata(value: object, call_id: str | None) -> tuple[Mapping[str, Any], ...]:
    extra = _field(value, "extra")
    values: list[Mapping[str, Any]] = []
    if isinstance(extra, Mapping):
        details = extra.get("tool_call_details")
        top_level = {
            key: child for key, child in extra.items() if key != "tool_call_details"
        }
        if top_level:
            values.append(top_level)
        if call_id and isinstance(details, Mapping):
            call_details = details.get(call_id)
            if isinstance(call_details, Mapping):
                values.append(call_details)
    return tuple(values)


def _walk_metadata(value: object, *, depth: int = 0) -> tuple[list[int], bool]:
    if depth > 8 or not isinstance(value, Mapping):
        return [], False
    exit_codes: list[int] = []
    is_error = False
    for key, child in value.items():
        if key in {"exit_code", "exitCode"} and isinstance(child, int) and not isinstance(
            child, bool
        ):
            exit_codes.append(child)
        elif key in {"is_error", "tool_result_is_error"} and child is True:
            is_error = True
        if isinstance(child, Mapping):
            child_codes, child_error = _walk_metadata(child, depth=depth + 1)
            exit_codes.extend(child_codes)
            is_error = is_error or child_error
    return exit_codes, is_error


def _content_text(value: object) -> str:
    content = _field(value, "content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        text = _field(part, "text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def result_success(
    result: object | None,
    *,
    step_extra: object | None = None,
    call_id: str | None = None,
) -> bool | None:
    """Decode authoritative exit status from pinned Claude/Codex ATIF shapes."""

    if result is None:
        return None
    codes: list[int] = []
    is_error = False
    for source in (*_metadata(result, call_id), *_metadata({"extra": step_extra}, call_id)):
        source_codes, source_error = _walk_metadata(source)
        codes.extend(source_codes)
        is_error = is_error or source_error
    if codes:
        outcomes = {code == 0 for code in codes}
        if len(outcomes) == 1:
            return outcomes.pop() and not is_error
        return None
    if is_error:
        return False

    text = _content_text(result)
    match = re.search(
        r"(?:\[\s*exit[_ ]code\s*\]|exit[_ ]code|process exited with code)"
        r"\s*[:=]?\s*(-?\d+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return int(match[1]) == 0
    if re.search(r"\[error\]\s*tool reported failure", text, re.IGNORECASE):
        return False
    return None


def split_shell(command: str) -> tuple[ShellComponent, ...]:
    """Split supported shell sequencing operators without evaluating the command."""

    components: list[ShellComponent] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    operator_before: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            current.append(character)
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            current.append(character)
            escaped = True
            index += 1
            continue
        if quote:
            current.append(character)
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            current.append(character)
            index += 1
            continue

        operator: str | None = None
        if command[index : index + 2] in {"&&", "||"}:
            operator = command[index : index + 2]
        elif character in {";", "\n"}:
            operator = character
        if operator is None:
            current.append(character)
            index += 1
            continue

        component = "".join(current).strip()
        if component:
            components.append(ShellComponent(component, operator_before))
            current = []
        operator_before = operator
        index += len(operator)

    component = "".join(current).strip()
    if component:
        components.append(ShellComponent(component, operator_before))
    return tuple(components)


def component_successes(
    components: Sequence[ShellComponent], overall: bool | None
) -> tuple[bool | None, ...]:
    """Return only component outcomes proven by a shell command's overall status."""

    if not components:
        return ()
    if len(components) == 1:
        return (overall,)
    statuses: list[bool | None] = [None] * len(components)
    if overall is True and all(
        component.operator_before == "&&" for component in components[1:]
    ):
        return tuple(True for _ in components)
    if components[-1].operator_before in {";", "\n"}:
        statuses[-1] = overall
        if overall is True:
            index = len(components) - 1
            while index > 0 and components[index].operator_before == "&&":
                statuses[index - 1] = True
                index -= 1
    return tuple(statuses)


def normalize_command(
    command: str,
    ignored_flags: Collection[str],
    removable_prefixes: Sequence[Sequence[str]],
) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return " ".join(command.split())
    for prefix in removable_prefixes:
        if tuple(tokens[: len(prefix)]) == tuple(prefix):
            tokens = tokens[len(prefix) :]
            break
    return " ".join(token for token in tokens if token not in ignored_flags)


def patch_paths(patch: str) -> tuple[str, ...]:
    paths = re.findall(
        r"^(?:\*\*\* (?:Add|Update|Delete) File:|\+\+\+ b/)\s*(.+)$",
        patch,
        re.MULTILINE,
    )
    return tuple(path.strip() for path in paths)


def _candidate_paths(command: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    paths: list[str] = []
    relevant_roots = {"src", "app", "lib", "tests", "crates", "packages"}
    for token in tokens:
        candidate = token.lstrip("<>").rstrip(",")
        if not candidate or candidate.startswith("-"):
            continue
        if (
            "/" in candidate
            or candidate in relevant_roots
            or re.search(r"\.[A-Za-z0-9_-]+$", candidate)
        ):
            paths.append(candidate)
    paths.extend(
        re.findall(
            r"(?:/app/)?(?:src|app|lib|tests|crates|packages)"
            r"(?:/[A-Za-z0-9_.-]+)+",
            command,
            re.IGNORECASE,
        )
    )
    return tuple(dict.fromkeys(paths))


def shell_mutation(
    command: str,
    mutation_patterns: Sequence[str | re.Pattern[str]],
    relevant_path_patterns: Sequence[str | re.Pattern[str]],
) -> tuple[str, tuple[str, ...]]:
    candidate_command = _NON_MUTATING_REDIRECTION.sub("", command)
    compiled_mutations = tuple(
        pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, re.IGNORECASE)
        for pattern in mutation_patterns
    )
    if not any(pattern.search(candidate_command) for pattern in compiled_mutations):
        return "none", ()
    paths = _candidate_paths(candidate_command)
    if not paths:
        return "unknown", ()
    compiled_paths = tuple(
        pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, re.IGNORECASE)
        for pattern in relevant_path_patterns
    )
    if any(
        pattern.search(path.removeprefix("/app/"))
        for path in paths
        for pattern in compiled_paths
    ):
        return "relevant", paths
    return "irrelevant", paths
