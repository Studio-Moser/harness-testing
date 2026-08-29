"""Immutable Harbor regrading and fail-closed public result construction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_key|access_token|refresh_token|auth_token|authorization|password|"
    r"secret|credential)(?:$|_)",
    re.IGNORECASE,
)
_PRIVATE_FIELDS = {
    "command_output",
    "env",
    "environment",
    "environment_variables",
    "extra",
    "prompt",
    "prompts",
    "reasoning",
    "reasoning_content",
    "tool_output",
    "trajectory",
    "trajectories",
}
_LOCAL_PATH = re.compile(r"(?:file://|/Users/|/home/|[A-Za-z]:\\Users\\)")
_SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|"
    r"secret)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}"
)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_REQUIRED_REGRADE_ARTIFACTS = ("/app", "/logs/agent/trajectory.json")

_RUN_FIELDS = (
    "id",
    "trial_id",
    "manifest_digest",
    "harness_testing_commit",
    "started_at",
    "finished_at",
    "finalized_at",
    "finalized",
    "release_decision",
)
_REVIEW_FIELDS = (
    "task_reviewed",
    "infrastructure_reviewed",
    "partial",
    "quarantined",
    "note",
)
_PROVIDER_FIELDS = (
    "name",
    "agent",
    "agent_version",
    "agent_contract",
    "model",
    "effort",
)
_TASK_FIELDS = ("id", "package", "pack", "digest")
_DATASET_FIELDS = ("id", "digest")
_PROVENANCE_FIELDS = (
    "environment_image_digest",
    "scorer_digest",
    "classifier_digest",
    "methodology_schema",
    "methodology_digest",
)
_DIMENSION_FIELDS = ("correctness", "workflow", "efficiency_policy")
_EFFICIENCY_FIELDS = (
    "agent_seconds",
    "verifier_seconds",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "cost_usd",
    "turns",
    "tool_calls",
    "commands",
    "direct_checks",
    "targeted_tests",
    "package_tests",
    "comprehensive_tests",
    "test_seconds",
    "premature_comprehensive_tests",
    "duplicate_successful_commands",
    "plans",
    "reviews",
    "subagents",
    "worktrees",
    "context_events",
    "files_changed",
    "generated_files",
    "diff_lines",
    "retries",
    "timeouts",
    "infrastructure_errors",
)


@dataclass(frozen=True)
class RegradeRecord:
    source_job_id: str
    source_job_path: Path
    source_job_digest: str
    regrade_job_path: Path
    command: tuple[str, ...]


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _path_payload(path: Path) -> bytes:
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}".encode()
    return path.read_bytes()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(f"{stat.S_IMODE(path.lstat().st_mode):o}".encode())
        digest.update(b"\0")
        digest.update(_path_payload(path))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _read_object(path: Path, description: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {description}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"invalid {description}: expected a JSON object")
    return document


def _validate_regrade_artifacts(source_job: Path) -> None:
    trials = sorted(
        child
        for child in source_job.iterdir()
        if child.is_dir()
        and (child / "config.json").is_file()
        and (child / "result.json").is_file()
    )
    if not trials:
        raise ValueError("source job has no recorded trials")
    for trial in trials:
        manifest_path = trial / "artifacts" / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"source trial has no readable artifact manifest: {trial}") from error
        if not isinstance(manifest, list):
            raise ValueError(f"source trial has an invalid artifact manifest: {trial}")
        entries = {
            str(item.get("source")): item
            for item in manifest
            if isinstance(item, dict)
        }
        for source in _REQUIRED_REGRADE_ARTIFACTS:
            entry = entries.get(source)
            if not isinstance(entry, dict) or entry.get("status") != "ok":
                raise ValueError(
                    f"source trial is missing required artifact {source}: {trial.name}"
                )
            destination = entry.get("destination")
            if not isinstance(destination, str):
                raise ValueError(
                    f"source trial has an invalid required artifact {source}: {trial.name}"
                )
            recorded = (trial / destination).resolve()
            try:
                recorded.relative_to(trial.resolve())
            except ValueError as error:
                raise ValueError(
                    f"source trial artifact escapes its record: {trial.name}"
                ) from error
            if not recorded.exists():
                raise ValueError(
                    f"source trial required artifact is absent on disk: {source}"
                )


def _new_job_path(root: Path, stdout: str) -> Path:
    clean = _ANSI.sub("", stdout)
    matches = re.findall(r"^New job directory:\s*(.+?)\s*$", clean, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("Harbor regrade did not report exactly one new job directory")
    reported = Path(matches[0])
    path = reported if reported.is_absolute() else root / reported
    path = path.resolve()
    try:
        path.relative_to((root / "jobs").resolve())
    except ValueError as error:
        raise ValueError("Harbor regrade job escaped the local jobs directory") from error
    if not all((path / name).is_file() for name in ("config.json", "result.json")):
        raise ValueError("Harbor regrade did not create a complete job directory")
    return path


def regrade_job(
    root: Path,
    source_job: Path,
    tasks_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> RegradeRecord:
    """Run Harbor's verifier-only regrade and retain immutable source provenance."""

    root = root.resolve()
    source_job = source_job.resolve()
    tasks_path = tasks_path.resolve()
    if not (source_job / "config.json").is_file():
        raise ValueError("source job is missing config.json")
    if not tasks_path.is_dir():
        raise ValueError("regrade tasks path does not exist")
    source_result = _read_object(source_job / "result.json", "source job result")
    try:
        source_job_id = str(UUID(str(source_result["id"])))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("source job has no valid identity") from error
    _validate_regrade_artifacts(source_job)
    before_digest = _tree_digest(source_job)
    command = (
        "harbor",
        "job",
        "regrade",
        str(source_job),
        "-p",
        str(tasks_path),
        "-e",
        "docker",
    )
    try:
        completed = runner(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        if _tree_digest(source_job) != before_digest:
            raise ValueError("source job changed during failed regrade") from error
        if isinstance(error, subprocess.CalledProcessError):
            raise ValueError(
                f"Harbor regrade failed with exit code {error.returncode}"
            ) from error
        raise ValueError(f"Harbor regrade could not start: {error}") from error
    after_digest = _tree_digest(source_job)
    if after_digest != before_digest:
        raise ValueError("source job changed during regrade")
    new_job = _new_job_path(root, completed.stdout or "")
    if new_job == source_job:
        raise ValueError("Harbor regrade attempted to overwrite the source job")
    receipt = {
        "schema_version": "1",
        "source_job_id": source_job_id,
        "source_job_path": str(source_job),
        "source_job_digest": before_digest,
        "regrade_job_path": str(new_job),
        "command": list(command),
    }
    receipt_path = new_job / "Regrade.json"
    if receipt_path.exists():
        raise ValueError("regrade provenance receipt already exists")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return RegradeRecord(
        source_job_id=source_job_id,
        source_job_path=source_job,
        source_job_digest=before_digest,
        regrade_job_path=new_job,
        command=command,
    )


def _sensitive_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(key)).strip("_").lower()
            child_path = f"{path}.{key}"
            if normalized in _PRIVATE_FIELDS or _SENSITIVE_KEY.search(normalized):
                errors.append(f"forbidden public field: {child_path}")
            errors.extend(_sensitive_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_sensitive_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (
        _LOCAL_PATH.search(value) or _SECRET_VALUE.search(value)
    ):
        errors.append(f"sensitive or local-only string: {path}")
    return errors


def _schema(root: Path) -> dict[str, object]:
    schema = _read_object(
        root / "policy" / "Public_Result.schema.json",
        "public result schema",
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"invalid public result schema: {error.message}") from error
    return schema


def compatibility_key(document: Mapping[str, object]) -> str:
    task = document["task"]
    dataset = document["dataset"]
    provenance = document["provenance"]
    provider = document["provider"]
    if not all(isinstance(value, Mapping) for value in (task, dataset, provenance, provider)):
        raise ValueError("public result has invalid compatibility inputs")
    inputs = {
        "task_digest": task["digest"],
        "dataset_digest": dataset["digest"],
        "scorer_digest": provenance["scorer_digest"],
        "classifier_digest": provenance["classifier_digest"],
        "environment_image_digest": provenance["environment_image_digest"],
        "provider_agent_contract": provider["agent_contract"],
        "methodology_schema": provenance["methodology_schema"],
    }
    return _sha256(_canonical_json(inputs))


def public_result_id(document: Mapping[str, object]) -> str:
    unsigned = dict(document)
    unsigned.pop("result_id", None)
    return _sha256(_canonical_json(unsigned))


def _schema_errors(root: Path, document: object) -> list[str]:
    validator = Draft202012Validator(_schema(root), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    return [
        "public result schema: "
        + ("$." + ".".join(map(str, error.path)) if error.path else "$")
        + f": {error.message}"
        for error in errors
    ]


def validate_public_result(root: Path, document: object) -> tuple[str, ...]:
    errors = _sensitive_errors(document)
    errors.extend(_schema_errors(root, document))
    if not isinstance(document, Mapping):
        return tuple(errors)
    run = document.get("run")
    review = document.get("review")
    if isinstance(run, Mapping) and run.get("finalized") is True:
        complete_review = (
            isinstance(review, Mapping)
            and review.get("task_reviewed") is True
            and review.get("infrastructure_reviewed") is True
            and review.get("partial") is False
            and review.get("quarantined") is False
        )
        if not complete_review:
            errors.append(
                "finalized result requires task and infrastructure review, "
                "complete coverage, and no quarantine"
            )
    try:
        expected_compatibility = compatibility_key(document)
    except (KeyError, TypeError, ValueError):
        expected_compatibility = None
    compatibility = document.get("compatibility")
    if isinstance(compatibility, Mapping) and expected_compatibility is not None:
        if compatibility.get("key") != expected_compatibility:
            errors.append("public result compatibility key does not match its inputs")
        mapping = compatibility.get("reviewed_mapping")
        if isinstance(mapping, Mapping) and mapping.get("compatible_with") == compatibility.get(
            "key"
        ):
            errors.append("reviewed compatibility mapping must join different keys")
    recorded_result_id = document.get("result_id")
    if (
        isinstance(recorded_result_id, str)
        and _DIGEST.fullmatch(recorded_result_id)
        and recorded_result_id != public_result_id(document)
    ):
        errors.append("public result identity does not match its content")
    return tuple(dict.fromkeys(errors))


def _select(source: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {field: source[field] for field in fields}


def _construct_allowlisted(document: Mapping[str, object]) -> dict[str, object]:
    arm = document["arm"]
    compatibility = document["compatibility"]
    infrastructure = document["infrastructure"]
    if not all(isinstance(value, Mapping) for value in (arm, compatibility, infrastructure)):
        raise ValueError("public result contains an invalid object")
    source_commits = arm["source_commits"]
    if not isinstance(source_commits, Mapping):
        raise ValueError("public result contains invalid arm provenance")
    mapping = compatibility["reviewed_mapping"]
    reviewed_mapping = (
        None
        if mapping is None
        else _select(
            mapping,
            ("compatible_with", "review_id", "reviewed_at", "rationale"),
        )
    )
    links = document["source_links"]
    if not isinstance(links, list):
        raise ValueError("public result contains invalid source links")
    return {
        "schema_version": document["schema_version"],
        "result_id": document["result_id"],
        "run": _select(document["run"], _RUN_FIELDS),
        "review": _select(document["review"], _REVIEW_FIELDS),
        "provider": _select(document["provider"], _PROVIDER_FIELDS),
        "arm": {
            "id": arm["id"],
            "role": arm["role"],
            "bundle_digest": arm["bundle_digest"],
            "source_commits": _select(
                source_commits, ("studio_harness", "superpowers")
            ),
        },
        "task": _select(document["task"], _TASK_FIELDS),
        "dataset": _select(document["dataset"], _DATASET_FIELDS),
        "provenance": _select(document["provenance"], _PROVENANCE_FIELDS),
        "compatibility": {
            "key": compatibility["key"],
            "reviewed_mapping": reviewed_mapping,
        },
        "dimensions": _select(document["dimensions"], _DIMENSION_FIELDS),
        "efficiency": _select(document["efficiency"], _EFFICIENCY_FIELDS),
        "infrastructure": {
            "status": infrastructure["status"],
            "detail": infrastructure["detail"],
        },
        "source_links": [
            _select(link, ("label", "url", "digest"))
            for link in links
            if isinstance(link, Mapping)
        ],
    }


def construct_public_result(root: Path, document: object) -> dict[str, object]:
    """Validate a reviewed result, then construct only its public allowlist."""

    errors = validate_public_result(root, document)
    if errors:
        raise ValueError("; ".join(errors))
    if not isinstance(document, Mapping):
        raise ValueError("public result must be an object")
    public = _construct_allowlisted(document)
    output_errors = validate_public_result(root, public)
    if output_errors:
        raise ValueError("constructed public result is invalid: " + "; ".join(output_errors))
    return public


def trend_series_key(document: Mapping[str, object]) -> str:
    compatibility = document["compatibility"]
    if not isinstance(compatibility, Mapping):
        raise ValueError("public result has no compatibility record")
    mapping = compatibility.get("reviewed_mapping")
    if isinstance(mapping, Mapping):
        return str(mapping["compatible_with"])
    return str(compatibility["key"])


def sanitize_public_result(
    root: Path, source_path: Path, output_path: Path
) -> dict[str, object]:
    """Write a schema-valid public result only inside local staging or results/."""

    root = root.resolve()
    output_path = output_path.resolve()
    try:
        relative = output_path.relative_to(root)
    except ValueError as error:
        raise ValueError("sanitized result output must stay inside the repository") from error
    if output_path.suffix != ".json":
        raise ValueError("sanitized result output must be a JSON file")
    is_public = relative.parts[:1] == ("results",)
    is_staging = relative.parts[:2] == ("runs", "generated")
    if not is_public and not is_staging:
        raise ValueError("sanitized result output must use results/ or runs/generated/")
    candidate = _read_object(source_path, "result candidate")
    public = construct_public_result(root, candidate)
    run = public["run"]
    if is_public and isinstance(run, Mapping) and run.get("finalized") is not True:
        raise ValueError("results/ accepts only finalized public results")
    contents = json.dumps(public, indent=2, sort_keys=True) + "\n"
    if output_path.exists():
        if output_path.read_text() != contents:
            raise ValueError("sanitized result output already exists with different content")
        return public
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(contents)
    return public
