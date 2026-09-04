"""Reconstruct public-safe run history without opening trial artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_testing.Config import load_job, load_versions
from harness_testing.Run_Reports import (
    _timestamp,
    build_job_report,
    run_report_id,
    validate_run_report,
)
from harness_testing.Runs import RunManifest, verify_manifest_document

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^run-[0-9a-f]{20}$")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REVIEW_STATES = {"unreviewed", "reviewed", "quarantined"}
_LIMITATIONS = {
    "partial-run",
    "failed-run",
    "obsolete-methodology",
    "legacy-run-identity",
    "missing-provenance",
    "infrastructure-failure",
}
_LEGACY_FIELDS = {
    "label",
    "manifest_digest",
    "jobs_subdirectory",
    "expected_jobs",
    "review_state",
    "limitations",
}


@dataclass(frozen=True)
class LegacyRunMapping:
    label: str
    manifest_digest: str
    jobs_subdirectory: str
    expected_jobs: int
    review_state: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _ManifestSource:
    root: Path
    path: Path
    document: dict[str, object]


def _sha256(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _resolve_from_root(root: Path, candidate: Path) -> Path:
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def _read_object(file_path: Path, description: str) -> dict[str, Any]:
    try:
        document = json.loads(file_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {description}: {file_path}") from error
    if not isinstance(document, dict):
        raise ValueError(f"invalid {description}: expected an object at {file_path}")
    return document


def _load_legacy_mappings(root: Path, mapping_path: Path) -> tuple[LegacyRunMapping, ...]:
    path = _resolve_from_root(root, mapping_path)
    try:
        with path.open("rb") as mapping_file:
            document = tomllib.load(mapping_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"historical mapping is unreadable: {path}") from error
    if set(document) - {"legacy"}:
        raise ValueError("historical mapping contains unknown sections")
    raw_mappings = document.get("legacy", [])
    if not isinstance(raw_mappings, list):
        raise ValueError("historical mapping legacy entries must be an array")
    mappings: list[LegacyRunMapping] = []
    for raw in raw_mappings:
        if not isinstance(raw, dict) or set(raw) != _LEGACY_FIELDS:
            raise ValueError("historical mapping has missing or unknown fields")
        label = raw["label"]
        digest = raw["manifest_digest"]
        subdirectory = raw["jobs_subdirectory"]
        expected_jobs = raw["expected_jobs"]
        review_state = raw["review_state"]
        limitations = raw["limitations"]
        if not isinstance(label, str) or not _LABEL.fullmatch(label):
            raise ValueError("historical mapping label must be kebab-case")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError(f"historical mapping {label} has an invalid digest")
        if not isinstance(subdirectory, str):
            raise ValueError(f"historical mapping {label} has an invalid jobs directory")
        relative = Path(subdirectory)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"historical mapping {label} has an unsafe jobs directory")
        if type(expected_jobs) is not int or expected_jobs < 1:
            raise ValueError(f"historical mapping {label} has an invalid job count")
        if review_state not in _REVIEW_STATES:
            raise ValueError(f"historical mapping {label} has an invalid review state")
        if (
            not isinstance(limitations, list)
            or not all(isinstance(item, str) and item in _LIMITATIONS for item in limitations)
            or len(set(limitations)) != len(limitations)
        ):
            raise ValueError(f"historical mapping {label} has invalid limitations")
        mappings.append(
            LegacyRunMapping(
                label=label,
                manifest_digest=digest,
                jobs_subdirectory=subdirectory,
                expected_jobs=expected_jobs,
                review_state=review_state,
                limitations=tuple(limitations),
            )
        )
    identities = [(mapping.label, mapping.manifest_digest) for mapping in mappings]
    if len(set(identities)) != len(identities):
        raise ValueError("historical mapping contains duplicate legacy identities")
    return tuple(mappings)


def _manifest_sources(source_roots: tuple[Path, ...]) -> tuple[_ManifestSource, ...]:
    sources: list[_ManifestSource] = []
    for source_root in source_roots:
        for manifest_path in sorted((source_root / "runs" / "generated").glob(
            "*/Manifest.json"
        )):
            document = _read_object(manifest_path, "run manifest")
            digest = verify_manifest_document(document)
            if manifest_path.parent.name != digest.removeprefix("sha256:"):
                raise ValueError(
                    f"manifest directory does not match its digest: {manifest_path}"
                )
            sources.append(
                _ManifestSource(
                    root=source_root,
                    path=manifest_path,
                    document=document,
                )
            )
    return tuple(sources)


def _normalized_manifest(source: _ManifestSource) -> tuple[RunManifest, bool]:
    document = copy.deepcopy(source.document)
    missing_skill_evaluation = "skill_evaluation" not in document
    document.setdefault("skill_evaluation", None)
    try:
        manifest = RunManifest.from_document(document, source.path)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"historical manifest is unsupported: {source.path}") from error
    return manifest, missing_skill_evaluation


def _job_names(manifest: RunManifest) -> tuple[str, ...]:
    recorded_digests = manifest.provenance.get("harbor_config_digests")
    if not isinstance(recorded_digests, Mapping):
        raise ValueError(f"historical manifest has no Harbor config digests: {manifest.path}")
    names: list[str] = []
    for index, relative_path in enumerate(manifest.harbor_config_paths):
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe historical Harbor config path: {relative_path}")
        config_path = manifest.path.parent / relative
        try:
            contents = config_path.read_bytes()
        except OSError as error:
            raise ValueError(f"historical Harbor config is unreadable: {config_path}") from error
        if recorded_digests.get(relative_path) != _sha256(contents):
            raise ValueError(f"historical Harbor config digest mismatch: {relative_path}")
        job = load_job(config_path)
        cell = manifest.cells[index % len(manifest.cells)]
        task = manifest.task_ids[index // len(manifest.cells)]
        expected_suffix = f"{cell.label}-{task}"
        if job.job_name != expected_suffix and not job.job_name.endswith(
            f"-{expected_suffix}"
        ):
            raise ValueError(f"historical Harbor job identity mismatch: {relative_path}")
        names.append(job.job_name)
    if len(set(names)) != len(names):
        raise ValueError(f"historical manifest contains duplicate job names: {manifest.path}")
    return tuple(names)


def _read_result(result_path: Path) -> dict[str, object]:
    result = _read_object(result_path, "top-level Harbor result")
    for field in ("started_at", "updated_at", "finished_at"):
        value = result.get(field)
        if value is not None and _timestamp(value)[0] is None:
            raise ValueError(f"historical Harbor result has invalid {field}: {result_path}")
    return result


def _result_records(
    manifest: RunManifest,
    base_directory: Path,
) -> tuple[tuple[int, str, dict[str, object]], ...]:
    records: list[tuple[int, str, dict[str, object]]] = []
    for index, (relative_path, job_name) in enumerate(
        zip(manifest.harbor_config_paths, _job_names(manifest), strict=True)
    ):
        result_path = base_directory / job_name / "result.json"
        if result_path.is_file():
            records.append((index, relative_path, _read_result(result_path)))
    return tuple(records)


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _historical_report(
    root: Path,
    manifest: RunManifest,
    records: tuple[tuple[int, str, dict[str, object]], ...],
    *,
    run_id: str,
    source_kind: str,
    source_label: str | None,
    review_state: str,
    limitations: tuple[str, ...],
    missing_skill_evaluation: bool,
) -> dict[str, object]:
    unavailable_reason = "missing-provenance" if missing_skill_evaluation else None
    jobs = [
        build_job_report(
            manifest,
            index,
            relative_path,
            result,
            series_key_unavailable_reason=unavailable_reason,
        )
        for index, relative_path, result in records
    ]
    completed_jobs = sum(job["status"] == "completed" for job in jobs)
    failed_jobs = sum(job["status"] in {"failed", "incomplete"} for job in jobs)
    pending_jobs = len(manifest.harbor_config_paths) - completed_jobs - failed_jobs
    completed_trials = sum(int(job["completed_trials"]) for job in jobs)
    failed_trials = sum(
        int(job["errored_trials"]) + int(job["cancelled_trials"])
        for job in jobs
    )
    report_limitations = list(limitations)
    complete = (
        completed_jobs == len(manifest.harbor_config_paths)
        and completed_trials == manifest.session_count
        and failed_jobs == 0
        and failed_trials == 0
    )
    if not complete:
        _append_once(report_limitations, "partial-run")
        _append_once(report_limitations, "failed-run")
    if failed_trials:
        _append_once(report_limitations, "infrastructure-failure")
    if any(job["comparability"] == "diagnostic-only" for job in jobs):
        _append_once(report_limitations, "missing-provenance")
    current_schema = str(
        load_versions(root / "Versions.toml")["repository"]["schema_version"]
    )
    if manifest.schema_version != current_schema:
        review_state = "quarantined"
        _append_once(report_limitations, "obsolete-methodology")
    started = [str(job["started_at"]) for job in jobs if job["started_at"] is not None]
    if not started:
        raise ValueError(f"historical run has no valid start time: {manifest.path}")
    updated: list[str] = []
    for _, _, result in records:
        for field in ("updated_at", "finished_at", "started_at"):
            normalized, _ = _timestamp(result.get(field))
            if normalized is not None:
                updated.append(normalized)
    if not updated:
        raise ValueError(f"historical run has no valid update time: {manifest.path}")
    finished = [str(job["finished_at"]) for job in jobs if job["finished_at"] is not None]
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
        "run_id": run_id,
        "source": {"kind": source_kind, "label": source_label},
        "evidence": {
            "review_state": review_state,
            "limitations": report_limitations,
        },
        "profile": manifest.profile,
        "status": "completed" if complete else "failed",
        "started_at": min(started),
        "updated_at": max(updated),
        "finished_at": max(finished) if finished else max(updated),
        "expected_jobs": len(manifest.harbor_config_paths),
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
    errors = validate_run_report(root, report, published=True)
    if errors:
        raise ValueError("historical run report is invalid: " + "; ".join(errors))
    return report


def _write_report(output_directory: Path, report: dict[str, object]) -> Path:
    destination = output_directory / f"{report['run_id']}.json"
    contents = json.dumps(report, indent=2, sort_keys=True) + "\n"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(contents)
    os.replace(temporary, destination)
    return destination


def _identified_reports(
    root: Path,
    sources: tuple[_ManifestSource, ...],
    output_directory: Path,
) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    identities: dict[str, str] = {}
    for source in sources:
        provenance = source.document.get("provenance")
        run_id = provenance.get("run_id") if isinstance(provenance, Mapping) else None
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            continue
        manifest, missing_skill = _normalized_manifest(source)
        job_names = _job_names(manifest)
        if any(not name.startswith(f"{run_id}-") for name in job_names):
            raise ValueError(
                f"historical jobs do not match manifest run ID {run_id}: "
                f"{manifest.path}"
            )
        records = _result_records(
            manifest,
            source.root / "jobs" / "raw",
        )
        if not records:
            continue
        existing_digest = identities.get(run_id)
        if existing_digest is not None and existing_digest != manifest.digest:
            raise ValueError(f"multiple manifests claim historical run {run_id}")
        report = _historical_report(
            root,
            manifest,
            records,
            run_id=run_id,
            source_kind="identified-historical",
            source_label=None,
            review_state="unreviewed",
            limitations=(),
            missing_skill_evaluation=missing_skill,
        )
        if run_id in reports:
            previous = json.loads(reports[run_id].read_text())
            if previous.get("report_id") != report["report_id"]:
                raise ValueError(f"conflicting historical copies for run {run_id}")
            continue
        identities[run_id] = manifest.digest
        reports[run_id] = _write_report(output_directory, report)
    return reports


def _legacy_reports(
    root: Path,
    sources: tuple[_ManifestSource, ...],
    mappings: tuple[LegacyRunMapping, ...],
    output_directory: Path,
    reports: dict[str, Path],
) -> None:
    by_digest: dict[str, list[_ManifestSource]] = {}
    for source in sources:
        digest = str(source.document.get("digest", ""))
        by_digest.setdefault(digest, []).append(source)
    for mapping in mappings:
        candidates = by_digest.get(mapping.manifest_digest, [])
        if not candidates:
            raise ValueError(f"legacy manifest is unavailable: {mapping.manifest_digest}")
        matched: list[tuple[RunManifest, bool, tuple[tuple[int, str, dict[str, object]], ...]]] = []
        for source in candidates:
            manifest, missing_skill = _normalized_manifest(source)
            base = (
                source.root
                / "jobs"
                / "raw"
                / mapping.jobs_subdirectory
            ).resolve()
            raw_root = (source.root / "jobs" / "raw").resolve()
            try:
                base.relative_to(raw_root)
            except ValueError as error:
                raise ValueError(
                    f"legacy jobs directory escapes the source root: {mapping.label}"
                ) from error
            records = _result_records(manifest, base)
            if records:
                matched.append((manifest, missing_skill, records))
        if len(matched) != 1:
            raise ValueError(
                f"legacy mapping {mapping.label} matched {len(matched)} source roots"
            )
        manifest, missing_skill, records = matched[0]
        if len(records) != mapping.expected_jobs:
            raise ValueError(
                f"legacy mapping {mapping.label} expected {mapping.expected_jobs} jobs, "
                f"found {len(records)}"
            )
        run_id = "run-" + hashlib.sha256(
            f"{mapping.manifest_digest}\0{mapping.label}".encode()
        ).hexdigest()[:20]
        if run_id in reports:
            raise ValueError(f"duplicate historical run identity: {run_id}")
        report = _historical_report(
            root,
            manifest,
            records,
            run_id=run_id,
            source_kind="legacy-historical",
            source_label=mapping.label,
            review_state=mapping.review_state,
            limitations=mapping.limitations,
            missing_skill_evaluation=missing_skill,
        )
        reports[run_id] = _write_report(output_directory, report)


def backfill_run_reports(
    root: Path,
    source_roots: tuple[Path, ...],
    mapping_path: Path,
    output_directory: Path,
) -> tuple[Path, ...]:
    """Build deterministic v2 reports from manifests and top-level job summaries."""

    root = root.resolve()
    resolved_sources = tuple(_resolve_from_root(root, path) for path in source_roots)
    if not resolved_sources or len(set(resolved_sources)) != len(resolved_sources):
        raise ValueError("historical source roots must be present and unique")
    if any(not path.is_dir() for path in resolved_sources):
        raise ValueError("historical source root does not exist")
    output = _resolve_from_root(root, output_directory)
    if output != (root / "runs" / "history").resolve():
        raise ValueError("historical output must be the repository runs/history directory")
    output.mkdir(parents=True, exist_ok=True)
    mappings = _load_legacy_mappings(root, mapping_path)
    sources = _manifest_sources(resolved_sources)
    reports = _identified_reports(root, sources, output)
    _legacy_reports(root, sources, mappings, output, reports)
    return tuple(reports[run_id] for run_id in sorted(reports))
