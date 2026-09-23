"""Command-line entry point for deterministic harness evaluation."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Sequence
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
    validate_mode = validate_parser.add_mutually_exclusive_group()
    validate_mode.add_argument("--changed-from")
    validate_mode.add_argument("--static-only", action="store_true")

    images_parser = subparsers.add_parser("images", help="manage pinned images")
    image_subparsers = images_parser.add_subparsers(dest="images_command")
    build_parser = image_subparsers.add_parser("build", help="build selected images")
    build_parser.add_argument("--node", action="store_true")
    build_parser.add_argument("--rust", action="store_true")
    build_parser.add_argument("--verifier", action="store_true")
    build_parser.add_argument("--all", action="store_true")

    deepswe_parser = subparsers.add_parser(
        "deepswe", help="manage the manual DeepSWE capability lane"
    )
    deepswe_subparsers = deepswe_parser.add_subparsers(dest="deepswe_command")
    deepswe_materialize_parser = deepswe_subparsers.add_parser(
        "materialize", help="fetch and derive the pinned six-task cohort"
    )
    deepswe_materialize_parser.add_argument("--confirm-download", action="store_true")
    deepswe_materialize_parser.add_argument("--task", action="append", default=[])

    review_parser = subparsers.add_parser(
        "review", help="freeze or import model-free final-patch review evidence"
    )
    review_subparsers = review_parser.add_subparsers(dest="review_command")
    review_prepare_parser = review_subparsers.add_parser(
        "prepare", help="create blinded frozen review packets"
    )
    review_prepare_parser.add_argument("--report", type=Path, required=True)
    review_prepare_parser.add_argument("--protocol", type=Path, required=True)
    review_record_parser = review_subparsers.add_parser(
        "record", help="validate and import returned review evidence"
    )
    review_record_parser.add_argument("--plan", type=Path, required=True)
    review_record_parser.add_argument("--results", type=Path, required=True)

    collaboration_parser = subparsers.add_parser(
        "collaboration", help="prepare or import blinded collaboration evidence"
    )
    collaboration_subparsers = collaboration_parser.add_subparsers(dest="collaboration_command")
    collaboration_prepare = collaboration_subparsers.add_parser(
        "prepare", help="create blinded transcript grading packets"
    )
    collaboration_prepare.add_argument("--report", type=Path, required=True)
    collaboration_prepare.add_argument("--protocol", type=Path, required=True)
    collaboration_record = collaboration_subparsers.add_parser(
        "record", help="import validated transcript grades"
    )
    collaboration_record.add_argument("--plan", type=Path, required=True)
    collaboration_record.add_argument("--results", type=Path, required=True)

    auth_parser = subparsers.add_parser("auth", help="store local subscription credentials")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")
    auth_subparsers.add_parser("claude", help="store the Claude subscription token")

    run_parser = subparsers.add_parser("run", help="plan or execute guarded Harbor runs")
    campaign_parser = subparsers.add_parser(
        "campaign", help="coordinate frozen full-toolbox lanes without executing models"
    )
    campaign_commands = campaign_parser.add_subparsers(dest="campaign_command", required=True)
    campaign_plan_parser = campaign_commands.add_parser("plan")
    campaign_plan_parser.add_argument("--manifest", type=Path, action="append", required=True)
    campaign_summary_parser = campaign_commands.add_parser("summarize")
    campaign_summary_parser.add_argument("--plan", type=Path, required=True)
    campaign_summary_parser.add_argument("--report", type=Path, action="append", required=True)
    run_subparsers = run_parser.add_subparsers(dest="run_command")
    plan_parser = run_subparsers.add_parser("plan", help="compile a dry-run manifest")
    plan_parser.add_argument("--request", type=Path, required=True)
    execute_parser = run_subparsers.add_parser("execute", help="execute an exact approved manifest")
    execute_parser.add_argument("--manifest", type=Path, required=True)
    execute_parser.add_argument("--approve", required=True)

    task_parser = subparsers.add_parser("task", help="validate benchmark tasks")
    task_subparsers = task_parser.add_subparsers(dest="task_command")
    qa_parser = task_subparsers.add_parser("qa", help="run model-free task QA cases")
    qa_selection = qa_parser.add_mutually_exclusive_group(required=True)
    qa_selection.add_argument("--task")
    qa_selection.add_argument("--pack", choices=("workflow",))
    qa_cases = qa_parser.add_mutually_exclusive_group(required=True)
    qa_cases.add_argument(
        "--case",
        choices=("oracle", "nop", "near-miss", "adversarial", "source-tamper"),
    )
    qa_cases.add_argument("--all-cases", action="store_true")
    qa_parser.add_argument("--variant", choices=("workflow", "comparison"), default="workflow")

    arguments = parser.parse_args(argv)
    if arguments.command == "validate":
        from harness_testing.Validate import run_affected_validation, validate_repository

        failures = validate_repository(_repository_root())
        if failures:
            for failure in failures:
                print(failure, file=sys.stderr)
            return 1
        print("Static validation passed.")
        if arguments.changed_from:
            try:
                run_affected_validation(_repository_root(), arguments.changed_from)
            except (ValueError, subprocess.CalledProcessError) as error:
                print(error, file=sys.stderr)
                return getattr(error, "returncode", 1) or 1
    elif arguments.command == "images" and arguments.images_command == "build":
        from harness_testing.Materialize import build_images, image_build_commands

        selected = tuple(
            image
            for image in ("node", "rust", "verifier")
            if arguments.all or getattr(arguments, image)
        )
        if not selected:
            print("Planned image builds:")
            for command in image_build_commands(_repository_root(), ("node", "rust", "verifier")):
                print(f"  {shlex.join(command.arguments)}")
            print("No image selected; pass a specific image flag or --all.", file=sys.stderr)
            return 2
        build_images(_repository_root(), selected)
    elif arguments.command == "deepswe" and arguments.deepswe_command == "materialize":
        from harness_testing.Materialize import (
            deepswe_materialization_plan,
            format_deepswe_plan,
            materialize_deepswe,
        )

        task_ids = tuple(arguments.task) or None
        plan = deepswe_materialization_plan(_repository_root(), task_ids=task_ids)
        print(format_deepswe_plan(plan))
        if not arguments.confirm_download:
            print(
                "No files downloaded or images built; pass --confirm-download to "
                "execute this exact plan.",
                file=sys.stderr,
            )
            return 2
        materialized = materialize_deepswe(
            _repository_root(), confirm_download=True, task_ids=task_ids
        )
        print(f"Materialized dataset: {materialized.digest}")
        print(materialized.path)
    elif arguments.command == "review" and arguments.review_command == "prepare":
        from harness_testing.Code_Reviews import prepare_review

        try:
            outcome = prepare_review(_repository_root(), arguments.report, arguments.protocol)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(json.dumps(outcome, indent=2, sort_keys=True))
    elif arguments.command == "review" and arguments.review_command == "record":
        from harness_testing.Code_Reviews import record_review
        from harness_testing.Run_Reports import refresh_local_dashboard

        try:
            outcome = record_review(_repository_root(), arguments.plan, arguments.results)
            refresh_local_dashboard(_repository_root())
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(json.dumps(outcome, indent=2, sort_keys=True))
    elif arguments.command == "collaboration":
        from harness_testing.Collaboration_Grading import prepare_grading, record_grading
        from harness_testing.Run_Reports import refresh_local_dashboard

        try:
            if arguments.collaboration_command == "prepare":
                outcome = prepare_grading(_repository_root(), arguments.report, arguments.protocol)
            elif arguments.collaboration_command == "record":
                outcome = record_grading(_repository_root(), arguments.plan, arguments.results)
                refresh_local_dashboard(_repository_root())
            else:
                parser.error("collaboration requires a subcommand")
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(json.dumps(outcome, indent=2, sort_keys=True, default=str))
    elif arguments.command == "auth" and arguments.auth_command == "claude":
        from harness_testing.Credentials import store_claude_subscription_token

        print("Enter the Claude subscription token in the Keychain prompt.")
        try:
            store_claude_subscription_token()
        except ValueError:
            print("Claude subscription token could not be stored.", file=sys.stderr)
            return 1
        print("Claude subscription token stored in Keychain.")
    elif arguments.command == "campaign":
        from harness_testing.Campaigns import campaign_plan, campaign_summary

        try:
            outcome = (
                campaign_plan(_repository_root(), arguments.manifest)
                if arguments.campaign_command == "plan"
                else campaign_summary(_repository_root(), arguments.plan, arguments.report)
            )
        except (ValueError, KeyError, OSError) as error:
            parser.error(str(error))
        print(json.dumps(outcome, indent=2, sort_keys=True))
        return 0
    elif arguments.command == "run" and arguments.run_command == "plan":
        from harness_testing.Experiments import plan_experiment
        from harness_testing.Runs import format_plan

        manifest = plan_experiment(_repository_root(), json.loads(arguments.request.read_text()))
        print(format_plan(manifest))
        return 0
    elif arguments.command == "run" and arguments.run_command == "execute":
        from harness_testing.Runs import execute_run

        execute_run(_repository_root(), arguments.manifest, arguments.approve)
    elif arguments.command == "task" and arguments.task_command == "qa":
        from harness_testing.QA import QA_CASES, run_task_qa, task_ids_for_pack

        task_ids = (
            (arguments.task,)
            if arguments.task is not None
            else task_ids_for_pack(_repository_root(), arguments.pack)
        )
        cases = QA_CASES if arguments.all_cases else (arguments.case,)
        show_identity = arguments.pack is not None or arguments.all_cases
        for task_id in task_ids:
            for case in cases:
                scores = (
                    run_task_qa(_repository_root(), task_id, case, variant="comparison")
                    if arguments.variant == "comparison"
                    else run_task_qa(_repository_root(), task_id, case)
                )
                summary = " ".join(
                    f"{name}={scores[name]:g}" for name in ("reward", "workflow", "efficiency")
                )
                prefix = f"{task_id}:{case} " if show_identity else ""
                print(f"{prefix}{summary}")
    return 0
