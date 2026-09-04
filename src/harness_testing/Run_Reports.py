"""Build safe local run summaries and refresh the ignored dashboard output."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from harness_testing.Config import load_job
from harness_testing.Public_Safety import public_safety_errors

if TYPE_CHECKING:
    from harness_testing.Runs import RunCell, RunManifest

_REPORT_STATUSES = {"running", "completed", "failed"}


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def run_report_id(document: Mapping[str, object]) -> str:
    """Return the content identity of a public-safe run report."""

    unsigned = dict(document)
    unsigned.pop("report_id", None)
    payload = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _run_report_schema(root: Path) -> dict[str, object]:
    schema = _read_object(root / "policy" / "Run_Report.schema.json")
    if schema is None:
        raise ValueError("run report schema is unreadable")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"invalid run report schema: {error.message}") from error
    return schema


def _run_report_schema_errors(root: Path, document: object) -> list[str]:
    validator = Draft202012Validator(
        _run_report_schema(root),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    return [
        "run report schema: "
        + ("$." + ".".join(map(str, error.path)) if error.path else "$")
        + f": {error.message}"
        for error in errors
    ]


def validate_run_report(
    root: Path,
    document: object,
    *,
    published: bool = False,
) -> tuple[str, ...]:
    """Validate one local or publishable allowlisted run report."""

    errors = list(public_safety_errors(document))
    errors.extend(_run_report_schema_errors(root, document))
    if not isinstance(document, Mapping):
        return tuple(dict.fromkeys(errors))
    if published and document.get("schema_version") != "2":
        errors.append(
            f"run report schema version {document.get('schema_version')} is local-only; "
            "published reports require version 2"
        )
    if (
        document.get("schema_version") == "2"
        and document.get("report_id") != run_report_id(document)
    ):
        errors.append("run report identity does not match its content")
    return tuple(dict.fromkeys(errors))


def load_run_report(
    root: Path,
    path: Path,
    *,
    published: bool = False,
) -> dict[str, object]:
    """Load one schema-valid run report from disk."""

    try:
        document = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid run report: {error}") from error
    errors = validate_run_report(root, document, published=published)
    if errors:
        raise ValueError("invalid run report: " + "; ".join(errors))
    if not isinstance(document, dict):
        raise ValueError("invalid run report: expected a JSON object")
    return document


def _integer(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _number(value: object) -> int | float | None:
    return value if not isinstance(value, bool) and isinstance(value, int | float) else None


def _timestamp(value: object) -> tuple[str | None, datetime | None]:
    if not isinstance(value, str):
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    return parsed.isoformat().replace("+00:00", "Z"), parsed


def _score(stats: Mapping[str, object], name: str) -> float | None:
    evals = stats.get("evals")
    if not isinstance(evals, Mapping):
        return None
    values: list[float] = []
    for evaluation in evals.values():
        metrics = evaluation.get("metrics") if isinstance(evaluation, Mapping) else None
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            value = metric.get(name) if isinstance(metric, Mapping) else None
            if not isinstance(value, bool) and isinstance(value, int | float):
                values.append(float(value))
    return sum(values) / len(values) if values else None


def _content_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _task_identity(manifest: RunManifest, task: str) -> tuple[str, str]:
    task_digests = manifest.provenance.get("task_digests")
    if not isinstance(task_digests, Mapping):
        raise ValueError("run manifest has no task digests")
    matches = [
        (str(name).partition("/")[0], digest)
        for name, digest in task_digests.items()
        if str(name).partition("/")[2] == task
    ]
    if len(matches) != 1 or not isinstance(matches[0][1], str):
        raise ValueError(f"run manifest has no unique task digest for {task}")
    return matches[0][0], matches[0][1]


def _series_key(
    manifest: RunManifest,
    cell: RunCell,
    task_digest: str,
    agent: str,
    agent_version: str,
) -> str:
    adapter_digests = manifest.provenance.get("agent_adapter_digests")
    image_input_digests = manifest.provenance.get("image_input_digests")
    if not isinstance(adapter_digests, Mapping) or not isinstance(
        image_input_digests, Mapping
    ):
        raise ValueError("run manifest has incomplete series provenance")
    adapter_digest = adapter_digests.get(cell.provider)
    if not isinstance(adapter_digest, str):
        raise ValueError(f"run manifest has no adapter digest for {cell.provider}")
    return _content_digest(
        {
            "manifest_schema_version": manifest.schema_version,
            "provider": cell.provider,
            "agent": agent,
            "agent_version": agent_version,
            "model": cell.model,
            "effort": cell.effort,
            "arm": cell.arm,
            "role": cell.role,
            "skill_evaluation": (
                manifest.skill_evaluation.to_dict()
                if manifest.skill_evaluation is not None
                else None
            ),
            "task_digest": task_digest,
            "image_input_digests": dict(image_input_digests),
            "agent_adapter_digest": adapter_digest,
            "dataset_digest": manifest.provenance.get("deepswe_dataset_digest"),
        }
    )


def _job_status(
    result: Mapping[str, object] | None,
    *,
    expected_trials: int,
) -> tuple[str, dict[str, int]]:
    if result is None:
        return "pending", {
            "completed": 0,
            "errored": 0,
            "running": 0,
            "pending": expected_trials,
            "cancelled": 0,
        }
    stats = result.get("stats")
    if not isinstance(stats, Mapping):
        return "incomplete", {
            "completed": 0,
            "errored": 0,
            "running": 0,
            "pending": expected_trials,
            "cancelled": 0,
        }
    names = {
        "completed": "n_completed_trials",
        "errored": "n_errored_trials",
        "running": "n_running_trials",
        "pending": "n_pending_trials",
        "cancelled": "n_cancelled_trials",
    }
    raw_counts = {name: _integer(stats.get(field)) for name, field in names.items()}
    if any(value is None for value in raw_counts.values()):
        return "incomplete", {
            name: value if value is not None else 0 for name, value in raw_counts.items()
        }
    counts = {name: int(value) for name, value in raw_counts.items()}
    if counts["errored"] or counts["cancelled"]:
        return "failed", counts
    if counts["running"]:
        return "running", counts
    if (
        counts["completed"] == expected_trials
        and counts["pending"] == 0
        and sum(counts.values()) == expected_trials
    ):
        return "completed", counts
    return "incomplete", counts


def build_job_report(
    manifest: RunManifest,
    index: int,
    relative_path: str,
    result: Mapping[str, object] | None,
    *,
    series_key_unavailable_reason: str | None = None,
) -> dict[str, object]:
    """Build one allowlisted job summary from manifest and top-level result data."""

    cell: RunCell = manifest.cells[index % len(manifest.cells)]
    task = manifest.task_ids[index // len(manifest.cells)]
    job_config = load_job(manifest.path.parent / relative_path)
    job_name = job_config.job_name
    agent_config = job_config.agents[0]
    agent = agent_config.import_path or agent_config.name
    if not isinstance(agent, str) or not agent:
        raise ValueError(f"Harbor job has no agent identity: {relative_path}")
    agent_version = agent_config.kwargs.get("version")
    if not isinstance(agent_version, str) or not agent_version:
        raise ValueError(f"Harbor job has no agent version: {relative_path}")
    task_pack, task_digest = _task_identity(manifest, task)
    status, counts = _job_status(result, expected_trials=manifest.attempts)
    stats = result.get("stats") if isinstance(result, Mapping) else None
    stats = stats if isinstance(stats, Mapping) else {}
    started_at, started = _timestamp(result.get("started_at") if result else None)
    finished_at, finished = _timestamp(result.get("finished_at") if result else None)
    runtime = (
        max(0.0, (finished - started).total_seconds())
        if started is not None and finished is not None
        else None
    )
    unavailable_reason = series_key_unavailable_reason
    if agent_config.import_path is None:
        unavailable_reason = "missing-provenance"
    series_key = None
    if unavailable_reason is None:
        try:
            series_key = _series_key(
                manifest,
                cell,
                task_digest,
                agent,
                agent_version,
            )
        except ValueError:
            unavailable_reason = "missing-provenance"
    return {
        "name": job_name,
        "provider": cell.provider,
        "agent": agent,
        "agent_version": agent_version,
        "arm": cell.arm,
        "role": cell.role,
        "model": cell.model,
        "effort": cell.effort,
        "harness_commit": cell.harness_commit,
        "task": task,
        "task_pack": task_pack,
        "task_digest": task_digest,
        "comparability": (
            "comparable" if unavailable_reason is None else "diagnostic-only"
        ),
        "series_key": series_key,
        "series_key_unavailable_reason": unavailable_reason,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "runtime_seconds": runtime,
        "expected_trials": manifest.attempts,
        "completed_trials": counts["completed"],
        "errored_trials": counts["errored"],
        "cancelled_trials": counts["cancelled"],
        "dimensions": {
            "correctness": _score(stats, "reward"),
            "workflow": _score(stats, "workflow"),
            "efficiency_policy": _score(stats, "efficiency"),
        },
        "efficiency": {
            "prompt_tokens": _integer(stats.get("n_input_tokens")),
            "cached_tokens": _integer(stats.get("n_cache_tokens")),
            "completion_tokens": _integer(stats.get("n_output_tokens")),
            "api_equivalent_cost_usd": _number(stats.get("cost_usd")),
        },
    }


def _job_report(
    root: Path,
    manifest: RunManifest,
    index: int,
    relative_path: str,
) -> dict[str, object]:
    job_name = load_job(manifest.path.parent / relative_path).job_name
    result = _read_object(root / "jobs" / "raw" / job_name / "result.json")
    return build_job_report(manifest, index, relative_path, result)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_run_report(
    root: Path,
    manifest: RunManifest,
    status: str,
) -> Path:
    """Atomically record allowlisted progress for one approved manifest."""

    if status not in _REPORT_STATUSES:
        raise ValueError(f"unsupported local run status: {status}")
    root = root.resolve()
    report_path = manifest.path.parent / "Run_Report.json"
    previous = _read_object(report_path)
    jobs = [
        _job_report(root, manifest, index, relative_path)
        for index, relative_path in enumerate(manifest.harbor_config_paths)
    ]
    job_starts = [job["started_at"] for job in jobs if job["started_at"] is not None]
    updated_at = _now()
    started_at = (
        previous.get("started_at")
        if isinstance(previous, Mapping) and isinstance(previous.get("started_at"), str)
        else min(job_starts)
        if job_starts
        else updated_at
    )
    job_finishes = [job["finished_at"] for job in jobs if job["finished_at"] is not None]
    completed_jobs = sum(job["status"] == "completed" for job in jobs)
    failed_jobs = sum(job["status"] in {"failed", "incomplete"} for job in jobs)
    pending_jobs = sum(job["status"] in {"pending", "running"} for job in jobs)
    completed_trials = sum(int(job["completed_trials"]) for job in jobs)
    failed_trials = sum(
        int(job["errored_trials"]) + int(job["cancelled_trials"])
        for job in jobs
    )
    limitations: list[str] = []
    if completed_jobs != len(jobs) or completed_trials != manifest.session_count:
        limitations.append("partial-run")
    if status == "failed" or failed_jobs or failed_trials:
        limitations.append("failed-run")
    if failed_trials:
        limitations.append("infrastructure-failure")
    observed_costs = [
        cost
        for job in jobs
        if isinstance(job.get("efficiency"), Mapping)
        for cost in [job["efficiency"].get("api_equivalent_cost_usd")]
        if isinstance(cost, int | float) and not isinstance(cost, bool)
    ]
    report: dict[str, object] = {
        "schema_version": "2",
        "report_id": "",
        "manifest_schema_version": manifest.schema_version,
        "manifest_digest": manifest.digest,
        "run_id": manifest.provenance["run_id"],
        "source": {"kind": "current", "label": None},
        "evidence": {
            "review_state": "unreviewed",
            "limitations": limitations,
        },
        "profile": manifest.profile,
        "status": status,
        "started_at": started_at,
        "updated_at": updated_at,
        "finished_at": (
            max(job_finishes) if job_finishes else updated_at
        ) if status != "running" else None,
        "expected_jobs": len(jobs),
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "pending_jobs": pending_jobs,
        "expected_trials": manifest.session_count,
        "completed_trials": completed_trials,
        "failed_trials": failed_trials,
        "admission_estimate_usd": float(manifest.api_equivalent_cost_usd),
        "observed_api_equivalent_cost_usd": (
            sum(observed_costs) if observed_costs else None
        ),
        "jobs": jobs,
    }
    report["report_id"] = run_report_id(report)
    errors = validate_run_report(root, report)
    if errors:
        raise ValueError("local run report is invalid: " + "; ".join(errors))
    contents = json.dumps(report, indent=2, sort_keys=True) + "\n"
    temporary = report_path.with_name(".Run_Report.json.tmp")
    temporary.write_text(contents)
    os.replace(temporary, report_path)
    return report_path


def refresh_local_dashboard(
    root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> Path | None:
    """Rebuild the ignored dashboard once after a local run finishes."""

    root = root.resolve()
    if not (root / "dashboard" / "package.json").is_file():
        return None
    (
        root
        / "dashboard"
        / "src"
        / ".observablehq"
        / "cache"
        / "data"
        / "Public_Results.json"
    ).unlink(missing_ok=True)
    try:
        runner(
            ("npm", "--prefix", "dashboard", "run", "build"),
            cwd=root,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(
            "local run report was saved, but the dashboard build failed; "
            "install its locked dependencies and rerun "
            "`npm --prefix dashboard run build`"
        ) from error
    return root / "dashboard" / "dist" / "index.html"
