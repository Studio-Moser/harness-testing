"""Deterministic repository policy validation."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml
from harbor.models.task.config import NetworkMode, TaskConfig, VerifierEnvironmentMode
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from harness_testing.Config import load_job, load_task, load_trajectory, load_versions
from harness_testing.Harness_Result import harness_result_schema_errors

_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_key|access_token|auth_token|authorization|password|secret|credential)(?:$|_)",
    re.IGNORECASE,
)
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_PROVIDER_CREDENTIAL = re.compile(
    r"\b(?:ANTHROPIC_API_KEY|ANTHROPIC_BASE_URL|CLAUDE_CODE_OAUTH_TOKEN|"
    r"CODEX_AUTH_JSON_PATH|OPENAI_API_KEY|OPENAI_API_BASE|OPENAI_BASE_URL)\b"
)
_CORE_SCHEMA_PATHS = {
    "src/harness_testing/Config.py",
    "tests/Support/QA_Agents.py",
}
_POLICY_PATHS = {
    "policy/Command_Classification.toml",
    "policy/Verification_Envelopes.toml",
    "src/harness_testing/Metrics.py",
}
_HARNESS_RESULT_SCHEMA_TESTS = {
    "tests/unit/test_Contract_Criteria.py",
    "tests/unit/test_Contract_Stub_Server.py",
    "tests/unit/test_Harness_Result.py",
    "tests/unit/test_Materialize.py",
    "tests/unit/test_Validate.py",
}
_TRAJECTORY_DECODER_TESTS = {
    "tests/unit/test_Codex_Agent.py",
    "tests/unit/test_Metrics.py",
    "tests/unit/test_Sentinel_Criteria.py",
    "tests/unit/test_Trajectory_Events.py",
    "tests/unit/test_Workflow_Criteria.py",
}
_WORKFLOW_GIT_BASELINE_FRAGMENTS = (
    "git init --quiet --initial-branch=main",
    'git config user.name "Benchmark Author"',
    'git config user.email "benchmark@example.invalid"',
    'AGENTS.md',
    'CLAUDE.md',
    'node_modules/',
    'target/',
    'dist/',
    '> .git/info/exclude',
    'git add --all',
    'GIT_AUTHOR_DATE="2025-01-01T00:00:00Z"',
    'GIT_COMMITTER_DATE="2025-01-01T00:00:00Z"',
    'git commit --quiet -m "Frozen workflow fixture"',
    'test -z "$(git status --porcelain)"',
)
_FULL_DETERMINISTIC_COMMANDS = (
    ("uv", "run", "ruff", "check", "src", "tests"),
    ("uv", "run", "pytest", "tests/unit", "-q"),
    ("npm", "ci", "--prefix", "dashboard", "--ignore-scripts"),
    ("npm", "--prefix", "dashboard", "test"),
    ("npm", "--prefix", "dashboard", "run", "build"),
    (
        "uv",
        "run",
        "harness-test",
        "task",
        "qa",
        "--pack",
        "workflow",
        "--all-cases",
    ),
    (
        "uv",
        "run",
        "harness-test",
        "task",
        "qa",
        "--pack",
        "contract",
        "--all-cases",
    ),
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
    environment_directory = task_root / "environment"
    is_rust = (environment_directory / "Cargo.toml").is_file()
    is_contract = task.metadata.get("category") == "contract"
    required_files = [
        "instruction.md",
        "environment/Dockerfile",
        "solution/solve.sh",
        "tests/Dockerfile",
        "tests/test.sh",
        "tests/criteria.py",
        "tests/Protected_Files.json",
    ]
    if is_contract:
        required_files.extend(
            (
                "environment/docker-compose.yaml",
                "tests/Expected.json",
                "tests/QA.json",
            )
        )
        if task.task and task.task.name == "studio-moser/standalone-computer-use":
            required_files.extend(
                (
                    "environment/Fixture/Computer_Use_Request.json",
                    "environment/computer-use-server/Dockerfile",
                    "environment/computer-use-server/Server.py",
                )
            )
        else:
            required_files.extend(
                (
                    "environment/Harness_Stub.mjs",
                    "environment/stub-server/Dockerfile",
                    "environment/stub-server/Scenario.json",
                )
            )
    elif is_rust:
        required_files.extend(("environment/Cargo.toml", "environment/Cargo.lock"))
    else:
        required_files.extend(
            (
                "environment/package.json",
                "environment/package-lock.json",
                "tests/Verifier/package.json",
                "tests/Verifier/package-lock.json",
            )
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

    if not is_contract:
        dockerfile_path = environment_directory / "Dockerfile"
        dockerfile = dockerfile_path.read_text()
        if not all(
            fragment in dockerfile for fragment in _WORKFLOW_GIT_BASELINE_FRAGMENTS
        ):
            failures.append(
                _failure(
                    dockerfile_path,
                    "workflow fixture must create a deterministic Git baseline",
                )
            )

    test_script = (task_root / "tests" / "test.sh").read_text()
    if re.search(r"\b(?:uvx|pip\s+install|npm\s+install)\b", test_script):
        failures.append(
            _failure(
                task_root / "tests" / "test.sh",
                "verifier runtime must not install or download dependencies",
            )
        )

    if not is_rust and not is_contract:
        try:
            environment_package = json.loads(
                (task_root / "environment" / "package.json").read_text()
            )
            verifier_package = json.loads(
                (task_root / "tests" / "Verifier" / "package.json").read_text()
            )
            available_dependencies = {
                **environment_package.get("dependencies", {}),
                **environment_package.get("devDependencies", {}),
            }
            verifier_names = {
                "@vitejs/plugin-react",
                "happy-dom",
                "react",
                "react-dom",
                "vite",
                "vitest",
            }
            expected_dependencies = {
                name: available_dependencies[name]
                for name in sorted(verifier_names)
                if name in available_dependencies
            }
            if verifier_package.get("dependencies") != expected_dependencies:
                failures.append(
                    _failure(
                        task_root / "tests" / "Verifier" / "package.json",
                        "verifier dependencies must be the exact frozen behavior-test subset",
                    )
                )
        except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
            failures.append(
                _failure(
                    task_root / "tests" / "Verifier" / "package.json",
                    f"invalid verifier dependency manifest: {error}",
                )
            )

    if is_contract:
        expected_path = task_root / "tests" / "Expected.json"
        qa_path = task_root / "tests" / "QA.json"
        expected: dict[str, Any] = {}
        try:
            expected = json.loads(expected_path.read_text())
            result = expected["result"]
            if set(expected) != {
                "artifacts",
                "calls",
                "evidence_requirements",
                "result",
            }:
                raise ValueError(
                    "Expected.json requires artifacts, calls, evidence_requirements, "
                    "and result"
                )
            evidence_requirements = expected["evidence_requirements"]
            if (
                not isinstance(evidence_requirements, list)
                or not evidence_requirements
                or not all(
                    isinstance(requirement, str) and requirement.strip()
                    for requirement in evidence_requirements
                )
            ):
                raise ValueError("evidence_requirements must contain exact prefixes")
            errors = harness_result_schema_errors(result)
            if errors:
                raise ValueError(
                    "; ".join(
                        f"HarnessResult {pointer}: {validator}"
                        for pointer, validator in errors
                    )
                )
            qa = json.loads(qa_path.read_text())
            if set(qa["cases"]) != {
                "oracle",
                "nop",
                "near-miss",
                "adversarial",
                "source-tamper",
            }:
                raise ValueError("QA.json must define the five deterministic cases")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            failures.append(
                _failure(expected_path, f"invalid contract expectation: {error}")
            )

        event_artifacts = [
            artifact
            for artifact in task.artifacts
            if not isinstance(artifact, str)
            and artifact.service not in (None, "main")
            and artifact.source.endswith("Events.jsonl")
        ]
        if len(event_artifacts) != 1:
            failures.append(
                _failure(
                    task_path,
                    "contract task requires one protected sidecar Events.jsonl artifact",
                )
            )

        if task.task and task.task.name == "studio-moser/standalone-computer-use":
            dockerfile_path = (
                environment_directory / "computer-use-server" / "Dockerfile"
            )
            dockerfile = dockerfile_path.read_text()
            if not all(
                fragment in dockerfile
                for fragment in (
                    "mcp==2.1.1",
                    "playwright==1.62.0",
                    "mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:",
                )
            ):
                failures.append(
                    _failure(
                        dockerfile_path,
                        "computer-use sidecar must use the pinned MCP and Playwright stack",
                    )
                )
            if len(task.environment.mcp_servers) != 1:
                failures.append(
                    _failure(task_path, "computer-use task requires one MCP server")
                )
        else:
            scenario_path = environment_directory / "stub-server" / "Scenario.json"
            try:
                scenario = json.loads(scenario_path.read_text())
                contract = scenario.get("contract")
                if isinstance(contract, dict) and "harness_result_schema" in contract:
                    raise ValueError("scenario contract reserves harness_result_schema")
                scenario_calls = [
                    {"action": call["action"], "payload": call["payload"]}
                    for call in scenario["calls"]
                ]
                if scenario_calls != expected.get("calls"):
                    raise ValueError("protected scenario calls differ from Expected.json")
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                failures.append(
                    _failure(scenario_path, f"invalid contract scenario: {error}")
                )

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
        protected_root = (
            environment_directory / "Fixture" if is_contract else environment_directory
        )
        if not isinstance(protected_files, dict) or not protected_files:
            raise ValueError("files must be a non-empty object")
        for relative, expected in protected_files.items():
            protected_path = protected_root / relative
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
            mutable_path = protected_root / relative
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
    if not repository.get("image_version"):
        failures.append(_failure(path, "repository image_version is required"))

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

    if "deepswe" in versions:
        from harness_testing.Materialize import deepswe_materialization_plan

        try:
            deepswe_materialization_plan(path.parent)
        except (KeyError, TypeError, ValueError) as error:
            failures.append(_failure(path, f"invalid DeepSWE capability pin: {error}"))

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


def validate_public_results(root: Path) -> tuple[ValidationFailure, ...]:
    """Validate the publication schema and every JSON result under results/."""

    failures: list[ValidationFailure] = []
    schema_path = root / "policy" / "Public_Result.schema.json"
    try:
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, SchemaError) as error:
        return (_failure(schema_path, f"invalid public result schema: {error}"),)

    from harness_testing.Results import validate_public_result

    results_root = root / "results"
    if not results_root.is_dir():
        return ()
    for path in sorted(results_root.rglob("*.json")):
        try:
            document = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            failures.append(_failure(path, f"invalid public result JSON: {error}"))
            continue
        errors = validate_public_result(root, document)
        for error in errors:
            failures.append(_failure(path, error))
        run = document.get("run") if isinstance(document, dict) else None
        if not isinstance(run, dict) or run.get("finalized") is not True:
            failures.append(_failure(path, "public results must be finalized"))
    return tuple(failures)


def validate_markdown_links(root: Path) -> tuple[ValidationFailure, ...]:
    """Check repository-local Markdown links without flaky network requests."""

    failures: list[ValidationFailure] = []
    for path in sorted(path for path in _repository_files(root) if path.suffix == ".md"):
        for match in _MARKDOWN_LINK.finditer(path.read_text(errors="replace")):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and raw_target.endswith(">"):
                raw_target = raw_target[1:-1]
            else:
                raw_target = raw_target.split(maxsplit=1)[0]
            if not raw_target or raw_target.startswith("#") or re.match(
                r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw_target
            ):
                continue
            target = unquote(raw_target.split("#", 1)[0].split("?", 1)[0])
            candidate = (
                root / target.removeprefix("/")
                if target.startswith("/")
                else path.parent / target
            )
            if not candidate.exists():
                failures.append(_failure(path, f"broken local Markdown link: {raw_target}"))
    return tuple(failures)


def _workflow_uses(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                yield child
            yield from _workflow_uses(child)
    elif isinstance(value, list):
        for child in value:
            yield from _workflow_uses(child)


def validate_workflow_files(
    root: Path, action_pins: dict[str, str] | None
) -> tuple[ValidationFailure, ...]:
    """Require model-free workflows and exact action pins from Versions.toml."""

    failures: list[ValidationFailure] = []
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return ()
    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        text = path.read_text(errors="replace")
        if _PROVIDER_CREDENTIAL.search(text):
            failures.append(_failure(path, "CI must not receive provider credentials"))
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as error:
            failures.append(_failure(path, f"invalid workflow YAML: {error}"))
            continue
        if not isinstance(document, dict):
            failures.append(_failure(path, "workflow must contain a YAML object"))
            continue
        for use in _workflow_uses(document):
            if use.startswith(("./", "docker://")):
                continue
            if "@" not in use:
                failures.append(_failure(path, f"action is not pinned: {use}"))
                continue
            name, commit = use.rsplit("@", 1)
            if not _FULL_COMMIT.fullmatch(commit):
                failures.append(
                    _failure(path, f"action {name} requires a full commit: {commit}")
                )
                continue
            if action_pins is None:
                continue
            expected = action_pins.get(name)
            if expected is None:
                failures.append(_failure(path, f"action is missing from Versions.toml: {name}"))
            elif commit != expected:
                failures.append(
                    _failure(
                        path,
                        f"action {name} differs from Versions.toml: {commit} != {expected}",
                    )
                )
    return tuple(failures)


def changed_repository_paths(root: Path, changed_from: str) -> tuple[Path, ...]:
    """Return safe repository-relative paths changed since one immutable Git ref."""

    if not changed_from.strip():
        raise ValueError("changed-from Git ref must not be empty")
    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                f"{changed_from}...HEAD",
                "--",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError(f"unable to compare changed files from {changed_from}") from error
    paths: set[Path] = set()
    for name in result.stdout.splitlines():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe changed repository path: {name}")
        paths.add(path)
    return tuple(sorted(paths))


def affected_validation_commands(
    root: Path, changed_paths: Iterable[Path]
) -> tuple[tuple[str, ...], ...]:
    """Map a change set to one grouped set of deterministic checks."""

    names: set[str] = set()
    for changed_path in changed_paths:
        if changed_path.is_absolute() or ".." in changed_path.parts:
            raise ValueError(f"unsafe changed repository path: {changed_path}")
        names.add(changed_path.as_posix())
    if names & _CORE_SCHEMA_PATHS or any(
        name.startswith("tests/Support/QA_Cases/") for name in names
    ):
        return _FULL_DETERMINISTIC_COMMANDS

    python_paths = sorted(
        name
        for name in names
        if name.endswith(".py") and (name.startswith("src/") or name.startswith("tests/"))
    )
    unit_tests: set[str] = set()
    qa_tasks: set[str] = set()
    images: set[str] = set()
    dashboard = False
    full_unit = bool(names & {"pyproject.toml", "uv.lock"})
    workflow_pack = False

    for name in names:
        path = Path(name)
        parts = path.parts
        if name == "src/harness_testing/Run_Reports.py":
            unit_tests.add("tests/unit/test_Runs.py")
            dashboard = True
        elif name.startswith("src/harness_testing/") and name.endswith(".py"):
            candidate = root / "tests" / "unit" / f"test_{path.stem}.py"
            if candidate.is_file():
                unit_tests.add(candidate.relative_to(root).as_posix())
            else:
                full_unit = True
        elif len(parts) >= 3 and parts[:2] == ("tests", "unit"):
            unit_tests.add(name)
        elif name.startswith("tests/Fixtures/ATIF/"):
            unit_tests.update(
                {
                    "tests/unit/test_Config.py",
                    "tests/unit/test_Metrics.py",
                    "tests/unit/test_Trajectory_Events.py",
                }
            )
        elif name.startswith("tests/Fixtures/Public_Results/"):
            unit_tests.update(
                {"tests/unit/test_Results.py", "tests/unit/test_Validate.py"}
            )
            dashboard = True
        elif name.startswith("tests/Fixtures/Run_Reports/"):
            unit_tests.update(
                {"tests/unit/test_Runs.py", "tests/unit/test_Validate.py"}
            )
            dashboard = True
        elif name.startswith("tests/Support/"):
            full_unit = True

        if len(parts) >= 3 and parts[0] == "tasks" and parts[1] in {
            "contract",
            "workflow",
        }:
            task_id = parts[2]
            if (root / "tasks" / parts[1] / task_id / "task.toml").is_file():
                qa_tasks.add(task_id)

        if name == "images/Node_Agent.Dockerfile":
            images.add("node")
        elif name == "images/Rust_Agent.Dockerfile":
            images.add("rust")
        elif name == "images/Verifier.Dockerfile":
            images.add("verifier")
        if name.startswith("images/"):
            unit_tests.add("tests/unit/test_Materialize.py")

        if name == "src/harness_testing/Harness_Result.schema.json":
            unit_tests.update(_HARNESS_RESULT_SCHEMA_TESTS)
            images.add("verifier")
        if name == "src/harness_testing/Trajectory_Events.py":
            unit_tests.update(_TRAJECTORY_DECODER_TESTS)
            images.add("verifier")
            workflow_pack = True

        if name == "policy/Run_Report.schema.json":
            unit_tests.update(
                {"tests/unit/test_Runs.py", "tests/unit/test_Validate.py"}
            )
            dashboard = True
        elif name in _POLICY_PATHS or name.startswith("policy/"):
            unit_tests.update(
                {
                    "tests/unit/test_Metrics.py",
                    "tests/unit/test_Results.py",
                    "tests/unit/test_Validate.py",
                }
            )
        if name == "policy/Public_Result.schema.json" or name.startswith("results/"):
            dashboard = True
        if name.startswith("dashboard/"):
            dashboard = True
        if name.startswith("arms/"):
            unit_tests.update(
                {"tests/unit/test_Materialize.py", "tests/unit/test_Runs.py"}
            )
        if name == "Versions.toml":
            unit_tests.update(
                {
                    "tests/unit/test_Materialize.py",
                    "tests/unit/test_Runs.py",
                    "tests/unit/test_Validate.py",
                }
            )
        if name.startswith(".github/workflows/"):
            unit_tests.add("tests/unit/test_Validate.py")

    commands: list[tuple[str, ...]] = []
    if python_paths:
        commands.append(("uv", "run", "ruff", "check", *python_paths))
    if full_unit:
        commands.append(("uv", "run", "pytest", "tests/unit", "-q"))
    elif unit_tests:
        commands.append(("uv", "run", "pytest", "-q", *sorted(unit_tests)))
    if images:
        flags = tuple(
            f"--{image}"
            for image in ("node", "rust", "verifier")
            if image in images
        )
        commands.append(("uv", "run", "harness-test", "images", "build", *flags))
    for task_id in sorted(qa_tasks):
        for case in ("oracle", "nop"):
            commands.append(
                (
                    "uv",
                    "run",
                    "harness-test",
                    "task",
                    "qa",
                    "--task",
                    task_id,
                    "--case",
                    case,
                )
            )
    if workflow_pack:
        commands.append(
            (
                "uv",
                "run",
                "harness-test",
                "task",
                "qa",
                "--pack",
                "workflow",
                "--all-cases",
            )
        )
    if dashboard:
        commands.extend(
            (
                ("npm", "ci", "--prefix", "dashboard", "--ignore-scripts"),
                ("npm", "--prefix", "dashboard", "test"),
                ("npm", "--prefix", "dashboard", "run", "build"),
            )
        )
    return tuple(dict.fromkeys(commands))


def run_affected_validation(
    root: Path,
    changed_from: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> tuple[tuple[str, ...], ...]:
    paths = changed_repository_paths(root, changed_from)
    commands = affected_validation_commands(root, paths)
    if not commands:
        print("No affected dynamic checks; static validation is sufficient.")
        return ()
    for command in commands:
        print(f"Affected check: {shlex.join(command)}", flush=True)
        runner(command, cwd=root, check=True)
    return commands


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
        ".cache/deepswe/",
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
    versions: dict[str, Any] | None = None
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
    failures.extend(validate_public_results(root))
    failures.extend(validate_markdown_links(root))
    action_pins = (
        None
        if versions is None
        else {
            str(action["name"]): str(action["commit"])
            for action in versions.get("actions", [])
        }
    )
    failures.extend(validate_workflow_files(root, action_pins))
    failures.extend(_validate_checked_in_commands(root))
    failures.extend(_validate_public_boundary(root))
    return tuple(failures)
