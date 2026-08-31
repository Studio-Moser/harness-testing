"""Shared deterministic criteria for Harness contract benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from pathlib import Path
from typing import Any

from harness_testing.Workflow_Criteria import protected_files_intact

_RESULT_KEYS = {
    "status",
    "route",
    "artifacts",
    "evidence",
    "telemetry",
    "shelby",
    "blockers",
}
_ROUTE_KEYS = {
    "requested",
    "actual_model",
    "effort",
    "provider",
    "executor",
    "resolution",
    "attempted",
    "fallback_reason",
}
_ARTIFACT_KEYS = {"files", "report"}
_EVIDENCE_KEYS = {"fixed_target", "checks", "outcome"}
_TELEMETRY_KEYS = {
    "attempts",
    "elapsed",
    "verification_failures",
    "token_or_quota_usage",
}
_SHELBY_KEYS = {"project_id", "run_id", "checkpoint_ids"}
_SEMANTIC_ROUTE_KEYS = {
    "requested",
    "actual_model",
    "effort",
    "provider",
    "executor",
    "resolution",
    "fallback_reason",
}
_FORBIDDEN_LIFECYCLE = (
    re.compile(r"(?:^|[;&|]\s*|\s)(?:git\s+(?:checkout|switch|branch|commit|push)|gh\s+pr)\b"),
    re.compile(r"(?:^|[;&|]\s*|\s)(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b"),
    re.compile(r"(?:^|[;&|]\s*|\s)(?:pytest|cargo\s+test|harbor\s+check)\b"),
    re.compile(r"(?:^|[;&|]\s*|\s)(?:pip|pip3|npm|pnpm|yarn)\s+install\b"),
    re.compile(r"(?:^|[;&|]\s*|\s)(?:export\s+)?PATH="),
)


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _optional_string(value: object) -> bool:
    return value is None or isinstance(value, str)


def _complete_result(result: object) -> bool:
    if not isinstance(result, dict) or set(result) != _RESULT_KEYS:
        return False
    route = result.get("route")
    artifacts = result.get("artifacts")
    evidence = result.get("evidence")
    telemetry = result.get("telemetry")
    shelby = result.get("shelby")
    blockers = result.get("blockers")
    if (
        not isinstance(route, dict)
        or set(route) != _ROUTE_KEYS
        or not isinstance(artifacts, dict)
        or set(artifacts) != _ARTIFACT_KEYS
        or not isinstance(evidence, dict)
        or set(evidence) != _EVIDENCE_KEYS
        or not isinstance(telemetry, dict)
        or set(telemetry) != _TELEMETRY_KEYS
        or not isinstance(shelby, dict)
        or set(shelby) != _SHELBY_KEYS
        or not _strings(blockers)
    ):
        return False
    if (
        result.get("status") not in {"accepted", "failed", "blocked", "abandoned"}
        or not isinstance(route.get("requested"), str)
        or not all(
            _optional_string(route.get(name))
            for name in (
                "actual_model",
                "effort",
                "provider",
                "executor",
                "resolution",
                "fallback_reason",
            )
        )
        or not _strings(route.get("attempted"))
        or not _strings(artifacts.get("files"))
        or not _optional_string(artifacts.get("report"))
        or not _optional_string(evidence.get("fixed_target"))
        or not _strings(evidence.get("checks"))
        or evidence.get("outcome") not in {"proven", "unproven"}
        or not isinstance(telemetry.get("attempts"), int)
        or telemetry["attempts"] < 0
        or not isinstance(telemetry.get("verification_failures"), int)
        or telemetry["verification_failures"] < 0
        or not _optional_string(shelby.get("project_id"))
        or not _optional_string(shelby.get("run_id"))
        or not _strings(shelby.get("checkpoint_ids"))
    ):
        return False
    if result["status"] == "accepted":
        return evidence["outcome"] == "proven" and not blockers
    if result["status"] == "blocked":
        return evidence["outcome"] == "unproven" and bool(blockers)
    return True


def _artifact_matches(path: Path, rule: object) -> bool:
    if not isinstance(rule, dict) or not path.is_file() or path.is_symlink():
        return False
    if set(rule) == {"text"}:
        return isinstance(rule["text"], str) and path.read_text() == rule["text"]
    if set(rule) == {"json"}:
        return _json(path) == rule["json"]
    if set(rule) == {"sha256"}:
        digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        return digest == rule["sha256"]
    if set(rule) == {"png"} and isinstance(rule["png"], dict):
        data = path.read_bytes()
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return False
        width, height = struct.unpack(">II", data[16:24])
        return rule["png"] == {"width": width, "height": height}
    return False


def _blocker_codes(blockers: list[str]) -> list[str]:
    return [blocker.partition(":")[0].strip() for blocker in blockers]


def _result_semantics_match(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    route = result["route"]
    expected_route = expected["route"]
    artifacts = result["artifacts"]
    expected_artifacts = expected["artifacts"]
    evidence = result["evidence"]
    expected_evidence = expected["evidence"]
    telemetry = result["telemetry"]
    expected_telemetry = expected["telemetry"]
    return (
        result["status"] == expected["status"]
        and all(
            route[key] == expected_route[key] for key in _SEMANTIC_ROUTE_KEYS
        )
        and len(artifacts["files"]) == len(set(artifacts["files"]))
        and set(artifacts["files"]) == set(expected_artifacts["files"])
        and artifacts["report"] == expected_artifacts["report"]
        and evidence["fixed_target"] == expected_evidence["fixed_target"]
        and evidence["outcome"] == expected_evidence["outcome"]
        and bool(evidence["checks"])
        and telemetry["attempts"] == expected_telemetry["attempts"]
        and telemetry["verification_failures"]
        == expected_telemetry["verification_failures"]
        and result["shelby"] == expected["shelby"]
        and _blocker_codes(result["blockers"])
        == _blocker_codes(expected["blockers"])
    )


def result_matches_contract(
    workspace: Path,
    expected_path: Path,
    protected_manifest: Path,
) -> bool:
    """Check the complete result, frozen inputs, and independently visible outputs."""

    expected = _json(expected_path)
    result = _json(workspace / "Harness_Result.json")
    if (
        not isinstance(expected, dict)
        or not _complete_result(result)
        or not _complete_result(expected.get("result"))
        or not protected_files_intact(workspace, protected_manifest)
    ):
        return False
    if not _result_semantics_match(result, expected["result"]):
        return False
    artifacts = expected.get("artifacts")
    if not isinstance(artifacts, dict):
        return False
    return all(
        _artifact_matches(
            Path(relative) if Path(relative).is_absolute() else workspace / relative,
            rule,
        )
        for relative, rule in artifacts.items()
        if isinstance(relative, str)
    ) and all(isinstance(relative, str) for relative in artifacts)


def _stub_evidence(expected_path: Path, events_path: Path) -> tuple[list[Any], list[Any]] | None:
    expected = _json(expected_path)
    if not isinstance(expected, dict) or not isinstance(expected.get("calls"), list):
        return None
    try:
        events = [
            json.loads(line)
            for line in events_path.read_text().splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return None
    if not all(
        isinstance(event, dict) and event.get("sequence") == sequence
        for sequence, event in enumerate(events, 1)
    ):
        return None
    return expected["calls"], events


def stub_calls_match(expected_path: Path, events_path: Path) -> bool:
    """Require every protected contract call without penalizing extra attempts."""

    evidence = _stub_evidence(expected_path, events_path)
    if evidence is None:
        return False
    calls, events = evidence
    if events and not any("expected_sequence" in event for event in events):
        cursor = 0
        for call in calls:
            while cursor < len(events) and not (
                events[cursor].get("matched") is True
                and events[cursor].get("action") == call.get("action")
                and events[cursor].get("payload") == call.get("payload")
            ):
                cursor += 1
            if cursor == len(events):
                return False
            cursor += 1
        return True
    for expected_sequence, call in enumerate(calls, 1):
        if not isinstance(call, dict) or not any(
            event.get("matched") is True
            and event.get("expected_sequence") == expected_sequence
            and event.get("action") == call.get("action")
            for event in events
        ):
            return False
    return True


def stub_calls_are_bounded(expected_path: Path, events_path: Path) -> bool:
    """Reject invalid, duplicate, or extra calls without requiring workflow completion."""

    evidence = _stub_evidence(expected_path, events_path)
    if evidence is None:
        return False
    calls, events = evidence
    if events and not any("expected_sequence" in event for event in events):
        remaining = set(range(len(calls)))
        for event in events:
            match = next(
                (
                    index
                    for index in remaining
                    if event.get("matched") is True
                    and event.get("action") == calls[index].get("action")
                    and event.get("payload") == calls[index].get("payload")
                ),
                None,
            )
            if match is None:
                return False
            remaining.remove(match)
        return True
    seen: set[int] = set()
    for event in events:
        expected_sequence = event.get("expected_sequence")
        if (
            event.get("matched") is not True
            or not isinstance(expected_sequence, int)
            or expected_sequence < 1
            or expected_sequence > len(calls)
            or expected_sequence in seen
            or event.get("action") != calls[expected_sequence - 1].get("action")
        ):
            return False
        seen.add(expected_sequence)
    return True


def no_unrequested_lifecycle() -> bool:
    """Reject testing, install, or repository lifecycle outside contract scope."""

    path = Path(
        os.environ.get("HARNESS_TEST_TRAJECTORY", "/logs/agent/trajectory.json")
    )
    trajectory = _json(path)
    if not isinstance(trajectory, dict):
        return False
    for step in trajectory.get("steps", []):
        if not isinstance(step, dict):
            continue
        for call in step.get("tool_calls") or []:
            if not isinstance(call, dict) or call.get("function_name") not in {
                "Bash",
                "shell",
            }:
                continue
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                continue
            command = arguments.get("command") or arguments.get("cmd")
            if isinstance(command, str) and any(
                pattern.search(command) for pattern in _FORBIDDEN_LIFECYCLE
            ):
                return False
    return True
