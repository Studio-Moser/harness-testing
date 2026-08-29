"""Deterministic repository policy validation."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from harbor.models.task.config import NetworkMode, TaskConfig, VerifierEnvironmentMode

from harness_testing.Config import load_job, load_task, load_trajectory, load_versions

_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_key|access_token|auth_token|authorization|password|secret|credential)(?:$|_)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationFailure:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _failure(path: Path, message: str) -> ValidationFailure:
    return ValidationFailure(path=path, message=message)


def _fixture_digest(environment_directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in environment_directory.rglob("*") if item.is_file()):
        relative = path.relative_to(environment_directory).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _validate_benchmark_task_assets(
    task_path: Path, task: TaskConfig
) -> list[ValidationFailure]:
    if "verification_envelope" not in task.metadata:
        return []
    task_root = task_path.parent
    required_files = (
        "instruction.md",
        "environment/Dockerfile",
        "environment/package.json",
        "environment/package-lock.json",
        "solution/solve.sh",
        "tests/Dockerfile",
        "tests/test.sh",
        "tests/criteria.py",
        "tests/Protected_Files.json",
    )
    failures = [
        _failure(task_root / relative, "required benchmark task asset is missing")
        for relative in required_files
        if not (task_root / relative).is_file()
    ]
    for dimension in ("reward", "workflow", "efficiency"):
        directory = task_root / "tests" / dimension
        if not directory.is_dir() or not any(directory.glob("*.py")):
            failures.append(
                _failure(directory, f"RewardKit {dimension} criterion is required")
            )
    if failures:
        return failures

    test_script = (task_root / "tests" / "test.sh").read_text()
    if re.search(r"\b(?:uvx|pip\s+install|npm\s+install)\b", test_script):
        failures.append(
            _failure(
                task_root / "tests" / "test.sh",
                "verifier runtime must not install or download dependencies",
            )
        )

    environment_directory = task_root / "environment"
    for path in environment_directory.rglob("*"):
        if path.is_symlink():
            failures.append(_failure(path, "frozen fixture must not contain symlinks"))
    expected_fixture_digest = str(task.metadata.get("fixture_digest", ""))
    actual_fixture_digest = _fixture_digest(environment_directory)
    if expected_fixture_digest != actual_fixture_digest:
        failures.append(
            _failure(
                task_path,
                "fixture digest mismatch: "
                f"recorded {expected_fixture_digest!r}, actual {actual_fixture_digest}",
            )
        )

    manifest_path = task_root / "tests" / "Protected_Files.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        protected_files = manifest["files"]
        if not isinstance(protected_files, dict) or not protected_files:
            raise ValueError("files must be a non-empty object")
        for relative, expected in protected_files.items():
            protected_path = environment_directory / relative
            if (
                Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not protected_path.is_file()
                or protected_path.is_symlink()
            ):
                failures.append(
                    _failure(manifest_path, f"invalid protected fixture path: {relative}")
                )
                continue
            actual = f"sha256:{hashlib.sha256(protected_path.read_bytes()).hexdigest()}"
            if expected != actual:
                failures.append(
                    _failure(
                        manifest_path,
                        f"protected digest mismatch for {relative}: {expected!r} != {actual}",
                    )
                )
        mutable_files = manifest.get("mutable_files", {})
        if not isinstance(mutable_files, dict):
            raise ValueError("mutable_files must be an object")
        for relative, rule in mutable_files.items():
            mutable_path = environment_directory / relative
            if (
                relative in protected_files
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not mutable_path.is_file()
                or mutable_path.is_symlink()
                or not isinstance(rule, dict)
            ):
                failures.append(
                    _failure(manifest_path, f"invalid mutable fixture path: {relative}")
                )
                continue
            expected = rule.get("baseline_sha256")
            actual = f"sha256:{hashlib.sha256(mutable_path.read_bytes()).hexdigest()}"
            if expected != actual:
                failures.append(
                    _failure(
                        manifest_path,
                        f"mutable baseline digest mismatch for {relative}: "
                        f"{expected!r} != {actual}",
                    )
                )
            replacements = rule.get("replacements")
            if not isinstance(replacements, list) or not replacements:
                failures.append(
                    _failure(manifest_path, f"mutable replacements are missing: {relative}")
                )
                continue
            source = mutable_path.read_text(errors="replace")
            for replacement in replacements:
                before = replacement.get("before") if isinstance(replacement, dict) else None
                after = replacement.get("after") if isinstance(replacement, dict) else None
                count = replacement.get("count") if isinstance(replacement, dict) else None
                if (
                    not isinstance(before, str)
                    or not isinstance(after, str)
                    or not isinstance(count, int)
                    or count < 1
                    or source.count(before) != count
                    or source.count(after) != 0
                ):
                    failures.append(
                        _failure(
                            manifest_path,
                            f"invalid mutable replacement for {relative}",
                        )
                    )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        failures.append(_failure(manifest_path, f"invalid protected manifest: {error}"))
    return failures


def validate_versions_file(path: Path) -> tuple[ValidationFailure, ...]:
    failures: list[ValidationFailure] = []
    try:
        versions = load_versions(path)
    except Exception as error:
        return (_failure(path, f"invalid version ledger: {error}"),)

    repository = versions.get("repository", {})
    if not repository.get("schema_version"):
        failures.append(_failure(path, "repository schema_version is required"))

    seen_sources: set[str] = set()
    for source in versions.get("sources", []):
        name = str(source.get("name", "<unnamed>"))
        if name in seen_sources:
            failures.append(_failure(path, f"duplicate source name: {name}"))
        seen_sources.add(name)
        if not _FULL_COMMIT.fullmatch(str(source.get("commit", ""))):
            failures.append(
                _failure(path, f"source {name} requires a full 40-character commit")
            )
        if not str(source.get("url", "")).startswith("https://"):
            failures.append(_failure(path, f"source {name} requires an HTTPS URL"))

    seen_packages: set[tuple[str, str]] = set()
    for package in versions.get("packages", []):
        identity = (str(package.get("ecosystem", "")), str(package.get("name", "")))
        if identity in seen_packages:
            failures.append(_failure(path, f"duplicate package pin: {identity[1]}"))
        seen_packages.add(identity)
        version = str(package.get("version", ""))
        if not version or version == "latest" or "*" in version:
            failures.append(_failure(path, f"package {identity[1]} requires an exact version"))

    for container in versions.get("containers", []):
        name = str(container.get("name", "<unnamed>"))
        tag = str(container.get("tag", ""))
        if not tag or tag == "latest":
            failures.append(_failure(path, f"container {name} requires an immutable tag"))
        if not _DIGEST.fullmatch(str(container.get("digest", ""))):
            failures.append(_failure(path, f"container {name} requires a sha256 digest"))

    for action in versions.get("actions", []):
        name = str(action.get("name", "<unnamed>"))
        if not _FULL_COMMIT.fullmatch(str(action.get("commit", ""))):
            failures.append(_failure(path, f"action {name} requires a full commit"))

    return tuple(failures)


def find_sensitive_keys(value: Any) -> tuple[str, ...]:
    matches: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(key)).strip("_")
                if _SENSITIVE_KEY.search(normalized):
                    matches.append(child_path)
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return tuple(matches)


def validate_task_paths(
    paths: Iterable[Path], *, expected_schema: str
) -> tuple[ValidationFailure, ...]:
    failures: list[ValidationFailure] = []
    packages: dict[str, Path] = {}

    for path in sorted(paths):
        try:
            task = load_task(path, expected_schema=expected_schema)
        except Exception as error:
            failures.append(_failure(path, f"invalid task: {error}"))
            continue

        if task.task is None:
            failures.append(_failure(path, "[task] package metadata is required"))
        else:
            package_name = task.task.name
            if task.task.version is None:
                failures.append(_failure(path, "task package version is required"))
            if previous := packages.get(package_name):
                failures.append(
                    _failure(
                        path,
                        f"duplicate task package {package_name}; first declared in {previous}",
                    )
                )
            else:
                packages[package_name] = path

        if task.environment.network_mode != NetworkMode.NO_NETWORK:
            failures.append(_failure(path, "environment network_mode must be no-network"))
        if task.agent.network_mode != NetworkMode.ALLOWLIST:
            failures.append(_failure(path, "agent network_mode must be allowlist"))
        if task.agent.allowed_hosts not in (None, []):
            failures.append(_failure(path, "task-level agent allowed_hosts must be empty"))
        if task.verifier.environment_mode != VerifierEnvironmentMode.SEPARATE:
            failures.append(_failure(path, "a separate verifier is required"))
        if task.verifier.network_mode != NetworkMode.NO_NETWORK:
            failures.append(_failure(path, "verifier network_mode must be no-network"))

        artifacts = {
            (artifact.source, artifact.destination)
            for artifact in task.artifacts
            if not isinstance(artifact, str)
        }
        required_artifacts = {
            ("/app", "workspace"),
            ("/logs/agent/trajectory.json", "trajectory.json"),
        }
        for missing in sorted(required_artifacts - artifacts):
            failures.append(
                _failure(path, f"required artifact is missing: {missing[0]} -> {missing[1]}")
            )
        workspace_artifacts = [
            artifact
            for artifact in task.artifacts
            if not isinstance(artifact, str)
            and artifact.source == "/app"
            and artifact.destination == "workspace"
        ]
        required_excludes = {".git", "node_modules", "target"}
        if len(workspace_artifacts) == 1 and not required_excludes.issubset(
            workspace_artifacts[0].exclude
        ):
            failures.append(
                _failure(
                    path,
                    "workspace artifact must exclude .git, node_modules, and target",
                )
            )

        failures.extend(_validate_benchmark_task_assets(path, task))

    return tuple(failures)


def _discover_task_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for pack_name in ("contract", "workflow"):
        pack = root / "tasks" / pack_name
        if not pack.is_dir():
            continue
        for task_directory in sorted(path for path in pack.iterdir() if path.is_dir()):
            task_path = task_directory / "task.toml"
            if task_path.is_file():
                paths.append(task_path)
    return tuple(paths)


def _validate_generated_jobs(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    generated = root / "runs" / "generated"
    if not generated.is_dir():
        return failures
    for path in sorted((*generated.rglob("*.yml"), *generated.rglob("*.yaml"))):
        try:
            raw = yaml.safe_load(path.read_text())
            sensitive_keys = find_sensitive_keys(raw)
            if sensitive_keys:
                failures.append(
                    _failure(path, f"sensitive keys are forbidden: {', '.join(sensitive_keys)}")
                )
            job = load_job(path)
            arm_mounts = [
                mount
                for mount in job.environment.mounts or []
                if mount.get("target") == "/harness-arm"
            ]
            if len(arm_mounts) != 1 or arm_mounts[0].get("read_only") is not True:
                failures.append(
                    _failure(path, "generated jobs require one read-only /harness-arm mount")
                )
        except Exception as error:
            failures.append(_failure(path, f"invalid generated job: {error}"))
    for path in sorted(generated.rglob("Manifest.json")):
        try:
            from harness_testing.Runs import verify_manifest_document

            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("manifest must contain an object")
            sensitive_keys = find_sensitive_keys(raw)
            if sensitive_keys:
                failures.append(
                    _failure(path, f"sensitive keys are forbidden: {', '.join(sensitive_keys)}")
                )
            verify_manifest_document(raw)
        except Exception as error:
            failures.append(_failure(path, f"invalid generated manifest: {error}"))
    return failures


def _validate_atif_fixtures(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    fixture_root = root / "tests" / "Fixtures" / "ATIF"
    if not fixture_root.is_dir():
        return failures
    for path in sorted(fixture_root.glob("Valid_*.json")):
        try:
            load_trajectory(path)
        except Exception as error:
            failures.append(_failure(path, f"invalid ATIF fixture: {error}"))
    return failures


def _repository_files(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(root / path for path in result.stdout.decode().split("\0") if path)


def _validate_checked_in_commands(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    executable_suffixes = {".sh", ".bash", ".zsh", ".yml", ".yaml"}
    for path in _repository_files(root):
        relative = path.relative_to(root)
        if path.suffix not in executable_suffixes and relative != Path("pyproject.toml"):
            continue
        text = path.read_text(errors="replace")
        if re.search(r"(?:^|\s)harbor\s+check(?:\s|$)", text):
            failures.append(_failure(path, "checked-in commands must not invoke harbor check"))
        if relative.parts[:2] == (".github", "workflows") and (
            re.search(r"(?:^|\s)harbor\s+run(?:\s|$)", text)
            or "harness-test run execute" in text
        ):
            failures.append(_failure(path, "CI must not start live model trials"))
    return failures


def _validate_public_boundary(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    forbidden_prefixes = (
        "jobs/",
        "raw-results/",
        "provider-homes/",
        "arms/materialized/",
        "runs/generated/",
        "dashboard/node_modules/",
        "dashboard/dist/",
    )
    for path in _repository_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(forbidden_prefixes):
            failures.append(_failure(path, "local or raw artifact crosses the public boundary"))
    return failures


def validate_repository(root: Path) -> tuple[ValidationFailure, ...]:
    versions_path = root / "Versions.toml"
    failures = list(validate_versions_file(versions_path))
    if failures:
        expected_schema = "1.4"
    else:
        versions = load_versions(versions_path)
        expected_schema = str(versions.get("standards", {}).get("harbor_task_schema", "1.4"))

    failures.extend(
        validate_task_paths(_discover_task_paths(root), expected_schema=expected_schema)
    )
    failures.extend(_validate_generated_jobs(root))
    failures.extend(_validate_atif_fixtures(root))
    failures.extend(_validate_checked_in_commands(root))
    failures.extend(_validate_public_boundary(root))
    return tuple(failures)
