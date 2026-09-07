"""Frozen, blinded final-patch review packets and evidence-only imports.

This module deliberately never dispatches a reviewer and never executes a
submitted reproduction command.  It only freezes inputs and imports retained
attestations after checking their bytes and declared conditions.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from harness_testing.Experiment_Reports import _price_usage, comparison_pricing
from harness_testing.Experiments import available_reference_reports, resolve_reference_reports
from harness_testing.Public_Safety import public_safety_errors
from harness_testing.Review_References import validate_review_references
from harness_testing.Run_Reports import load_run_report, run_report_id, validate_run_report
from harness_testing.Runs import verify_manifest_document

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PACKET_ID = re.compile(r"^review-[a-f0-9]{24}$")
_FINDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_STATUSES = {"completed", "blocked", "incomplete"}
_FINDING_STATUSES = {"confirmed", "unconfirmed", "dismissed"}
_SEVERITIES = {"P0", "P1", "P2", "P3"}
_USAGE_FIELDS = (
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def _sha256(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _read_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return value


def _validate_schema(root: Path, name: str, value: object) -> None:
    schema = _read_json(root / "policy" / name, f"{name} schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.path)) or "$"
        raise ValueError(f"{name}: {path}: {error.message}")


def _safe_relative(path: str, description: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in path or not candidate.parts:
        raise ValueError(f"unsafe {description}: {path}")
    return candidate


def _path_bytes(path: Path, description: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} is unavailable: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f"{description} is unreadable: {path}") from error


def _packet_path(plan_directory: Path, packet_id: str) -> Path:
    return plan_directory / "Packets" / f"{packet_id}.json"


def _review_result(
    *,
    status: str,
    files: list[Path],
    report: Path | None,
    fixed_target: str | None,
    checks: list[str],
    blockers: list[str] | None = None,
) -> dict[str, object]:
    blockers = blockers or []
    return {
        "status": status,
        "route": {
            "requested": "bulk",
            "actual_model": None,
            "effort": None,
            "provider": None,
            "executor": None,
            "resolution": None,
            "attempted": [],
            "fallback_reason": None,
        },
        "artifacts": {
            "files": [str(path) for path in files],
            "report": str(report) if report is not None else None,
        },
        "evidence": {
            "fixed_target": fixed_target,
            "checks": checks,
            "outcome": "proven" if status == "accepted" else "unproven",
        },
        "telemetry": {
            "attempts": 0,
            "elapsed": None,
            "verification_failures": len(blockers),
            "token_or_quota_usage": None,
        },
        "shelby": {"project_id": None, "run_id": None, "checkpoint_ids": []},
        "blockers": blockers,
    }


def _manifest_for_report(root: Path, report: Mapping[str, object]) -> dict[str, Any]:
    digest = report.get("manifest_digest")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("source report has no valid manifest digest")
    path = root / "runs" / "generated" / digest.removeprefix("sha256:") / "Manifest.json"
    manifest = _read_json(path, "source manifest")
    if verify_manifest_document(manifest) != digest:
        raise ValueError("source manifest digest does not match source report")
    if manifest.get("digest") != digest:
        raise ValueError("source manifest identity does not match source report")
    return manifest


def _task_instruction(
    root: Path, manifest: Mapping[str, object], task_id: str, task_root: Path | None = None
) -> tuple[Path, bytes]:
    experiment = (
        manifest.get("provenance", {}).get("experiment")
        if isinstance(manifest.get("provenance"), Mapping)
        else None
    )
    conditions = experiment.get("conditions") if isinstance(experiment, Mapping) else None
    variant = conditions.get("task_variant") if isinstance(conditions, Mapping) else None
    if variant == "comparison":
        from harness_testing.Materialize import _tree_digest

        if task_root is None or _tree_digest(task_root) != conditions["task_digests"][task_id]:
            raise ValueError("comparison task cache does not match the frozen task digest")
        path = task_root / "Comparison Instruction.md"
        return path, _path_bytes(path, "original task instruction")
    if variant == "deepswe":
        from harness_testing.Materialize import load_deepswe_dataset

        dataset = load_deepswe_dataset(root, task_ids=(task_id,))
        expected = (
            manifest.get("provenance", {}).get("deepswe_dataset_digest")
            if isinstance(manifest.get("provenance"), Mapping)
            else None
        )
        if not isinstance(expected, str) or dataset.digest != expected:
            raise ValueError("DeepSWE task cache does not match the source manifest")
        path = dataset.path / "tasks" / task_id / "instruction.md"
        return path, _path_bytes(path, "original DeepSWE task instruction")
    raise ValueError(f"unsupported source task variant for review: {variant!r}")


def _trial_job(manifest: Mapping[str, object], trial: Mapping[str, object]) -> Path:
    provenance = manifest.get("provenance")
    schedule = provenance.get("trial_schedule") if isinstance(provenance, Mapping) else None
    cells = manifest.get("cells")
    paths = manifest.get("harbor_config_paths")
    if not isinstance(schedule, list) or not isinstance(cells, list) or not isinstance(paths, list):
        raise ValueError("source manifest lacks an experiment trial schedule")
    task_id, contender_id, attempt = (
        trial.get("task_id"),
        trial.get("contender_id"),
        trial.get("attempt"),
    )
    matches: list[str] = []
    for slot, path in zip(schedule, paths, strict=True):
        if not isinstance(slot, Mapping) or not isinstance(path, str):
            raise ValueError("source manifest has malformed trial schedule")
        index = slot.get("cell_index")
        cell = cells[index] if type(index) is int and 0 <= index < len(cells) else None
        contender = cell.get("contender") if isinstance(cell, Mapping) else None
        if (
            isinstance(contender, Mapping)
            and contender.get("id") == contender_id
            and slot.get("task_id") == task_id
            and slot.get("attempt") == attempt
        ):
            matches.append(path)
    if len(matches) != 1:
        raise ValueError("source trial does not resolve to exactly one retained job")
    return _safe_relative(matches[0], "source Harbor config")


def _trial_inputs(
    root: Path, manifest: Mapping[str, object], trial: Mapping[str, object]
) -> dict[str, object]:
    config_relative = _trial_job(manifest, trial)
    config_path = (
        root
        / "runs"
        / "generated"
        / str(manifest["digest"]).removeprefix("sha256:")
        / config_relative
    )
    from harness_testing.Config import load_job

    config_digests = manifest["provenance"].get("harbor_config_digests")
    if not isinstance(config_digests, Mapping) or config_digests.get(
        config_relative.as_posix()
    ) != _sha256(_path_bytes(config_path, "source Harbor config")):
        raise ValueError("source Harbor config digest does not match the frozen manifest")
    job = load_job(config_path)
    job_directory = root / "jobs" / "raw" / job.job_name
    if job.job_name != Path(job.job_name).name or not job_directory.resolve().is_relative_to(
        root / "jobs/raw"
    ):
        raise ValueError("source job artifacts escape the local raw directory")
    attempt = trial.get("attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("source trial has invalid attempt")
    trial_directories = (
        sorted(
            path
            for path in (root / "jobs" / "raw" / job.job_name).iterdir()
            if path.is_dir() and (path / "config.json").is_file()
        )
        if (root / "jobs" / "raw" / job.job_name).is_dir()
        else []
    )
    if len(trial_directories) != 1 or job.n_attempts != 1:
        raise ValueError("source trial artifacts are missing or ambiguous")
    patch_path = trial_directories[0] / "artifacts" / "logs" / "artifacts" / "model.patch"
    task_id = trial.get("task_id")
    if not isinstance(task_id, str):
        raise ValueError("source trial has no task identity")
    task_roots = [
        (root / dataset.path / task_id).resolve()
        for dataset in job.datasets
        if getattr(dataset, "path", None) is not None
        and task_id in (dataset.task_names or [task_id])
    ]
    task_root = task_roots[0] if len(task_roots) == 1 else None
    if task_root is not None and not task_root.is_relative_to(root / ".cache"):
        raise ValueError("source task cache escapes the retained local cache")
    instruction_path, instruction = _task_instruction(root, manifest, task_id, task_root)
    conversation = job.agents[0].kwargs.get("conversation")
    base = (
        conversation.get("artifact_patch_base_commit")
        if isinstance(conversation, Mapping)
        else None
    )
    base_files = None
    if patch_path.is_file():
        patch = _path_bytes(patch_path, "final model patch")
    else:
        workspace = trial_directories[0] / "artifacts" / "workspace"
        if task_root is None:
            raise ValueError("source task cache does not resolve uniquely")
        source = task_root / "environment"
        if not source.is_dir() or not workspace.is_dir():
            raise ValueError("source trial has neither a final patch nor a retained workspace")
        patch, base_files = _comparison_patch(source, workspace)
        patch_path = workspace
        base = _sha256(_canonical(base_files))
    if not isinstance(base, str) or not base:
        raise ValueError("source job has no retained patch base")
    return {
        "patch_path": patch_path,
        "patch": patch,
        "instruction_path": instruction_path,
        "instruction": instruction,
        "base": base,
        "base_files": base_files,
    }


def _comparison_patch(source: Path, workspace: Path) -> tuple[bytes, dict]:
    """Make an applicable diff without host paths, runtime instructions or build output."""
    ignored = {".git", "node_modules", "dist", "target", ".codex", ".claude", ".agents"}
    startup = {"AGENTS.md", "CLAUDE.md"}
    base_files = {}
    if source.is_symlink() or workspace.is_symlink():
        raise ValueError("review workspace contains a symlink")
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        for label, origin in (("a", source), ("b", workspace)):
            destination = directory / label
            destination.mkdir()
            for path in sorted(origin.rglob("*")):
                relative = path.relative_to(origin)
                if ignored.intersection(relative.parts) or relative.name in startup:
                    continue
                if path.is_symlink():
                    raise ValueError("review workspace contains a symlink")
                if not path.is_file():
                    continue
                contents = _path_bytes(path, "review source file")
                copied = destination / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(contents)
                executable = bool(path.stat().st_mode & 0o111)
                copied.chmod(0o755 if executable else 0o644)
                if label == "a":
                    base_files[relative.as_posix()] = {
                        "content_base64": base64.b64encode(contents).decode("ascii"),
                        "executable": executable,
                    }
        result = subprocess.run(
            (
                "git",
                "diff",
                "--no-index",
                "--no-ext-diff",
                "--no-textconv",
                "--binary",
                "--no-prefix",
                "--",
                "a",
                "b",
            ),
            cwd=directory,
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        if result.returncode not in {0, 1}:
            raise ValueError("retained comparison workspace cannot reconstruct a final patch")
        return result.stdout, base_files


def _protocol(root: Path, protocol_path: Path) -> tuple[dict[str, Any], bytes, str]:
    contents = _path_bytes(protocol_path, "code review protocol")
    protocol = _read_json(protocol_path, "code review protocol")
    _validate_schema(root, "Code Review Protocol.schema.json", protocol)
    return protocol, contents, _sha256(contents)


def prepare_review(
    root: Path, report_path: Path, protocol_path: Path, references_path: Path | None = None
) -> dict[str, object]:
    """Freeze blinded, packet-local review inputs for completed v3 trials."""

    root = root.resolve()
    report_path = report_path.resolve()
    protocol_path = protocol_path.resolve()
    report_bytes = _path_bytes(report_path, "source report")
    raw_report = _read_json(report_path, "source report")
    experiment = raw_report.get("experiment")
    trials = experiment.get("trials") if isinstance(experiment, Mapping) else None
    if raw_report.get("schema_version") != "3" or not isinstance(trials, list):
        raise ValueError("review preparation requires a version-3 experiment report")
    selected = [
        trial
        for trial in trials
        if isinstance(trial, Mapping) and trial.get("status") == "completed"
    ]
    if not selected:
        raise ValueError("review preparation requires at least one completed experiment trial")
    if len(selected) != len(trials):
        raise ValueError("review preparation refuses reports with non-completed experiment trials")
    report = load_run_report(root, report_path)
    source_snapshot = (
        root / "runs" / "evidence" / (report["report_id"].removeprefix("sha256:") + ".json")
    )
    source_snapshot.parent.mkdir(parents=True, exist_ok=True)
    if source_snapshot.exists() and source_snapshot.read_bytes() != report_bytes:
        raise ValueError("source report snapshot conflicts with frozen source bytes")
    if not source_snapshot.exists():
        source_snapshot.write_bytes(report_bytes)
    protocol, protocol_bytes, protocol_id = _protocol(root, protocol_path)
    references = validate_review_references(
        root,
        report,
        protocol_id,
        _read_json(references_path, "review reference mapping") if references_path else {},
    )
    manifest = _manifest_for_report(root, report)
    frozen_conditions = manifest.get("provenance", {}).get("experiment", {}).get("conditions")
    if frozen_conditions != report["experiment"]["conditions"]:
        raise ValueError("source report conditions do not match the source manifest")
    image_digests = frozen_conditions.get("image_digests")
    if not isinstance(image_digests, Mapping) or not all(
        isinstance(name, str) and isinstance(digest, str) and _DIGEST.fullmatch(digest)
        for name, digest in image_digests.items()
    ):
        raise ValueError("source manifest has no valid pinned image evidence")
    prepared: list[dict[str, object]] = []
    for trial in selected:
        trial_id = trial.get("trial_id")
        if not isinstance(trial_id, str) or not _DIGEST.fullmatch(trial_id):
            raise ValueError("source trial has invalid identity")
        inputs = _trial_inputs(root, manifest, trial)
        packet_id = "review-" + secrets.token_hex(12)
        packet = {
            "packet_id": packet_id,
            "task": {
                "base": inputs["base"],
                "target_digest": _sha256(inputs["patch"]),
                "image_digests": {
                    name: digest
                    for name, digest in image_digests.items()
                    if name == f"{trial['task_id']}:agent"
                    or name == ("rust" if trial["task_id"].startswith("rust-") else "node")
                },
                "original_instruction": inputs["instruction"].decode("utf-8"),
            },
            "review_protocol": {
                "protocol_id": protocol_id,
                "reviewer": protocol["reviewer"],
                "instruction": protocol["instruction"],
                "categories": protocol["categories"],
                "time_budget_seconds": protocol["time_budget_seconds"],
                "hidden_grader_available": False,
            },
            "patch": inputs["patch"].decode("utf-8"),
        }
        if not packet["task"]["image_digests"]:
            raise ValueError("source task has no pinned agent image")
        if inputs.get("base_files") is not None:
            packet["task"]["base_files"] = inputs["base_files"]
        packet_bytes = json.dumps(packet, indent=2, sort_keys=True).encode() + b"\n"
        prepared.append(
            {
                "packet_id": packet_id,
                "packet": packet,
                "packet_bytes": packet_bytes,
                "trial_id": trial_id,
                "target_digest": _sha256(inputs["patch"]),
                "patch_path": str(inputs["patch_path"]),
                "patch_digest": _sha256(inputs["patch"]),
                "instruction_path": str(inputs["instruction_path"]),
                "instruction_digest": _sha256(inputs["instruction"]),
                "base": inputs["base"],
            }
        )
    secrets.SystemRandom().shuffle(prepared)
    plan_unsigned = {
        "schema_version": "1",
        "source": {
            "report_path": str(report_path),
            "report_id": report["report_id"],
            "report_digest": _sha256(report_bytes),
            "manifest_digest": report["manifest_digest"],
        },
        "protocol": {
            "protocol_id": protocol_id,
            "protocol_digest": _sha256(protocol_bytes),
            "path": str(protocol_path),
            "time_budget_seconds": protocol["time_budget_seconds"],
            "categories": protocol["categories"],
        },
        "conditions": protocol["reviewer"],
        "pricing_digest": _price_usage(root, [])[1],
        "reference_revisions": references,
        "packets": [
            {key: value for key, value in item.items() if key not in {"packet", "packet_bytes"}}
            | {"packet_digest": _sha256(item["packet_bytes"])}
            for item in prepared
        ],
    }
    plan_id = _sha256(_canonical(plan_unsigned))
    plan = {"plan_id": plan_id, **plan_unsigned}
    plan_directory = root / "runs" / "reviews" / plan_id.removeprefix("sha256:")
    packet_paths = [_packet_path(plan_directory, str(item["packet_id"])) for item in prepared]
    plan_path = plan_directory / "Plan.json"
    if plan_directory.exists():
        existing = _read_json(plan_path, "review plan") if plan_path.is_file() else None
        if existing != plan:
            raise ValueError("review plan identity conflicts with existing local evidence")
    else:
        (plan_directory / "Packets").mkdir(parents=True)
        for item, path in zip(prepared, packet_paths, strict=True):
            path.write_bytes(item["packet_bytes"])
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        (plan_directory / "Source Report.json").write_bytes(report_bytes)
    return _review_result(
        status="accepted",
        files=[plan_path, *packet_paths],
        report=None,
        fixed_target=plan_id,
        checks=[
            "source-report",
            "source-manifest",
            "original-instruction",
            "final-patch",
            "protocol",
            "packet-bytes",
        ],
    )


def _verify_plan(root: Path, plan_path: Path) -> tuple[dict[str, Any], Path]:
    plan_path = plan_path.resolve()
    plan = _read_json(plan_path, "review plan")
    plan_id = plan.get("plan_id")
    unsigned = dict(plan)
    unsigned.pop("plan_id", None)
    if not isinstance(plan_id, str) or plan_id != _sha256(_canonical(unsigned)):
        raise ValueError("review plan identity does not match its content")
    directory = plan_path.parent.resolve()
    expected_root = (root / "runs" / "reviews").resolve()
    if not directory.is_relative_to(expected_root):
        raise ValueError("review plan must stay in runs/reviews")
    return plan, directory


def _verify_frozen_inputs(
    root: Path, plan: Mapping[str, object], directory: Path
) -> tuple[dict[str, object], Path]:
    source = plan.get("source")
    protocol = plan.get("protocol")
    packets = plan.get("packets")
    if (
        not isinstance(source, Mapping)
        or not isinstance(protocol, Mapping)
        or not isinstance(packets, list)
    ):
        raise ValueError("review plan has incomplete frozen evidence")
    report_path = Path(str(source.get("report_path", "")))
    report_bytes = _path_bytes(directory / "Source Report.json", "frozen source report")
    if source.get("report_digest") != _sha256(report_bytes):
        raise ValueError("source report changed after review preparation")
    report = _read_json(directory / "Source Report.json", "frozen source report")
    errors = validate_run_report(root, report)
    if errors:
        raise ValueError("frozen source report is invalid: " + "; ".join(errors))
    if report.get("report_id") != source.get("report_id"):
        raise ValueError("source report identity changed after review preparation")
    protocol_path = Path(str(protocol.get("path", "")))
    protocol_bytes = _path_bytes(protocol_path, "code review protocol")
    if protocol.get("protocol_digest") != _sha256(protocol_bytes) or protocol.get(
        "protocol_id"
    ) != _sha256(protocol_bytes):
        raise ValueError("code review protocol changed after review preparation")
    manifest = _manifest_for_report(root, report)
    report_trials = (
        report.get("experiment", {}).get("trials")
        if isinstance(report.get("experiment"), Mapping)
        else None
    )
    if not isinstance(report_trials, list):
        raise ValueError("source report has no experiment trials")
    by_id = {trial.get("trial_id"): trial for trial in report_trials if isinstance(trial, Mapping)}
    for item in packets:
        if not isinstance(item, Mapping):
            raise ValueError("review plan packet is invalid")
        packet_id, trial_id = item.get("packet_id"), item.get("trial_id")
        if (
            not isinstance(packet_id, str)
            or not _PACKET_ID.fullmatch(packet_id)
            or trial_id not in by_id
        ):
            raise ValueError("review plan packet mapping is invalid")
        packet_path = _packet_path(directory, packet_id)
        if item.get("packet_digest") != _sha256(_path_bytes(packet_path, "review packet")):
            raise ValueError("review packet changed after review preparation")
        inputs = _trial_inputs(root, manifest, by_id[trial_id])
        expected = {
            "patch_digest": _sha256(inputs["patch"]),
            "instruction_digest": _sha256(inputs["instruction"]),
            "base": inputs["base"],
        }
        if any(item.get(key) != value for key, value in expected.items()):
            raise ValueError("review target changed after review preparation")
    return report, report_path


def _evidence_file(
    results_directory: Path, declared: object, description: str
) -> tuple[Path, bytes, str]:
    if not isinstance(declared, Mapping) or set(declared) != {"path", "digest"}:
        raise ValueError(f"{description} must name one retained evidence file and digest")
    path = declared.get("path")
    digest = declared.get("digest")
    if not isinstance(path, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError(f"{description} is invalid")
    evidence = (results_directory / _safe_relative(path, description)).resolve()
    if not evidence.is_relative_to(results_directory.resolve()):
        raise ValueError(f"unsafe {description}")
    contents = _path_bytes(evidence, description)
    if _sha256(contents) != digest:
        raise ValueError(f"{description} digest does not match its bytes")
    return evidence, contents, digest


def _public_finding(
    finding: Mapping[str, object],
    *,
    results_directory: Path,
    evidence_directory: Path,
    packet_id: str,
    reviewer_sessions: set[object],
) -> dict[str, object]:
    required = {"id", "severity", "category", "title", "file", "line", "status", "confirmation"}
    if set(finding) != required:
        raise ValueError("review finding has missing or unknown fields")
    status = finding["status"]
    if status not in _FINDING_STATUSES or finding["severity"] not in _SEVERITIES:
        raise ValueError("review finding has unsupported status or severity")
    if (
        not all(
            isinstance(finding[name], str) and finding[name]
            for name in ("id", "category", "title", "file")
        )
        or type(finding["line"]) is not int
        or finding["line"] < 1
    ):
        raise ValueError("review finding has invalid public fields")
    if not _FINDING_ID.fullmatch(str(finding["id"])):
        raise ValueError("review finding ID is unsafe")
    _safe_relative(str(finding["file"]), "finding file")
    if status == "unconfirmed":
        if finding["confirmation"] is not None:
            raise ValueError("unconfirmed findings may not carry a confirmation")
        return {
            key: finding[key]
            for key in ("id", "severity", "category", "title", "file", "line", "status")
        } | {"evidence_digest": None}
    if status == "dismissed":
        confirmation = finding["confirmation"]
        if not isinstance(confirmation, Mapping) or set(confirmation) != {"evidence"}:
            raise ValueError("dismissed finding requires retained evidence")
        _, contents, digest = _evidence_file(
            results_directory, confirmation.get("evidence"), "dismissal evidence"
        )
        (evidence_directory / f"{packet_id}-{finding['id']}.dismissed.evidence").write_bytes(
            contents
        )
        return {
            key: finding[key]
            for key in ("id", "severity", "category", "title", "file", "line", "status")
        } | {"evidence_digest": digest}
    confirmation = finding["confirmation"]
    if not isinstance(confirmation, Mapping) or set(confirmation) != {
        "session_id",
        "procedure",
        "expected",
        "observed",
        "evidence",
    }:
        raise ValueError("confirmed finding has incomplete confirmation")
    session = confirmation.get("session_id")
    if not isinstance(session, str) or not session or session in reviewer_sessions:
        raise ValueError("confirmed finding requires a distinct confirming session")
    if not all(
        isinstance(confirmation.get(name), str) and confirmation[name].strip()
        for name in ("procedure", "expected", "observed")
    ):
        raise ValueError("confirmed finding requires reproduction procedure and observed result")
    path, contents, digest = _evidence_file(
        results_directory, confirmation.get("evidence"), "confirmation evidence"
    )
    destination = evidence_directory / f"{packet_id}-{finding['id']}.evidence"
    destination.write_bytes(contents)
    return {
        key: finding[key]
        for key in ("id", "severity", "category", "title", "file", "line", "status")
    } | {"evidence_digest": digest}


def _internal_review(
    value: object,
    *,
    results_directory: Path,
    evidence_directory: Path,
    packet_id: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or "status" not in value:
        raise ValueError("internal review is invalid")
    if value.get("status") == "unknown" and set(value) == {"status"}:
        return {
            "status": "unknown",
            "found": None,
            "fixed": None,
            "unresolved": None,
            "evidence_digest": None,
        }
    required = {"status", "found", "fixed", "unresolved", "evidence"}
    if value.get("status") != "recorded" or set(value) != required:
        raise ValueError("recorded internal review requires counts and evidence")
    if not all(
        type(value.get(name)) is int and value[name] >= 0
        for name in ("found", "fixed", "unresolved")
    ):
        raise ValueError("internal review counts are invalid")
    if value["fixed"] + value["unresolved"] > value["found"]:
        raise ValueError("internal review counts exceed findings")
    _, contents, digest = _evidence_file(
        results_directory, value.get("evidence"), "internal review evidence"
    )
    (evidence_directory / f"{packet_id}-internal.evidence").write_bytes(contents)
    return {key: value[key] for key in ("status", "found", "fixed", "unresolved")} | {
        "evidence_digest": digest
    }


def _review_usage(result: Mapping, conditions: Mapping) -> tuple[list[dict], bool]:
    usage_complete = result.get("usage_complete")
    usage = result.get("model_usage")
    if type(usage_complete) is not bool or not isinstance(usage, list):
        raise ValueError("review result has invalid usage evidence")
    if usage_complete and not usage:
        raise ValueError("complete review usage must include model measurements")
    expected_provider = {"codex": "openai", "claude": "anthropic"}.get(
        conditions["provider"], conditions["provider"]
    )
    if any(
        not isinstance(row, Mapping)
        or set(row) != set(_USAGE_FIELDS)
        or row.get("provider") != expected_provider
        or row.get("model") != conditions["model"]
        or any(
            not (row.get(field) is None and not usage_complete)
            and (type(row.get(field)) is not int or row[field] < 0)
            for field in _USAGE_FIELDS[2:]
        )
        or not all(isinstance(row.get(field), str) and row[field] for field in _USAGE_FIELDS[:2])
        for row in usage
    ):
        raise ValueError("review result model usage must cover the complete supplied tree")
    return [dict(row) for row in usage], usage_complete


def _review_summary(
    root: Path,
    packet: Mapping[str, object],
    result: Mapping[str, object],
    results_directory: Path,
    evidence_directory: Path,
    reviewer_sessions: set[object],
    time_budget_seconds: int,
) -> dict[str, object]:
    if result.get("status") not in _STATUSES:
        raise ValueError("review result has invalid status")
    usage, usage_complete = _review_usage(result, result["conditions"])
    duration = result.get("duration_seconds")
    if duration is not None and (
        type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0
    ):
        raise ValueError("review result duration is invalid")
    if result.get("status") == "completed" and duration is None:
        raise ValueError("completed review requires a known duration")
    if result.get("status") == "completed" and duration > time_budget_seconds:
        raise ValueError("review result exceeds the frozen time budget")
    session = result.get("session_id")
    if (
        not isinstance(session, str)
        or not session
        or result.get("fresh_session") is not True
        or result.get("no_tested_harness") is not True
    ):
        raise ValueError("review result requires a fresh isolated session identity")
    findings = result.get("findings")
    if not isinstance(findings, list):
        raise ValueError("review result findings are invalid")
    if len({finding.get("id") for finding in findings if isinstance(finding, Mapping)}) != len(
        findings
    ):
        raise ValueError("review result has duplicate finding IDs")
    public_findings = [
        _public_finding(
            finding,
            results_directory=results_directory,
            evidence_directory=evidence_directory,
            packet_id=str(packet["packet_id"]),
            reviewer_sessions=reviewer_sessions,
        )
        for finding in findings
        if isinstance(finding, Mapping)
    ]
    if len(public_findings) != len(findings):
        raise ValueError("review result finding is invalid")
    required_sessions = {
        finding["confirmation"]["session_id"]
        for finding in findings
        if finding["status"] == "confirmed"
    }
    ledgers = result.get("confirmation_usage", [])
    seen = set()
    for ledger in ledgers:
        session_id = ledger["session_id"]
        if (
            session_id not in required_sessions
            or session_id in seen
            or session_id in reviewer_sessions
            or ledger["conditions"] != result["conditions"]
            or ledger["target_digest"] != packet["target_digest"]
        ):
            raise ValueError("confirmation usage does not match the independent frozen review")
        seen.add(session_id)
        additional, complete = _review_usage(ledger, result["conditions"])
        usage.extend(additional)
        usage_complete = usage_complete and complete
        elapsed = ledger["duration_seconds"]
        if elapsed is not None and (
            type(elapsed) not in {int, float}
            or not math.isfinite(elapsed)
            or elapsed < 0
            or elapsed > time_budget_seconds
        ):
            raise ValueError("confirmation duration is outside the frozen budget")
        duration = duration + elapsed if duration is not None and elapsed is not None else None
    if seen != required_sessions:
        usage_complete = False
        duration = None
    cost, pricing_digest = _price_usage(root, usage)
    return {
        "protocol_id": packet["protocol_id"],
        "status": result["status"],
        "target_digest": packet["target_digest"],
        "findings": public_findings,
        "cost_usd": cost if usage_complete else None,
        "pricing_digest": pricing_digest,
        "duration_seconds": float(duration) if duration is not None else None,
        "usage_complete": usage_complete,
        "model_usage": [dict(row) for row in usage],
        "internal_review": _internal_review(
            result.get("internal_review"),
            results_directory=results_directory,
            evidence_directory=evidence_directory,
            packet_id=str(packet["packet_id"]),
        ),
    }


def _attach_comparison(root: Path, report: dict[str, object]) -> None:
    experiment = report.get("experiment")
    if not isinstance(experiment, dict):
        raise ValueError("reviewed report has no experiment")
    from harness_testing.Comparisons import build_comparison

    request = {
        key: copy.deepcopy(experiment[key])
        for key in (
            "request_id",
            "label",
            "purpose",
            "conditions",
            "contenders",
            "baseline_result_ids",
            "predecessor_result_ids",
            "first_version",
            "change",
        )
    }
    references = (
        resolve_reference_reports(request, available_reference_reports(root))
        if request["baseline_result_ids"] or request["predecessor_result_ids"]
        else []
    )
    policy = _read_json(root / "policy" / "Comparison Policy.json", "comparison policy")
    policy["pricing"] = comparison_pricing(root)
    report["report_id"] = request["request_id"]
    experiment["comparison"] = build_comparison(request, [report, *references], policy)
    for pair in experiment["comparison"].get("pairs", []):
        if isinstance(pair, dict):
            for key in ("left_report_id", "right_report_id"):
                if pair.get(key) == request["request_id"]:
                    pair[key] = None


def record_review(root: Path, plan_path: Path, results_path: Path) -> dict[str, object]:
    """Import a complete same-protocol result set without running its evidence."""

    root = root.resolve()
    plan, directory = _verify_plan(root, plan_path)
    source_report, source_path = _verify_frozen_inputs(root, plan, directory)
    references = validate_review_references(
        root,
        source_report,
        plan["protocol"]["protocol_id"],
        plan.get("reference_revisions", {}),
    )
    if plan.get("pricing_digest") != _price_usage(root, [])[1]:
        raise ValueError("review pricing changed after preparation; restore the frozen rates")
    results_path = results_path.resolve()
    results_bytes = _path_bytes(results_path, "review results")
    results = _read_json(results_path, "review results")
    _validate_schema(root, "Code Review Results.schema.json", results)
    if results.get("plan_id") != plan.get("plan_id") or results.get("protocol_id") != plan.get(
        "protocol", {}
    ).get("protocol_id"):
        raise ValueError("review results do not match the frozen plan and protocol")
    if results.get("conditions") != plan.get("conditions"):
        raise ValueError("review results do not match the required reviewer conditions")
    packets = plan.get("packets")
    submitted = results.get("packets")
    if not isinstance(packets, list) or not isinstance(submitted, list):
        raise ValueError("review plan or results has invalid packets")
    planned = {item.get("packet_id"): item for item in packets if isinstance(item, Mapping)}
    returned = {item.get("packet_id"): item for item in submitted if isinstance(item, Mapping)}
    if (
        len(planned) != len(packets)
        or len(returned) != len(submitted)
        or set(planned) != set(returned)
    ):
        raise ValueError("review results must cover every frozen packet exactly once")
    sessions = [item.get("session_id") for item in submitted if isinstance(item, Mapping)]
    if len(set(sessions)) != len(sessions):
        raise ValueError("review packets must use distinct fresh sessions")
    confirming_sessions = set()
    for item in submitted:
        packet_sessions = {
            finding["confirmation"]["session_id"]
            for finding in item["findings"]
            if finding["status"] == "confirmed"
            and isinstance(finding["confirmation"], Mapping)
            and isinstance(finding["confirmation"].get("session_id"), str)
        }
        if confirming_sessions.intersection(packet_sessions):
            raise ValueError("confirmation sessions must not review multiple packets")
        confirming_sessions.update(packet_sessions)
    with tempfile.TemporaryDirectory(dir=directory, prefix=".record-") as scratch:
        evidence_directory = Path(scratch)
        summaries = {}
        for packet_id, packet in planned.items():
            if returned[packet_id].get("target_digest") != packet.get("target_digest"):
                raise ValueError("review result does not match the frozen packet target")
            if returned[packet_id].get("conditions") != plan.get("conditions"):
                raise ValueError("review packet does not match the required reviewer conditions")
            findings = returned[packet_id].get("findings")
            if not isinstance(findings, list) or any(
                not isinstance(finding, Mapping)
                or finding.get("category") not in plan["protocol"]["categories"]
                for finding in findings
            ):
                raise ValueError("review finding category is not in the frozen protocol")
            complete_packet = dict(packet) | {"protocol_id": plan["protocol"]["protocol_id"]}
            summaries[packet["trial_id"]] = _review_summary(
                root,
                complete_packet,
                returned[packet_id],
                results_path.parent,
                evidence_directory,
                set(sessions),
                plan["protocol"]["time_budget_seconds"],
            )
        revised = copy.deepcopy(source_report)
        trials = revised["experiment"]["trials"]
        for trial in trials:
            if isinstance(trial, dict) and trial.get("trial_id") in summaries:
                trial["code_review"] = summaries[trial["trial_id"]]
        costs = [summary["cost_usd"] for summary in summaries.values()]
        revised["experiment"]["code_review"] = {
            "plan_id": plan["plan_id"],
            "protocol_id": plan["protocol"]["protocol_id"],
            "source_report_id": source_report["report_id"],
            "results_digest": _sha256(results_bytes),
            "evaluation_cost_usd": sum(costs)
            if costs and all(cost is not None for cost in costs)
            else None,
        }
        revised["experiment"]["supersedes_report_id"] = source_report["report_id"]
        imported_path = directory / "Import.json"
        imported = _read_json(imported_path, "retained import") if imported_path.exists() else None
        if imported and imported.get("results_digest") != _sha256(results_bytes):
            raise ValueError("imported review results conflict with retained private evidence")
        revised["updated_at"] = (
            imported["imported_at"]
            if imported
            else datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
        for key in ("baseline_result_ids", "predecessor_result_ids"):
            revised["experiment"][key] = [
                references.get(identity, identity) for identity in revised["experiment"][key]
            ]
        _attach_comparison(root, revised)
        revised["report_id"] = run_report_id(revised)
        if imported and imported.get("report_id") != revised["report_id"]:
            raise ValueError("repeated import conflicts with the retained report revision")
        safety = public_safety_errors(revised)
        validation = validate_run_report(root, revised)
        if safety or validation:
            raise ValueError(
                "reviewed report is not public-safe: "
                + "; ".join(dict.fromkeys((*safety, *validation)))
            )
        retained_results = directory / "Imported Results.json"
        if retained_results.exists() and retained_results.read_bytes() != results_bytes:
            raise ValueError("imported review results conflict with retained private evidence")
        if not retained_results.exists():
            retained_results.write_bytes(results_bytes)
        if not imported_path.exists():
            imported_path.write_text(
                json.dumps(
                    {
                        "results_digest": _sha256(results_bytes),
                        "report_id": revised["report_id"],
                        "imported_at": revised["updated_at"],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        final_evidence = directory / "Evidence"
        final_evidence.mkdir(exist_ok=True)
        for staged in evidence_directory.iterdir():
            destination = final_evidence / staged.name
            if destination.exists() and destination.read_bytes() != staged.read_bytes():
                raise ValueError("retained review evidence conflicts with the imported bytes")
            if not destination.exists():
                shutil.move(str(staged), destination)
    contents = json.dumps(revised, indent=2, sort_keys=True) + "\n"
    evidence_path = (
        root / "runs" / "evidence" / (revised["report_id"].removeprefix("sha256:") + ".json")
    )
    source_snapshot = (
        root / "runs" / "evidence" / (source_report["report_id"].removeprefix("sha256:") + ".json")
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if evidence_path.exists() and evidence_path.read_text() != contents:
        raise ValueError("reviewed report revision conflicts with retained evidence")
    if not source_snapshot.exists():
        source_snapshot.write_bytes(_path_bytes(directory / "Source Report.json", "source report"))
    evidence_path.write_text(contents)
    if (
        source_path.name == "Run_Report.json"
        and source_path.is_relative_to(root / "runs" / "generated")
        and source_path.read_bytes()
        == _path_bytes(directory / "Source Report.json", "source report")
    ):
        temporary = source_path.with_name(".Run_Report.review.tmp")
        temporary.write_text(contents)
        os.replace(temporary, source_path)
    return _review_result(
        status="accepted",
        files=[Path(plan_path), retained_results, evidence_path],
        report=evidence_path,
        fixed_target=str(plan["plan_id"]),
        checks=[
            "source-report",
            "protocol",
            "packet-bytes",
            "patch-and-instruction",
            "reviewer-conditions",
            "sessions",
            "evidence-digests",
            "public-safety",
        ],
    )
