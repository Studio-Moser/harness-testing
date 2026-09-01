"""Shared deterministic criteria for Harness contract benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from harness_testing.Harness_Result import harness_result_schema_errors
from harness_testing.Workflow_Criteria import protected_files_intact

_SEMANTIC_ROUTE_KEYS = (
    "requested",
    "actual_model",
    "effort",
    "provider",
    "executor",
    "resolution",
    "fallback_reason",
)
_MAX_DIAGNOSTICS = 12
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


def _attempts_match(actual: list[str], expected: list[str]) -> bool:
    return Counter(item.strip() for item in actual) == Counter(
        item.strip() for item in expected
    )


def _evidence_matches(checks: list[str], requirements: object) -> bool:
    if (
        not isinstance(requirements, list)
        or not requirements
        or not all(
            isinstance(requirement, str) and requirement.strip()
            for requirement in requirements
        )
    ):
        return False
    available = set(range(len(checks)))
    for requirement in requirements:
        match = next(
            (
                index
                for index in available
                if checks[index].strip().casefold().startswith(
                    requirement.strip().casefold()
                )
            ),
            None,
        )
        if match is None:
            return False
        available.remove(match)
    return True


def _result_semantic_diagnostics(
    result: dict[str, Any], expected: dict[str, Any], evidence_requirements: object
) -> list[str]:
    route = result["route"]
    expected_route = expected["route"]
    artifacts = result["artifacts"]
    expected_artifacts = expected["artifacts"]
    evidence = result["evidence"]
    expected_evidence = expected["evidence"]
    telemetry = result["telemetry"]
    expected_telemetry = expected["telemetry"]
    diagnostics: list[str] = []
    if result["status"] != expected["status"]:
        diagnostics.append("result-semantics:/status:mismatch")
    for key in _SEMANTIC_ROUTE_KEYS:
        if route[key] != expected_route[key]:
            diagnostics.append(f"result-semantics:/route/{key}:mismatch")
    if not _attempts_match(route["attempted"], expected_route["attempted"]):
        diagnostics.append("result-semantics:/route/attempted:mismatch")
    if len(artifacts["files"]) != len(set(artifacts["files"])):
        diagnostics.append("result-semantics:/artifacts/files:duplicate")
    if set(artifacts["files"]) != set(expected_artifacts["files"]):
        diagnostics.append("result-semantics:/artifacts/files:mismatch")
    if artifacts["report"] != expected_artifacts["report"]:
        diagnostics.append("result-semantics:/artifacts/report:mismatch")
    if evidence["fixed_target"] != expected_evidence["fixed_target"]:
        diagnostics.append("result-semantics:/evidence/fixed_target:mismatch")
    if not _evidence_matches(evidence["checks"], evidence_requirements):
        diagnostics.append("result-semantics:/evidence/checks:missing-prefix")
    if evidence["outcome"] != expected_evidence["outcome"]:
        diagnostics.append("result-semantics:/evidence/outcome:mismatch")
    if telemetry["attempts"] != expected_telemetry["attempts"]:
        diagnostics.append("result-semantics:/telemetry/attempts:mismatch")
    if telemetry["verification_failures"] != expected_telemetry["verification_failures"]:
        diagnostics.append("result-semantics:/telemetry/verification_failures:mismatch")
    if result["shelby"] != expected["shelby"]:
        diagnostics.append("result-semantics:/shelby:mismatch")
    if _blocker_codes(result["blockers"]) != _blocker_codes(expected["blockers"]):
        diagnostics.append("result-semantics:/blockers:mismatch")
    return diagnostics


def _artifact_path(relative: str) -> str:
    return relative if relative.startswith("/") else f"/{relative}"


def result_contract_diagnostics(
    workspace: Path,
    expected_path: Path,
    protected_manifest: Path,
) -> tuple[str, ...]:
    """Return bounded local reasons a contract result does not match."""

    result_path = workspace / "Harness_Result.json"
    try:
        result = json.loads(result_path.read_text())
    except FileNotFoundError:
        return ("result-json:/Harness_Result.json:missing",)
    except (OSError, json.JSONDecodeError):
        return ("result-json:/Harness_Result.json:malformed",)

    result_schema_errors = harness_result_schema_errors(result)
    diagnostics = [
        f"result-schema:{path}:{code}"
        for path, code in result_schema_errors
    ]
    expected = _json(expected_path)
    expected_result = expected.get("result") if isinstance(expected, dict) else None
    expected_schema_errors = harness_result_schema_errors(expected_result)
    expected_artifacts = expected.get("artifacts") if isinstance(expected, dict) else None
    protected_intact = protected_files_intact(workspace, protected_manifest)
    if (
        not isinstance(expected, dict)
        or expected_schema_errors
        or not isinstance(expected_artifacts, dict)
        or not all(isinstance(relative, str) for relative in expected_artifacts)
        or not protected_intact
    ):
        diagnostics.append("protected-state:/:mismatch")

    if not result_schema_errors and not expected_schema_errors and isinstance(expected, dict):
        diagnostics.extend(
            _result_semantic_diagnostics(
                result, expected_result, expected.get("evidence_requirements")
            )
        )

    if isinstance(expected_artifacts, dict):
        for relative, rule in expected_artifacts.items():
            if not isinstance(relative, str):
                continue
            path = Path(relative) if Path(relative).is_absolute() else workspace / relative
            if not _artifact_matches(path, rule):
                diagnostics.append(f"artifact:{_artifact_path(relative)}:mismatch")
    return tuple(diagnostics[:_MAX_DIAGNOSTICS])


def result_matches_contract(
    workspace: Path,
    expected_path: Path,
    protected_manifest: Path,
) -> bool:
    """Check the complete result, frozen inputs, and independently visible outputs."""

    diagnostics = result_contract_diagnostics(
        workspace, expected_path, protected_manifest
    )
    for diagnostic in diagnostics:
        print(f"harness-contract: {diagnostic}")
    return not diagnostics


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
