"""Provider-neutral skill evaluation state and public-safe observations."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_SKILL_NAME = re.compile(
    r"^[a-z0-9][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)?$"
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CELL = re.compile(r"^[a-z0-9]+-A[0-3]-(?:baseline|candidate|calibration)$")
_TASK = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MODES = frozenset({"capability", "discovery"})
_PROVIDER_MARKERS = {"claude": "/", "codex": "$"}


def validate_skill_name(name: object) -> str:
    if not isinstance(name, str) or not _SKILL_NAME.fullmatch(name):
        raise ValueError("skill name must be canonical lowercase plugin:name syntax")
    return name


@dataclass(frozen=True)
class SkillEvaluation:
    mode: str
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in _MODES:
            raise ValueError("skill evaluation mode must be capability or discovery")
        validate_skill_name(self.name)

    def to_dict(self) -> dict[str, str]:
        return {"mode": self.mode, "name": self.name}

    @classmethod
    def from_document(cls, value: object) -> SkillEvaluation | None:
        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {"mode", "name"}:
            raise ValueError("manifest skill_evaluation must contain only mode and name")
        mode = value["mode"]
        name = value["name"]
        if not isinstance(mode, str) or not isinstance(name, str):
            raise ValueError("manifest skill_evaluation mode and name must be text")
        return cls(mode=mode, name=name)


def explicit_instruction(provider: str, skill_name: str, instruction: str) -> str:
    """Prefix an unchanged task with the provider's explicit skill marker."""

    name = validate_skill_name(skill_name)
    marker = _PROVIDER_MARKERS.get(provider)
    if marker is None:
        raise ValueError(f"unsupported skill invocation provider: {provider}")
    if not isinstance(instruction, str):
        raise ValueError("instruction must be text")
    return f"{marker}{name} {instruction}"


def _tool_calls(trajectory: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        calls = step.get("tool_calls")
        if not isinstance(calls, list):
            continue
        yield from (call for call in calls if isinstance(call, Mapping))


def _exact_skill_call(call: Mapping[str, object], name: str) -> bool:
    if call.get("function_name") not in {"Skill", "skill"}:
        return False
    arguments = call.get("arguments")
    return isinstance(arguments, Mapping) and any(
        arguments.get(field) == name for field in ("skill", "name", "skill_name")
    )


def _codex_pinned_skill_read(call: Mapping[str, object], name: str) -> bool:
    if call.get("function_name") not in {"exec", "shell", "read", "read_file"}:
        return False
    plugin, separator, skill = name.partition(":")
    if not separator:
        plugin = skill = name
    arguments = call.get("arguments")
    if not isinstance(arguments, Mapping):
        return False
    serialized = json.dumps(arguments, sort_keys=True)
    path = re.compile(
        r"/(?:harness-arm/codex/provider-home|tmp/codex-home)/plugins/cache/"
        rf"[^/\s\"']+/{re.escape(plugin)}/[^/\s\"']+/skills/"
        rf"{re.escape(skill)}/SKILL\.md(?:[\s\"']|$)"
    )
    return path.search(serialized) is not None


def observe_skill_invocation(
    provider: str,
    skill_name: str,
    trajectory: Mapping[str, object],
) -> bool:
    """Observe selection using only ATIF tool calls, never model text."""

    name = validate_skill_name(skill_name)
    if provider not in _PROVIDER_MARKERS:
        raise ValueError(f"unsupported skill observation provider: {provider}")
    calls = _tool_calls(trajectory)
    if provider == "claude":
        return any(
            call.get("function_name") == "Skill" and _exact_skill_call(call, name)
            for call in calls
        )
    return any(
        _exact_skill_call(call, name) or _codex_pinned_skill_read(call, name)
        for call in calls
    )


def _read_trajectory(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"skill evaluation trajectory is unreadable: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"skill evaluation trajectory is invalid: {path.name}")
    return value


def write_skill_evaluation_report(
    output: Path,
    *,
    manifest_digest: str,
    evaluation: SkillEvaluation,
    trials: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Write deterministic per-trial classifications without raw trajectory data."""

    if not _DIGEST.fullmatch(manifest_digest):
        raise ValueError("skill evaluation manifest digest is invalid")
    records: list[dict[str, object]] = []
    numerator = 0
    for trial in trials:
        provider = trial.get("provider")
        cell = trial.get("cell")
        task = trial.get("task")
        attempt = trial.get("attempt")
        trajectory_path = trial.get("trajectory")
        if (
            provider not in _PROVIDER_MARKERS
            or not isinstance(cell, str)
            or not _CELL.fullmatch(cell)
            or not isinstance(task, str)
            or not _TASK.fullmatch(task)
            or type(attempt) is not int
            or attempt < 1
            or not isinstance(trajectory_path, Path)
        ):
            raise ValueError("skill evaluation trial is invalid")
        observed = evaluation.mode == "capability" or observe_skill_invocation(
            provider,
            evaluation.name,
            _read_trajectory(trajectory_path),
        )
        if observed:
            numerator += 1
        records.append(
            {
                "provider": provider,
                "cell": cell,
                "task": task,
                "attempt": attempt,
                "invocation": (
                    "explicit"
                    if evaluation.mode == "capability"
                    else "implicit"
                    if observed
                    else "not-observed"
                ),
            }
        )
    denominator = len(records)
    if denominator == 0:
        raise ValueError("skill evaluation has no completed trials")
    report: dict[str, object] = {
        "schema_version": "1",
        "manifest_digest": manifest_digest,
        "skill_evaluation": evaluation.to_dict(),
        "trials": records,
        "aggregate": {
            "numerator": numerator,
            "denominator": denominator,
            "rate": numerator / denominator,
        },
    }
    contents = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if not output.is_file() or output.read_text() != contents:
        output.write_text(contents)
    return report
