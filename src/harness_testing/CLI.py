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

    run_parser = subparsers.add_parser("run", help="plan or execute guarded Harbor runs")
    run_subparsers = run_parser.add_subparsers(dest="run_command")
    plan_parser = run_subparsers.add_parser("plan", help="compile a dry-run manifest")
    plan_parser.add_argument(
        "--profile",
        choices=("smoke", "checkpoint", "release", "calibration", "research"),
        required=True,
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
    elif arguments.command == "run" and arguments.run_command == "plan":
        from harness_testing.Runs import format_plan, plan_run

        manifest = plan_run(
            _repository_root(),
            profile=arguments.profile,
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
    return 0
