"""Conservatively classify ATIF commands and report testing churn."""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Trajectory
from harbor.models.trajectories.observation_result import ObservationResult
from harbor.models.trajectories.tool_call import ToolCall

from harness_testing.Trajectory_Events import (
    ShellComponent,
    component_successes,
    normalize_command,
    patch_paths,
    result_success,
    shell_mutation,
    split_shell,
)


@dataclass(frozen=True)
class _ClassRule:
    name: str
    rank: int
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class MetricPolicy:
    classifier_schema: str
    task_policy_digest: str
    shell_tools: frozenset[str]
    mutation_tools: frozenset[str]
    command_arguments: tuple[str, ...]
    path_arguments: tuple[str, ...]
    ignored_flags: frozenset[str]
    removable_prefixes: tuple[tuple[str, ...], ...]
    class_rules: tuple[_ClassRule, ...]
    relevant_path_patterns: tuple[re.Pattern[str], ...]
    shell_mutation_patterns: tuple[re.Pattern[str], ...]
    track_premature_comprehensive: bool
    track_duplicate_success: bool


@dataclass(frozen=True)
class CommandComponent:
    command: str
    normalized: str
    scope: str
    rank: int


@dataclass(frozen=True)
class CommandClassification:
    scope: str
    components: tuple[CommandComponent, ...]


@dataclass(frozen=True)
class CommandRecord:
    step_id: int
    tool_name: str
    command: str
    normalized: str
    scope: str
    components: tuple[CommandComponent, ...]
    success: bool | None
    duration_seconds: float | None


@dataclass(frozen=True)
class MetricReport:
    metrics: dict[str, int | float | None]
    command_records: tuple[CommandRecord, ...]
    classifier_schema: str
    task_policy_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "metrics": self.metrics,
            "commands": [
                {
                    "step_id": record.step_id,
                    "tool_name": record.tool_name,
                    "command": record.command,
                    "normalized": record.normalized,
                    "scope": record.scope,
                    "components": [
                        {
                            "command": component.command,
                            "normalized": component.normalized,
                            "scope": component.scope,
                        }
                        for component in record.components
                    ],
                    "success": record.success,
                    "duration_seconds": record.duration_seconds,
                }
                for record in self.command_records
            ],
            "classifier_schema": self.classifier_schema,
            "task_policy_digest": self.task_policy_digest,
        }


def _compile_patterns(values: object, description: str) -> tuple[re.Pattern[str], ...]:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"{description} must be a list of regular expressions")
    try:
        return tuple(re.compile(value, re.IGNORECASE) for value in values)
    except re.error as error:
        raise ValueError(f"invalid {description}: {error}") from error


def _string_list(value: object, description: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{description} must be a list of strings")
    return tuple(value)


def load_metric_policy(
    command_policy_path: Path,
    envelopes_path: Path,
    envelope_name: str,
) -> MetricPolicy:
    with command_policy_path.open("rb") as policy_file:
        command_policy = tomllib.load(policy_file)
    with envelopes_path.open("rb") as envelope_file:
        envelopes = tomllib.load(envelope_file)
    raw_envelope = envelopes.get("envelopes", {}).get(envelope_name)
    if not isinstance(raw_envelope, dict):
        raise ValueError(f"unknown verification envelope: {envelope_name}")
    tools = command_policy.get("tools", {})
    normalization = command_policy.get("normalization", {})
    mutation = command_policy.get("mutation", {})
    raw_rules = command_policy.get("classes")
    if not isinstance(raw_rules, list):
        raise ValueError("command policy classes must be a list")
    rules: list[_ClassRule] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ValueError("every command class must be an object")
        rules.append(
            _ClassRule(
                name=str(raw_rule["name"]),
                rank=int(raw_rule["rank"]),
                patterns=_compile_patterns(
                    raw_rule.get("patterns"), f"{raw_rule.get('name')} patterns"
                ),
            )
        )
    digest = hashlib.sha256()
    digest.update(command_policy_path.read_bytes())
    digest.update(b"\0")
    digest.update(envelopes_path.read_bytes())
    digest.update(b"\0")
    digest.update(envelope_name.encode())
    return MetricPolicy(
        classifier_schema=str(command_policy["schema_version"]),
        task_policy_digest=f"sha256:{digest.hexdigest()}",
        shell_tools=frozenset(_string_list(tools.get("shell"), "shell tools")),
        mutation_tools=frozenset(
            _string_list(tools.get("mutation"), "mutation tools")
        ),
        command_arguments=_string_list(
            tools.get("command_arguments"), "command arguments"
        ),
        path_arguments=_string_list(tools.get("path_arguments"), "path arguments"),
        ignored_flags=frozenset(
            _string_list(normalization.get("ignored_flags"), "ignored flags")
        ),
        removable_prefixes=tuple(
            tuple(prefix.split())
            for prefix in _string_list(
                normalization.get("removable_prefixes"), "removable prefixes"
            )
        ),
        class_rules=tuple(rules),
        relevant_path_patterns=_compile_patterns(
            mutation.get("relevant_path_patterns"), "relevant path patterns"
        ),
        shell_mutation_patterns=_compile_patterns(
            mutation.get("shell_mutation_patterns"), "shell mutation patterns"
        ),
        track_premature_comprehensive=bool(
            raw_envelope.get("track_premature_comprehensive")
        ),
        track_duplicate_success=bool(raw_envelope.get("track_duplicate_success")),
    )


def _normalize_command(command: str, policy: MetricPolicy) -> str:
    return normalize_command(
        command,
        policy.ignored_flags,
        policy.removable_prefixes,
    )


def _classify_component(command: str, policy: MetricPolicy) -> CommandComponent:
    normalized = _normalize_command(command, policy)
    matches = [
        rule
        for rule in policy.class_rules
        if any(pattern.search(normalized) for pattern in rule.patterns)
    ]
    if not matches:
        return CommandComponent(
            command=command,
            normalized=normalized,
            scope="unknown",
            rank=0,
        )
    selected = max(matches, key=lambda rule: rule.rank)
    return CommandComponent(
        command=command,
        normalized=normalized,
        scope=selected.name,
        rank=selected.rank,
    )


def classify_command(command: str, policy: MetricPolicy) -> CommandClassification:
    components = tuple(
        _classify_component(component.command, policy)
        for component in split_shell(command)
    )
    if not components:
        components = (_classify_component(command, policy),)
    return CommandClassification(
        scope=max(components, key=lambda component: component.rank).scope,
        components=components,
    )


def _tool_duration(tool_call: ToolCall, result: ObservationResult | None) -> float | None:
    for extra in (tool_call.extra, result.extra if result else None):
        if extra and isinstance(extra.get("duration_seconds"), int | float):
            return float(extra["duration_seconds"])
    return None


def _tool_command(tool_call: ToolCall, policy: MetricPolicy) -> str | None:
    for argument in policy.command_arguments:
        value = tool_call.arguments.get(argument)
        if isinstance(value, str):
            return value
    return None


def _tool_paths(tool_call: ToolCall, policy: MetricPolicy) -> tuple[str, ...]:
    paths: list[str] = []
    for argument in policy.path_arguments:
        value = tool_call.arguments.get(argument)
        if isinstance(value, str):
            paths.append(value)
    if tool_call.function_name == "apply_patch":
        patch = tool_call.arguments.get("patch") or tool_call.arguments.get("input")
        if isinstance(patch, str):
            paths.extend(patch_paths(patch))
    return tuple(dict.fromkeys(paths))


def _is_relevant_path(path: str, policy: MetricPolicy) -> bool:
    normalized = path.removeprefix("/app/")
    return any(pattern.search(normalized) for pattern in policy.relevant_path_patterns)


def _shell_mutation(
    command: str, policy: MetricPolicy
) -> tuple[str, tuple[str, ...]]:
    return shell_mutation(
        command,
        policy.shell_mutation_patterns,
        policy.relevant_path_patterns,
    )


def _tool_mutation(
    tool_call: ToolCall,
    command: str | None,
    policy: MetricPolicy,
) -> tuple[str, tuple[str, ...]]:
    if tool_call.function_name in policy.mutation_tools:
        paths = _tool_paths(tool_call, policy)
        if not paths:
            return "unknown", ()
        if any(_is_relevant_path(path, policy) for path in paths):
            return "relevant", paths
        return "irrelevant", paths
    if command is not None:
        return _shell_mutation(command, policy)
    return "none", ()


def _metadata_number(
    context: AgentContext | None, key: str, expected_type: type[int] | type[float]
) -> int | float | None:
    if context is None or context.metadata is None:
        return None
    value = context.metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return expected_type(value)


def _trajectory_seconds(trajectory: Trajectory) -> float | None:
    timestamps = [step.timestamp for step in trajectory.steps if step.timestamp]
    if len(timestamps) < 2:
        return None
    try:
        start = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (end - start).total_seconds())


def _telemetry(
    trajectory: Trajectory, context: AgentContext | None
) -> tuple[int | None, int | None, int | None, int | None, float | None]:
    final = trajectory.final_metrics
    prompt_tokens = context.n_input_tokens if context else None
    completion_tokens = context.n_output_tokens if context else None
    cached_tokens = context.n_cache_tokens if context else None
    cost_usd = context.cost_usd if context else None
    if final:
        if prompt_tokens is None:
            prompt_tokens = final.total_prompt_tokens
        if completion_tokens is None:
            completion_tokens = final.total_completion_tokens
        if cached_tokens is None:
            cached_tokens = final.total_cached_tokens
        if cost_usd is None:
            cost_usd = final.total_cost_usd
    reasoning_tokens = _metadata_number(context, "reasoning_tokens", int)
    if reasoning_tokens is None and final and final.extra:
        value = final.extra.get("reasoning_tokens")
        if isinstance(value, int) and not isinstance(value, bool):
            reasoning_tokens = value
    return prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens, cost_usd


def _patch_diff_lines(tool_call: ToolCall) -> int | None:
    if tool_call.function_name != "apply_patch":
        return None
    patch = tool_call.arguments.get("patch") or tool_call.arguments.get("input")
    if not isinstance(patch, str):
        return None
    return sum(
        1
        for line in patch.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    )


def trajectory_metrics(
    trajectory: Trajectory,
    policy: MetricPolicy,
    *,
    agent_context: AgentContext | None = None,
    verifier_seconds: float | None = None,
) -> MetricReport:
    command_records: list[CommandRecord] = []
    successful_since_mutation: set[str] = set()
    pending_comprehensive = 0
    premature_comprehensive = 0
    duplicate_success = 0
    changed_paths: set[str] = set()
    unknown_mutation = False
    tool_call_count = 0
    plan_count = 0
    review_count = 0
    subagent_count = len(trajectory.subagent_trajectories or [])
    worktree_count = 0
    context_event_count = 0
    diff_lines: list[int] = []

    def record_mutation(
        mutation: str,
        paths: tuple[str, ...],
        success: bool | None,
        *,
        shell_component: bool,
    ) -> None:
        nonlocal pending_comprehensive, premature_comprehensive, unknown_mutation
        if success is False or mutation in {"none", "irrelevant"}:
            return
        if mutation == "relevant" and (success is True or not shell_component):
            changed_paths.update(
                path.removeprefix("/app/")
                for path in paths
                if _is_relevant_path(path, policy)
            )
            if policy.track_premature_comprehensive and pending_comprehensive:
                premature_comprehensive += pending_comprehensive
            pending_comprehensive = 0
            successful_since_mutation.clear()
            return
        if mutation in {"relevant", "unknown"}:
            unknown_mutation = True
            pending_comprehensive = 0
            successful_since_mutation.clear()

    for step in trajectory.steps:
        results = {
            result.source_call_id: result
            for result in step.observation.results
            if result.source_call_id is not None
        } if step.observation else {}
        for tool_call in step.tool_calls or []:
            tool_call_count += 1
            result = results.get(tool_call.tool_call_id)
            success = result_success(
                result,
                step_extra=step.extra,
                call_id=tool_call.tool_call_id,
            )
            command = _tool_command(tool_call, policy)

            if command is not None and tool_call.function_name in policy.shell_tools:
                shell_components = split_shell(command)
                if not shell_components:
                    shell_components = (ShellComponent(command, None),)
                component_classifications = tuple(
                    _classify_component(component.command, policy)
                    for component in shell_components
                )
                classification = CommandClassification(
                    scope=max(
                        component_classifications,
                        key=lambda component: component.rank,
                    ).scope,
                    components=component_classifications,
                )
                statuses = component_successes(shell_components, success)
                for shell_component, component, component_success in zip(
                    shell_components,
                    component_classifications,
                    statuses,
                    strict=True,
                ):
                    mutation, paths = _shell_mutation(shell_component.command, policy)
                    record_mutation(
                        mutation,
                        paths,
                        component_success,
                        shell_component=True,
                    )
                    if (
                        component_success is True
                        and component.scope == "comprehensive_test"
                    ):
                        pending_comprehensive += 1

                normalized = _normalize_command(command, policy)
                record = CommandRecord(
                    step_id=step.step_id,
                    tool_name=tool_call.function_name,
                    command=command,
                    normalized=normalized,
                    scope=classification.scope,
                    components=classification.components,
                    success=success,
                    duration_seconds=_tool_duration(tool_call, result),
                )
                command_records.append(record)
                if success is True:
                    if (
                        policy.track_duplicate_success
                        and normalized in successful_since_mutation
                    ):
                        duplicate_success += 1
                    successful_since_mutation.add(normalized)
                if "git worktree" in normalized:
                    worktree_count += 1
            else:
                mutation, paths = _tool_mutation(tool_call, None, policy)
                record_mutation(
                    mutation,
                    paths,
                    success,
                    shell_component=False,
                )

            name = tool_call.function_name.lower()
            if "plan" in name:
                plan_count += 1
            if "review" in name:
                review_count += 1
            if name in {"task", "spawn_agent", "delegate"}:
                subagent_count += 1
            if "context" in name or "compact" in name:
                context_event_count += 1
            if (lines := _patch_diff_lines(tool_call)) is not None:
                diff_lines.append(lines)

    prompt, completion, reasoning, cached, cost = _telemetry(trajectory, agent_context)
    test_scopes = {"targeted_test", "package_test", "comprehensive_test"}
    test_durations = [
        record.duration_seconds
        for record in command_records
        if record.scope in test_scopes and record.duration_seconds is not None
    ]
    turns = sum(
        step.llm_call_count if step.llm_call_count is not None else 1
        for step in trajectory.steps
        if step.source == "agent"
    )
    agent_seconds = _metadata_number(agent_context, "agent_seconds", float)
    if agent_seconds is None:
        agent_seconds = _trajectory_seconds(trajectory)
    if verifier_seconds is None:
        verifier_seconds = _metadata_number(agent_context, "verifier_seconds", float)
    metrics: dict[str, int | float | None] = {
        "agent_seconds": agent_seconds,
        "verifier_seconds": verifier_seconds,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
        "cost_usd": cost,
        "turns": turns,
        "tool_calls": tool_call_count,
        "commands": len(command_records),
        "direct_checks": sum(record.scope == "direct_check" for record in command_records),
        "targeted_tests": sum(record.scope == "targeted_test" for record in command_records),
        "package_tests": sum(record.scope == "package_test" for record in command_records),
        "comprehensive_tests": sum(
            record.scope == "comprehensive_test" for record in command_records
        ),
        "test_seconds": sum(test_durations) if test_durations else None,
        "premature_comprehensive_tests": (
            None
            if unknown_mutation and policy.track_premature_comprehensive
            else premature_comprehensive
        ),
        "duplicate_successful_commands": (
            None if unknown_mutation and policy.track_duplicate_success else duplicate_success
        ),
        "plans": plan_count,
        "reviews": review_count,
        "subagents": subagent_count,
        "worktrees": worktree_count,
        "context_events": context_event_count,
        "files_changed": None if unknown_mutation else len(changed_paths),
        "generated_files": None,
        "diff_lines": sum(diff_lines) if diff_lines else None,
        "retries": _metadata_number(agent_context, "retries", int),
        "timeouts": _metadata_number(agent_context, "timeouts", int),
        "infrastructure_errors": _metadata_number(
            agent_context, "infrastructure_errors", int
        ),
    }
    return MetricReport(
        metrics=metrics,
        command_records=tuple(command_records),
        classifier_schema=policy.classifier_schema,
        task_policy_digest=policy.task_policy_digest,
    )
