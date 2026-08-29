"""Command-line entry point for deterministic harness evaluation."""

from __future__ import annotations

import argparse
import shlex
import sys
import tomllib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _schema_version() -> str:
    with (_repository_root() / "Versions.toml").open("rb") as versions_file:
        versions = tomllib.load(versions_file)
    return str(versions["repository"]["schema_version"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-test")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_schema_version()}",
    )
    subparsers = parser.add_subparsers(dest="command")
    validate_parser = subparsers.add_parser("validate", help="validate deterministic inputs")
    validate_parser.add_argument("--changed-from")
    validate_parser.add_argument("--static-only", action="store_true")

    images_parser = subparsers.add_parser("images", help="manage pinned images")
    image_subparsers = images_parser.add_subparsers(dest="images_command")
    build_parser = image_subparsers.add_parser("build", help="build selected images")
    build_parser.add_argument("--node", action="store_true")
    build_parser.add_argument("--rust", action="store_true")
    build_parser.add_argument("--verifier", action="store_true")
    build_parser.add_argument("--all", action="store_true")

    arm_parser = subparsers.add_parser("arm", help="materialize provider-native arms")
    arm_subparsers = arm_parser.add_subparsers(dest="arm_command")
    materialize_parser = arm_subparsers.add_parser(
        "materialize", help="materialize one immutable provider arm"
    )
    materialize_parser.add_argument("--provider", choices=("claude", "codex"), required=True)
    materialize_parser.add_argument("--arm", choices=("A0", "A1", "A2", "A3"), required=True)
    materialize_parser.add_argument("--harness-source")
    materialize_parser.add_argument("--harness-commit")

    deepswe_parser = subparsers.add_parser(
        "deepswe", help="manage the manual DeepSWE capability lane"
    )
    deepswe_subparsers = deepswe_parser.add_subparsers(dest="deepswe_command")
    deepswe_materialize_parser = deepswe_subparsers.add_parser(
        "materialize", help="fetch and derive the pinned six-task cohort"
    )
    deepswe_materialize_parser.add_argument(
        "--confirm-download", action="store_true"
    )

    regrade_parser = subparsers.add_parser(
        "regrade", help="re-run Harbor verification without an agent phase"
    )
    regrade_parser.add_argument("--job", type=Path, required=True)
    regrade_parser.add_argument("--tasks", type=Path, required=True)

    result_parser = subparsers.add_parser(
        "result", help="construct fail-closed public result files"
    )
    result_subparsers = result_parser.add_subparsers(dest="result_command")
    sanitize_parser = result_subparsers.add_parser(
        "sanitize", help="validate and write one allowlisted result"
    )
    sanitize_parser.add_argument("--job", type=Path, required=True)
    sanitize_parser.add_argument("--output", type=Path, required=True)

    run_parser = subparsers.add_parser("run", help="plan or execute guarded Harbor runs")
    run_subparsers = run_parser.add_subparsers(dest="run_command")
    plan_parser = run_subparsers.add_parser("plan", help="compile a dry-run manifest")
    plan_parser.add_argument(
        "--profile",
        choices=("smoke", "checkpoint", "release", "calibration", "research"),
        required=True,
    )
    plan_parser.add_argument(
        "--billing-mode", choices=("subscription", "api"), required=True
    )
    plan_parser.add_argument("--cell", action="append", default=[])
    plan_parser.add_argument("--task", action="append", default=[])
    plan_parser.add_argument("--max-sessions", type=int, required=True)
    plan_parser.add_argument("--max-budget-usd", type=Decimal, required=True)
    plan_parser.add_argument("--attempts", type=int)
    plan_parser.add_argument("--concurrency", type=int)
    plan_parser.add_argument("--agent-timeout-seconds", type=int)
    execute_parser = run_subparsers.add_parser(
        "execute", help="execute an exact approved manifest"
    )
    execute_parser.add_argument("--manifest", type=Path, required=True)
    execute_parser.add_argument("--approve", required=True)

    task_parser = subparsers.add_parser("task", help="validate benchmark tasks")
    task_subparsers = task_parser.add_subparsers(dest="task_command")
    qa_parser = task_subparsers.add_parser("qa", help="run one model-free task QA case")
    qa_parser.add_argument("--task", required=True)
    qa_parser.add_argument(
        "--case",
        choices=("oracle", "nop", "near-miss", "adversarial", "source-tamper"),
        required=True,
    )

    arguments = parser.parse_args(argv)
    if arguments.command == "validate":
        from harness_testing.Validate import validate_repository

        failures = validate_repository(_repository_root())
        if failures:
            for failure in failures:
                print(failure, file=sys.stderr)
            return 1
        print("Static validation passed.")
    elif arguments.command == "images" and arguments.images_command == "build":
        from harness_testing.Materialize import build_images, image_build_commands

        selected = tuple(
            image
            for image in ("node", "rust", "verifier")
            if arguments.all or getattr(arguments, image)
        )
        if not selected:
            print("Planned image builds:")
            for command in image_build_commands(
                _repository_root(), ("node", "rust", "verifier")
            ):
                print(f"  {shlex.join(command.arguments)}")
            print("No image selected; pass a specific image flag or --all.", file=sys.stderr)
            return 2
        build_images(_repository_root(), selected)
    elif arguments.command == "arm" and arguments.arm_command == "materialize":
        from harness_testing.Materialize import materialize_arm

        materialized = materialize_arm(
            _repository_root(),
            arguments.provider,
            arguments.arm,
            harness_source=arguments.harness_source,
            harness_commit=arguments.harness_commit,
        )
        print(f"{materialized.provider}:{materialized.arm} {materialized.digest}")
        print(materialized.path)
    elif (
        arguments.command == "deepswe"
        and arguments.deepswe_command == "materialize"
    ):
        from harness_testing.Materialize import (
            deepswe_materialization_plan,
            format_deepswe_plan,
            materialize_deepswe,
        )

        plan = deepswe_materialization_plan(_repository_root())
        print(format_deepswe_plan(plan))
        if not arguments.confirm_download:
            print(
                "No files downloaded or images built; pass --confirm-download to "
                "execute this exact plan.",
                file=sys.stderr,
            )
            return 2
        materialized = materialize_deepswe(
            _repository_root(), confirm_download=True
        )
        print(f"Materialized dataset: {materialized.digest}")
        print(materialized.path)
    elif arguments.command == "regrade":
        from harness_testing.Results import regrade_job

        try:
            record = regrade_job(
                _repository_root(),
                arguments.job,
                arguments.tasks,
            )
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(f"Source job: {record.source_job_id} {record.source_job_digest}")
        print(f"Regrade job: {record.regrade_job_path}")
    elif arguments.command == "result" and arguments.result_command == "sanitize":
        from harness_testing.Results import sanitize_public_result

        try:
            result = sanitize_public_result(
                _repository_root(),
                arguments.job,
                arguments.output,
            )
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(f"Sanitized result: {result['result_id']}")
        print(arguments.output)
    elif arguments.command == "run" and arguments.run_command == "plan":
        from harness_testing.Runs import format_plan, plan_run

        manifest = plan_run(
            _repository_root(),
            profile=arguments.profile,
            billing_mode=arguments.billing_mode,
            cell_specifications=tuple(arguments.cell),
            task_ids=tuple(arguments.task),
            max_sessions=arguments.max_sessions,
            max_budget_usd=arguments.max_budget_usd,
            attempts=arguments.attempts,
            concurrency=arguments.concurrency,
            agent_timeout_seconds=arguments.agent_timeout_seconds,
        )
        print(format_plan(manifest))
    elif arguments.command == "run" and arguments.run_command == "execute":
        from harness_testing.Runs import execute_run

        execute_run(_repository_root(), arguments.manifest, arguments.approve)
    elif arguments.command == "task" and arguments.task_command == "qa":
        from harness_testing.QA import run_task_qa

        scores = run_task_qa(_repository_root(), arguments.task, arguments.case)
        print(
            " ".join(
                f"{name}={scores[name]:g}"
                for name in ("reward", "workflow", "efficiency")
            )
        )
    return 0
