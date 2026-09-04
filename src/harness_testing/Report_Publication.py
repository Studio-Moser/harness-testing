"""Validate the fixed destination for public-safe run reports."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from harness_testing.Run_Reports import load_run_report

_REPOSITORY = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$")
_WORKFLOW = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TARGET_FIELDS = {"repository", "data_branch", "workflow", "code_ref"}


@dataclass(frozen=True)
class PublicationTarget:
    repository: str
    data_branch: str
    workflow: str
    code_ref: str


@dataclass(frozen=True)
class PublicationReceipt:
    report_id: str
    repository: str
    branch: str
    commit: str


class _PublicationCommandError(Exception):
    def __init__(self, stage: str, *, non_fast_forward: bool = False):
        super().__init__(stage)
        self.stage = stage
        self.non_fast_forward = non_fast_forward


def load_publication_target(root: Path) -> PublicationTarget:
    """Load and fail closed on the repository's tracked publication policy."""

    path = root / "policy" / "Dashboard_Publication.toml"
    try:
        with path.open("rb") as policy_file:
            document = tomllib.load(policy_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"publication policy is unreadable: {error}") from error
    if set(document) != {"public_reports"}:
        raise ValueError("publication policy must contain only [public_reports]")
    values = document.get("public_reports")
    if not isinstance(values, dict) or set(values) != _TARGET_FIELDS:
        raise ValueError("publication policy has missing or unknown target fields")
    if not all(isinstance(values[field], str) for field in _TARGET_FIELDS):
        raise ValueError("publication policy target fields must be strings")
    target = PublicationTarget(**values)
    if not _REPOSITORY.fullmatch(target.repository):
        raise ValueError("publication policy repository must be OWNER/REPO")
    if (
        not _BRANCH.fullmatch(target.data_branch)
        or ".." in target.data_branch
        or "//" in target.data_branch
        or target.data_branch.endswith(".lock")
    ):
        raise ValueError("publication policy data branch is invalid")
    if not _WORKFLOW.fullmatch(target.workflow):
        raise ValueError("publication policy workflow must be a workflow filename")
    if target.code_ref != "main":
        raise ValueError("publication policy code ref must be main")
    return target


def publication_manifest_record(target: PublicationTarget) -> dict[str, str]:
    """Return the exact destination included in content-addressed run manifests."""

    return {
        "mode": "public",
        "repository": target.repository,
        "data_branch": target.data_branch,
        "workflow": target.workflow,
        "code_ref": target.code_ref,
    }


def _receipt_path(report_path: Path) -> Path:
    return report_path.with_name(f"{report_path.stem}.Publication.json")


def _read_json_object(file_path: Path) -> dict[str, object] | None:
    try:
        document = json.loads(file_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _receipt_matches(
    report_path: Path,
    report_id: object,
    target: PublicationTarget,
) -> bool:
    if not isinstance(report_id, str) or not _DIGEST.fullmatch(report_id):
        return False
    receipt = _read_json_object(_receipt_path(report_path))
    return receipt is not None and receipt == {
        "schema_version": "1",
        "report_id": report_id,
        "repository": target.repository,
        "branch": target.data_branch,
        "commit": receipt.get("commit"),
    } and isinstance(receipt.get("commit"), str) and bool(
        re.fullmatch(r"[0-9a-f]{40}", receipt["commit"])
    )


def pending_run_reports(root: Path) -> tuple[Path, ...]:
    """Return validated-report candidates without a matching publication receipt."""

    root = root.resolve()
    target = load_publication_target(root)
    candidates = tuple((root / "runs" / "generated").glob("*/Run_Report.json")) + tuple(
        path
        for path in (root / "runs" / "history").glob("*.json")
        if not path.name.endswith(".Publication.json")
    )
    pending: list[Path] = []
    for report_path in sorted(set(candidates)):
        try:
            report = load_run_report(root, report_path, published=True)
        except ValueError:
            pending.append(report_path)
            continue
        report_id = report.get("report_id")
        if not _receipt_matches(report_path, report_id, target):
            pending.append(report_path)
    return tuple(pending)


def _run(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    command: tuple[str, ...],
    *,
    cwd: Path,
    stage: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise _PublicationCommandError(stage) from error
    except subprocess.CalledProcessError as error:
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        lower = stderr.lower()
        conflict = "non-fast-forward" in lower or (
            "rejected" in lower and "fetch first" in lower
        )
        raise _PublicationCommandError(
            stage,
            non_fast_forward=conflict,
        ) from error


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("run report has no updated_at timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("run report has an invalid updated_at timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validated_reports(
    root: Path,
    report_paths: tuple[Path, ...],
) -> tuple[tuple[Path, dict[str, object]], ...]:
    validated: list[tuple[Path, dict[str, object]]] = []
    run_ids: set[str] = set()
    for report_path in report_paths:
        resolved = report_path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise ValueError("run report to publish must stay inside the repository") from error
        is_live = (
            len(relative.parts) == 4
            and relative.parts[:2] == ("runs", "generated")
            and relative.name == "Run_Report.json"
        )
        is_history = (
            len(relative.parts) == 3
            and relative.parts[:2] == ("runs", "history")
            and relative.suffix == ".json"
            and not relative.name.endswith(".Publication.json")
        )
        if not is_live and not is_history:
            raise ValueError("run report to publish must use the local report outbox")
        report = load_run_report(root, resolved, published=True)
        run_id = report["run_id"]
        if not isinstance(run_id, str) or run_id in run_ids:
            raise ValueError("run report batch contains a duplicate or invalid run ID")
        run_ids.add(run_id)
        validated.append((resolved, report))
    return tuple(sorted(validated, key=lambda item: str(item[1]["run_id"])))


def _apply_reports(
    root: Path,
    checkout: Path,
    reports: tuple[tuple[Path, dict[str, object]], ...],
) -> int:
    reports_directory = checkout / "reports"
    reports_directory.mkdir(exist_ok=True)
    changed = 0
    for source_path, incoming in reports:
        run_id = str(incoming["run_id"])
        destination = reports_directory / f"{run_id}.json"
        if destination.is_file():
            published = load_run_report(root, destination, published=True)
            if published.get("run_id") != run_id:
                raise ValueError(f"published report has the wrong run identity: {run_id}")
            incoming_time = _timestamp(incoming.get("updated_at"))
            published_time = _timestamp(published.get("updated_at"))
            if incoming_time < published_time:
                raise ValueError(f"run report is older than published report: {run_id}")
            if incoming_time == published_time:
                if incoming.get("report_id") != published.get("report_id"):
                    raise ValueError(
                        f"run report conflicts with published report at the same time: {run_id}"
                    )
                continue
        temporary = destination.with_suffix(".json.tmp")
        shutil.copyfile(source_path, temporary)
        os.replace(temporary, destination)
        changed += 1
    return changed


def _publish_once(
    root: Path,
    reports: tuple[tuple[Path, dict[str, object]], ...],
    target: PublicationTarget,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    with tempfile.TemporaryDirectory(prefix="harness-report-publication-") as temporary:
        checkout = Path(temporary) / "repository"
        _run(
            runner,
            (
                "gh",
                "repo",
                "clone",
                target.repository,
                str(checkout),
                "--",
                "--branch",
                target.data_branch,
                "--single-branch",
                "--depth",
                "1",
            ),
            cwd=root,
            stage="clone data branch",
        )
        changed = _apply_reports(root, checkout, reports)
        if changed:
            _run(
                runner,
                ("git", "-C", str(checkout), "add", "reports"),
                cwd=root,
                stage="stage reports",
            )
            _run(
                runner,
                (
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Studio Moser Harness Testing",
                    "-c",
                    "user.email=harness-testing@users.noreply.github.com",
                    "commit",
                    "-m",
                    f"data: publish {changed} run report(s)",
                ),
                cwd=root,
                stage="commit reports",
            )
            _run(
                runner,
                (
                    "git",
                    "-C",
                    str(checkout),
                    "push",
                    "origin",
                    target.data_branch,
                ),
                cwd=root,
                stage="push reports",
            )
        commit = _run(
            runner,
            ("git", "-C", str(checkout), "rev-parse", "HEAD"),
            cwd=root,
            stage="read data commit",
        ).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("published data branch returned an invalid commit")
        return commit


def _write_receipt(
    report_path: Path,
    report_id: str,
    target: PublicationTarget,
    commit: str,
) -> PublicationReceipt:
    receipt = PublicationReceipt(
        report_id=report_id,
        repository=target.repository,
        branch=target.data_branch,
        commit=commit,
    )
    document = {
        "schema_version": "1",
        "report_id": receipt.report_id,
        "repository": receipt.repository,
        "branch": receipt.branch,
        "commit": receipt.commit,
    }
    destination = _receipt_path(report_path)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)
    return receipt


def publish_run_reports(
    root: Path,
    report_paths: tuple[Path, ...],
    target: PublicationTarget,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[PublicationReceipt, ...]:
    """Publish one validated report batch without switching the caller's worktree."""

    root = root.resolve()
    if target != load_publication_target(root):
        raise ValueError("publication target does not match the tracked policy")
    if len(set(path.resolve() for path in report_paths)) != len(report_paths):
        raise ValueError("run report batch contains duplicate paths")
    reports = _validated_reports(root, report_paths)
    if not reports:
        return ()
    try:
        _run(
            runner,
            ("gh", "auth", "status", "--hostname", "github.com"),
            cwd=root,
            stage="verify GitHub authentication",
        )
        try:
            commit = _publish_once(root, reports, target, runner)
        except _PublicationCommandError as error:
            if error.stage != "push reports" or not error.non_fast_forward:
                raise
            commit = _publish_once(root, reports, target, runner)
        _run(
            runner,
            (
                "gh",
                "workflow",
                "run",
                target.workflow,
                "--repo",
                target.repository,
                "--ref",
                target.code_ref,
            ),
            cwd=root,
            stage="dispatch Pages workflow",
        )
    except _PublicationCommandError as error:
        raise ValueError(f"could not publish run reports during {error.stage}") from error
    return tuple(
        _write_receipt(
            report_path,
            str(report["report_id"]),
            target,
            commit,
        )
        for report_path, report in reports
    )


def sync_pending_reports(
    root: Path,
    target: PublicationTarget,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[PublicationReceipt, ...]:
    """Publish every pending local report in one data commit and dispatch."""

    return publish_run_reports(
        root,
        pending_run_reports(root),
        target,
        runner=runner,
    )
